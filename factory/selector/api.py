# api.py — Pure-deterministic Simulator Selector logic
#
# This file implements the Simulator Selector class, which deterministically ranks
# simulator candidates from the SimulatorCatalog against a HypothesisSpec using a
# multi-criteria weighted scoring pipeline.
#
# Features:
# 1. Loading and validating weight configuration from weights.yaml.
# 2. Compatibility filtering based on direct matches, equivalence maps, and superset matches.
# 3. Cost estimation using either run telemetry or manifest-specified defaults.
# 4. Cross-simulator partner matching.
# 5. Maintenance signal scoring based on last-commit age.
# 6. Detection of ambiguous near-ties within an epsilon gap.
# 7. Safe error handling (only infra failures raise; selection mismatches return failure modes).

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

import yaml

from factory.artifacts import DomainScope, HypothesisSpec
from factory.catalog import (
    Catalog,
    CatalogEntry,
    EntryStatus,
    SimulatorManifest,
)
from factory.selector.errors import (
    CatalogStaleError,
    SelectorConfigError,
)

CatalogVersionHash = str
ObservableName = str
SimulatorId = str

logger = logging.getLogger("factory.selector.api")


# --------------------------------------------------------------------------
# Protocols and Stubs
# --------------------------------------------------------------------------


@runtime_checkable
class TelemetryReader(Protocol):
    """Protocol for reading historical run telemetry for runtime cost estimation."""

    min_runs_for_confidence: int

    def median_runtime_for(
        self, simulator_id: SimulatorId, observable: ObservableName
    ) -> float | None:
        """Returns median runtime for a simulator/observable pair if confidence is met."""
        ...

    def get_runs(self, simulator_id: SimulatorId, observable: ObservableName) -> list[float]:
        """Returns the list of runtime observations for confidence levels."""
        ...


class TelemetryStub:
    """Mock implementation of the TelemetryReader protocol for testing."""

    def __init__(
        self,
        runs: dict[tuple[SimulatorId, ObservableName], list[float]] | None = None,
        min_runs: int = 5,
    ) -> None:
        logger.info("Initializing TelemetryStub with runs count=%d", len(runs) if runs else 0)
        self.runs = runs or {}
        self.min_runs_for_confidence = min_runs

    def median_runtime_for(
        self, simulator_id: SimulatorId, observable: ObservableName
    ) -> float | None:
        logger.info(
            "TelemetryStub.median_runtime_for(simulator_id=%s, observable=%s)",
            simulator_id,
            observable,
        )
        times = self.runs.get((simulator_id, observable))
        if not times or len(times) < self.min_runs_for_confidence:
            return None
        sorted_times = sorted(times)
        n = len(sorted_times)
        if n % 2 == 1:
            return sorted_times[n // 2]
        return (sorted_times[n // 2 - 1] + sorted_times[n // 2]) / 2.0

    def get_runs(self, simulator_id: SimulatorId, observable: ObservableName) -> list[float]:
        logger.info(
            "TelemetryStub.get_runs(simulator_id=%s, observable=%s)",
            simulator_id,
            observable,
        )
        return self.runs.get((simulator_id, observable), [])

    @classmethod
    def no_history(cls) -> TelemetryStub:
        """Returns a TelemetryStub instance with no history."""
        logger.info("TelemetryStub.no_history() called")
        return cls()


# --------------------------------------------------------------------------
# Data Structures
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CostEstimate:
    """Cost estimation metrics for a simulator run."""

    expected_runtime_seconds: float
    expected_cost_usd: float
    source: Literal["telemetry", "manifest", "fallback_default"]
    confidence: Literal["high", "medium", "low", "unavailable"]


@dataclass(frozen=True)
class Candidate:
    """A scored and evaluated simulator candidate."""

    simulator_id: SimulatorId
    score: float  # weighted sum in [0, 1]
    capability_match: float  # in [0, 1]
    license_ok: bool  # OSI-approved + redistributable
    cost: CostEstimate
    cross_simulator_partners: tuple[SimulatorId, ...]
    maintenance_freshness: float  # in [0, 1]; from last-commit recency
    over_budget: bool  # vs current Budget if provided
    flags: tuple[str, ...]  # e.g. "cost_estimate_missing"
    rationale_lines: tuple[str, ...]  # human-readable scoring breakdown


@dataclass(frozen=True)
class SelectionResult:
    """The deterministic output containing ranked candidates and failure classifications."""

    hypothesis_id: str
    catalog_version_hash: CatalogVersionHash
    weights_hash: str  # hash of config/selector/weights.yaml
    candidates: tuple[Candidate, ...]  # ranked, best first
    cross_simulator_available: bool  # ≥1 candidate has ≥1 partner
    ambiguous: bool  # ≥2 candidates within ambiguity_epsilon
    failure_mode: Literal[
        "ok",
        "no_suitable_simulator",
        "cross_simulator_map_empty",
        "all_over_budget",
    ]
    trace_path: Path  # full reasoning trace JSON


@dataclass(frozen=True)
class SelectorWeights:
    """Configurable coefficients and penalty thresholds."""

    capability_match: float
    license_compliance: float
    cost: float
    cross_simulator_availability: float
    maintenance_freshness: float
    ambiguity_epsilon: float  # score gap below which ties are flagged
    cost_estimate_missing_penalty: float
    over_budget_penalty: float


# --------------------------------------------------------------------------
# Helper Functions
# --------------------------------------------------------------------------


def load_manifest(entry: CatalogEntry) -> SimulatorManifest:
    """Loads a SimulatorManifest from disk, stripping extra fields to conform to Pydantic schema."""
    logger.info("load_manifest(entry=%s) from %s", entry.simulator_id, entry.manifest_path)
    with open(entry.manifest_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    # Filter fields to avoid validation errors due to extra = "forbid"
    allowed_fields = set(SimulatorManifest.model_fields.keys())
    filtered = {k: v for k, v in data.items() if k in allowed_fields}
    return SimulatorManifest(**filtered)


def is_license_ok(entry: CatalogEntry, catalog: Catalog) -> bool:
    """Evaluates if the license and its dependencies are OSI-approved and redistributable."""
    logger.info("is_license_ok(entry=%s)", entry.simulator_id)
    # 1. Read audit report if available
    audit_path = Path(entry.license_audit_report_path)
    if audit_path.is_dir():
        audit_path = audit_path / "license_audit_report.json"
    if audit_path.exists() and audit_path.is_file():
        try:
            with open(audit_path, encoding="utf-8") as f:
                report = json.load(f)
                if report.get("overall_verdict") != "allow":
                    return False
        except Exception as e:
            logger.warning("Failed to parse license audit report at %s: %s", audit_path, e)
            return False
    else:
        # Fallback to checking the manifest license against the catalog's OSI database
        try:
            manifest = load_manifest(entry)
            osi_licenses = getattr(catalog, "_osi_licenses", None)
            if osi_licenses is not None and manifest.license not in osi_licenses:
                return False
        except Exception as e:
            logger.warning("Fallback license check failed: %s", e)
            return False
    return True


# Hardcoded / configurable mapping for superset-to-special-case matching
SUPERSET_MAP: dict[str, list[str]] = {
    "mhd_equilibrium": ["force_balance_residual", "magnetic_well", "iota", "mean_observable"],
    "stellarator_geometry": ["aspect_ratio", "major_radius", "minor_radius"],
}


def domain_scope_allows_entry(
    domain_scope: DomainScope,
    simulator_id: SimulatorId,
    manifest_domain: str,
) -> bool:
    """Return whether a catalog entry is enabled by the current DomainScope."""

    simulator_ids = tuple(str(item) for item in domain_scope.allowed_simulator_ids)
    if simulator_ids and simulator_id not in simulator_ids:
        return False

    allowed_domains = tuple(domain_scope.allowed_domains)
    if not allowed_domains:
        return True

    return any(domain_label_matches(allowed, manifest_domain) for allowed in allowed_domains)


def domain_label_matches(allowed_domain: str, manifest_domain: str) -> bool:
    """Match canonical, case, separator, and family-style domain labels."""

    allowed_tokens = _domain_tokens(allowed_domain)
    manifest_tokens = _domain_tokens(manifest_domain)
    if not allowed_tokens or not manifest_tokens:
        return False
    if allowed_tokens == manifest_tokens:
        return True
    allowed = "-".join(allowed_tokens)
    manifest = "-".join(manifest_tokens)
    if manifest.startswith(f"{allowed}-") or allowed.startswith(f"{manifest}-"):
        return True
    allowed_set = frozenset(allowed_tokens)
    manifest_set = frozenset(manifest_tokens)
    return allowed_set.issubset(manifest_set) or manifest_set.issubset(allowed_set)


def _domain_tokens(label: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^a-z0-9]+", label.lower()) if token)


def check_compatibility(
    entry: CatalogEntry,
    hypothesis: HypothesisSpec,
    catalog: Catalog,
) -> tuple[float, str] | None:
    """Evaluates compatibility of the simulator entry against the hypothesis metric."""
    metric = hypothesis.measurable_metric
    manifest = load_manifest(entry)
    computed = manifest.capabilities.computed_observables

    # 1. Direct match
    if metric in computed:
        return (1.0, f"Direct match: '{metric}' is computed directly")

    # 2. Equivalence-map match
    # Checks if any of our computed observables can be translated to the target metric.
    # We query the catalog's equivalence pairs for the metric.
    try:
        pairs = catalog.equivalence_pairs(metric)
        for p in pairs:
            # If entry has a pair mapped to metric, or we declare the metric in manifest's map
            if p.cross_simulator_id == entry.simulator_id:
                return (
                    0.85,
                    f"Equivalence-map match: '{metric}' is reachable via equivalence mapping",
                )
        for eq in manifest.cross_simulator_equivalence_map:
            if eq.observable == metric:
                return (
                    0.85,
                    f"Equivalence-map match: '{metric}' is declared in local equivalence mapping",
                )
    except Exception as e:
        logger.warning("Equivalence check failed: %s", e)

    # 3. Capability-superset match
    for obs in computed:
        if obs in SUPERSET_MAP and metric in SUPERSET_MAP[obs]:
            return (
                0.70,
                f"Capability-superset match: '{metric}' is a special case of more general '{obs}'",
            )

    return None


def can_cross_validate(
    e_i: CatalogEntry,
    e_j: CatalogEntry,
    observable: str,
) -> bool:
    """Returns True if simulator i and j can cross-validate each other for a given observable."""
    if e_i.simulator_id == e_j.simulator_id:
        return False
    try:
        manifest_i = load_manifest(e_i)
        for eq in manifest_i.cross_simulator_equivalence_map:
            if eq.observable == observable and eq.cross_simulator_id == e_j.simulator_id:
                return True
    except Exception:
        pass
    try:
        manifest_j = load_manifest(e_j)
        for eq in manifest_j.cross_simulator_equivalence_map:
            if eq.observable == observable and eq.cross_simulator_id == e_i.simulator_id:
                return True
    except Exception:
        pass
    return False


# --------------------------------------------------------------------------
# Selector Class
# --------------------------------------------------------------------------


class Selector:
    """Deterministic ranker over the SimulatorCatalog."""

    def __init__(
        self,
        catalog: Catalog,
        weights: SelectorWeights | None = None,
        telemetry: TelemetryReader | None = None,
        weights_path: Path = Path("config/selector/weights.yaml"),
        mock_mode: bool = False,
    ) -> None:
        logger.info(
            "Initializing Selector(weights_path=%s, mock_mode=%s)",
            weights_path,
            mock_mode,
        )
        self.catalog = catalog
        self.telemetry = telemetry
        self.weights_path = weights_path
        self.mock_mode = mock_mode

        if weights is not None:
            self._validate_weights_object(weights)
            self.weights = weights
            self.weights_hash = self._compute_weights_obj_hash(weights)
        else:
            self.weights = self._load_weights(weights_path)
            self.weights_hash = self._compute_weights_file_hash(weights_path)

    def _validate_weights_object(self, weights: SelectorWeights) -> None:
        main_sum = (
            weights.capability_match
            + weights.license_compliance
            + weights.cost
            + weights.cross_simulator_availability
            + weights.maintenance_freshness
        )
        if abs(main_sum - 1.0) > 1e-6:
            raise SelectorConfigError(f"Weights sum must be 1.0 ± 1e-6, got {main_sum}")

    def _load_weights(self, path: Path) -> SelectorWeights:
        if not path.exists():
            raise SelectorConfigError(f"Weights configuration file not found at {path}")
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            raise SelectorConfigError(f"Failed to parse weights configuration: {e}") from e

        required = {
            "capability_match",
            "license_compliance",
            "cost",
            "cross_simulator_availability",
            "maintenance_freshness",
            "ambiguity_epsilon",
            "cost_estimate_missing_penalty",
            "over_budget_penalty",
        }
        for r in required:
            if r not in data:
                raise SelectorConfigError(f"Weights config missing required field: {r}")

        weights = SelectorWeights(
            capability_match=float(data["capability_match"]),
            license_compliance=float(data["license_compliance"]),
            cost=float(data["cost"]),
            cross_simulator_availability=float(data["cross_simulator_availability"]),
            maintenance_freshness=float(data["maintenance_freshness"]),
            ambiguity_epsilon=float(data["ambiguity_epsilon"]),
            cost_estimate_missing_penalty=float(data["cost_estimate_missing_penalty"]),
            over_budget_penalty=float(data["over_budget_penalty"]),
        )
        self._validate_weights_object(weights)
        return weights

    def _compute_weights_obj_hash(self, weights: SelectorWeights) -> str:
        canonical = json.dumps(asdict(weights), sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()

    def _compute_weights_file_hash(self, path: Path) -> str:
        if not path.exists():
            return hashlib.sha256(b"").hexdigest()
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _compute_telemetry_hash(self) -> str:
        if self.telemetry is None:
            return hashlib.sha256(b"").hexdigest()
        runs_dict = getattr(self.telemetry, "runs", None)
        if not runs_dict:
            return hashlib.sha256(b"").hexdigest()
        # Serialize runs dict deterministically
        serialized = []
        for (sim_id, obs), run_times in sorted(runs_dict.items()):
            serialized.append((sim_id, obs, sorted(run_times)))
        canonical = json.dumps(serialized, sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()

    def select(
        self,
        hypothesis_spec: HypothesisSpec,
        budget_dollar_cap: float | None = None,
        domain_scope: DomainScope | None = None,
    ) -> SelectionResult:
        """Deterministically rank active candidates from the SimulatorCatalog.

        Never raises on selection failures; returns SelectionResult with appropriate failure mode.
        Raises SelectorConfigError / CatalogStaleError on infrastructural failures only.
        """
        logger.info(
            "Selector.select(hypothesis_id=%s, budget_dollar_cap=%s) called",
            hypothesis_spec.hypothesis_id,
            budget_dollar_cap,
        )

        catalog_version_start = self.catalog.version_hash()

        # Step 1: Compatibility Filter
        metric = hypothesis_spec.measurable_metric
        # Retrieve active entries that compute this metric directly or via equivalence mapping
        # Note: We query all active entries and check for direct/equivalence/superset matches.
        all_active = self.catalog.list_entries(status=EntryStatus.ACTIVE)

        # Build set of compatible entries
        compatible_map: dict[SimulatorId, tuple[CatalogEntry, float, str]] = {}
        for entry in all_active:
            # Filter out entries flagged disabled in current DomainScope if scope is provided
            if domain_scope is not None:
                manifest = load_manifest(entry)
                if not domain_scope_allows_entry(
                    domain_scope,
                    entry.simulator_id,
                    manifest.domain,
                ):
                    logger.info(
                        "Dropping entry '%s' with domain '%s' as it is not allowed by DomainScope",
                        entry.simulator_id,
                        manifest.domain,
                    )
                    continue

            # Drop entries failing license audit
            if not is_license_ok(entry, self.catalog):
                logger.info(
                    "Dropping entry '%s' because it failed license compliance checks",
                    entry.simulator_id,
                )
                continue

            comp_res = check_compatibility(entry, hypothesis_spec, self.catalog)
            if comp_res is not None:
                subscore, rationale = comp_res
                compatible_map[entry.simulator_id] = (entry, subscore, rationale)

        # Step 2: Cost Estimation & Freshness Scoring
        candidates_raw: list[Candidate] = []

        # Compute cost estimates for all compatible entries
        cost_estimates: dict[SimulatorId, CostEstimate] = {}
        for sim_id, (entry, _, _) in compatible_map.items():
            cost_estimates[sim_id] = self._estimate_cost(entry, hypothesis_spec)

        # Normalize cost subscores comparative to the current candidate set
        cost_subscores: dict[SimulatorId, float] = {}
        if cost_estimates:
            min_cost = min(ce.expected_cost_usd for ce in cost_estimates.values())
            max_cost = max(ce.expected_cost_usd for ce in cost_estimates.values())

            for sim_id, ce in cost_estimates.items():
                if abs(max_cost - min_cost) < 1e-6:
                    norm_cost = 1.0
                else:
                    norm_cost = 1.0 - (ce.expected_cost_usd - min_cost) / (max_cost - min_cost)

                # Apply penalty for fallback_default source
                if ce.source == "fallback_default":
                    norm_cost = max(0.0, norm_cost - self.weights.cost_estimate_missing_penalty)
                cost_subscores[sim_id] = norm_cost

        # Determine cross-simulator availability partners per candidate
        for sim_id, (entry, cap_subscore, cap_rationale) in compatible_map.items():
            partners = []
            for other_id, (other_entry, _, _) in compatible_map.items():
                if can_cross_validate(entry, other_entry, metric):
                    partners.append(other_id)

            # Fetch commit freshness
            freshness = self._calculate_freshness(entry, hypothesis_spec)

            # Subscores
            lic_ok = True  # We filtered out license violations
            xsim_subscore = 1.0 if partners else 0.0
            cost_subscore = cost_subscores.get(sim_id, 0.0)
            ce = cost_estimates[sim_id]

            # Check budget cap
            over_budget = False
            if budget_dollar_cap is not None and ce.expected_cost_usd > budget_dollar_cap:
                over_budget = True

            # Calculate final weighted score
            final_score = (
                self.weights.capability_match * cap_subscore
                + self.weights.license_compliance * (1.0 if lic_ok else 0.0)
                + self.weights.cost * cost_subscore
                + self.weights.cross_simulator_availability * xsim_subscore
                + self.weights.maintenance_freshness * freshness
            )

            # Apply budget penalty
            if over_budget:
                final_score -= self.weights.over_budget_penalty

            # Clamp score to [0.0, 1.0]
            final_score = max(0.0, min(1.0, final_score))

            flags = []
            if ce.source == "fallback_default":
                flags.append("cost_estimate_missing")
            if over_budget:
                flags.append("over_budget")

            rationale_lines = (
                cap_rationale,
                f"License ok: {lic_ok} (subscore: 1.0)",
                (
                    f"Cost estimate: {ce.expected_cost_usd:.4f} USD via '{ce.source}' "
                    f"(subscore: {cost_subscore:.4f})"
                ),
                f"Cross-simulator partners: {sorted(partners)} (subscore: {xsim_subscore:.4f})",
                f"Maintenance freshness: {freshness:.4f} (subscore: {freshness:.4f})",
                f"Final weighted score: {final_score:.4f}",
            )

            candidates_raw.append(
                Candidate(
                    simulator_id=sim_id,
                    score=final_score,
                    capability_match=cap_subscore,
                    license_ok=lic_ok,
                    cost=ce,
                    cross_simulator_partners=tuple(sorted(partners)),
                    maintenance_freshness=freshness,
                    over_budget=over_budget,
                    flags=tuple(flags),
                    rationale_lines=rationale_lines,
                )
            )

        # Sort candidates deterministically: score desc, then simulator_id asc
        sorted_candidates = tuple(sorted(candidates_raw, key=lambda c: (-c.score, c.simulator_id)))

        # Step 3: Rank & Ambiguity Flagging
        ambiguous = False
        if len(sorted_candidates) >= 2:
            gap = sorted_candidates[0].score - sorted_candidates[1].score
            if gap <= self.weights.ambiguity_epsilon:
                ambiguous = True

        # Step 4: Failure-Mode Classification
        cross_simulator_available = any(
            len(c.cross_simulator_partners) >= 1 for c in sorted_candidates
        )

        failure_mode: Literal[
            "ok",
            "no_suitable_simulator",
            "cross_simulator_map_empty",
            "all_over_budget",
        ]
        if not sorted_candidates:
            failure_mode = "no_suitable_simulator"
        elif all(c.over_budget for c in sorted_candidates):
            failure_mode = "all_over_budget"
        elif not cross_simulator_available:
            failure_mode = "cross_simulator_map_empty"
        else:
            failure_mode = "ok"

        # Verify Catalog has not changed during selection execution
        catalog_version_end = self.catalog.version_hash()
        if catalog_version_start != catalog_version_end:
            raise CatalogStaleError("Catalog version changed during selection run")

        # Step 5: Save trace file
        tel_hash = self._compute_telemetry_hash()
        reproducibility_key = (
            hypothesis_spec.provenance_hash,
            catalog_version_start,
            self.weights_hash,
            tel_hash,
        )
        selection_hash = hashlib.sha256(str(reproducibility_key).encode()).hexdigest()

        cycle_id = os.environ.get("FACTORY_CYCLE_ID", "default_cycle")
        trace_dir = Path("runs") / cycle_id / "artifacts"
        trace_path = trace_dir / f"{selection_hash}.trace.json"

        trace_data = {
            "hypothesis_id": hypothesis_spec.hypothesis_id,
            "hypothesis_provenance_hash": hypothesis_spec.provenance_hash,
            "catalog_version_hash": catalog_version_start,
            "weights_hash": self.weights_hash,
            "telemetry_snapshot_hash": tel_hash,
            "weights_applied": asdict(self.weights),
            "candidates_scored": [
                {
                    "simulator_id": c.simulator_id,
                    "score": c.score,
                    "subscores": {
                        "capability_match": c.capability_match,
                        "license_compliance": 1.0 if c.license_ok else 0.0,
                        "cost": cost_subscores.get(c.simulator_id, 0.0),
                        "cross_simulator_availability": 1.0 if c.cross_simulator_partners else 0.0,
                        "maintenance_freshness": c.maintenance_freshness,
                    },
                    "cost_estimate": asdict(c.cost),
                    "cross_simulator_partners": c.cross_simulator_partners,
                    "flags": c.flags,
                    "rationale": c.rationale_lines,
                }
                for c in sorted_candidates
            ],
            "ambiguous": ambiguous,
            "failure_mode": failure_mode,
        }

        try:
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            with open(trace_path, "w", encoding="utf-8") as f:
                json.dump(trace_data, f, indent=2, sort_keys=True)
        except Exception as e:
            logger.warning("Failed to write trace file to %s: %s", trace_path, e)

        # Emit telemetry event
        try:
            from factory.telemetry import emit as tel_emit

            selected_id = sorted_candidates[0].simulator_id if sorted_candidates else None
            tel_emit(
                "factory.selector.simulator_selected",
                {
                    "hypothesis_id": hypothesis_spec.hypothesis_id,
                    "simulator_id": selected_id,
                    "failure_mode": failure_mode,
                },
            )
        except Exception:
            pass

        return SelectionResult(
            hypothesis_id=hypothesis_spec.hypothesis_id,
            catalog_version_hash=catalog_version_start,
            weights_hash=self.weights_hash,
            candidates=sorted_candidates,
            cross_simulator_available=cross_simulator_available,
            ambiguous=ambiguous,
            failure_mode=failure_mode,
            trace_path=trace_path,
        )

    def _estimate_cost(self, entry: CatalogEntry, hypothesis: HypothesisSpec) -> CostEstimate:
        """Determines expected runtime and cost metrics for a candidate entry."""
        metric = hypothesis.measurable_metric

        # 1. Load manifest data
        try:
            with open(entry.manifest_path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
        except Exception:
            raw_data = {}

        # 2. Determine expected runtime
        expected_runtime_seconds = None
        source: Literal["telemetry", "manifest", "fallback_default"] = "telemetry"
        confidence: Literal["high", "medium", "low", "unavailable"] = "medium"

        if self.telemetry is not None:
            expected_runtime_seconds = self.telemetry.median_runtime_for(
                entry.simulator_id, observable=metric
            )
            if expected_runtime_seconds is not None:
                runs = self.telemetry.get_runs(entry.simulator_id, metric)
                if len(runs) >= 10:
                    confidence = "high"
                elif len(runs) >= 5:
                    confidence = "medium"
                else:
                    confidence = "low"

        if expected_runtime_seconds is None:
            source = "manifest"
            confidence = "low"
            expected_runtime_seconds = raw_data.get("expected_runtime_seconds_default")

            if expected_runtime_seconds is None:
                with contextlib.suppress(Exception):
                    expected_runtime_seconds = entry.last_smoke_test.runtime_seconds
            if expected_runtime_seconds is None:
                with contextlib.suppress(Exception):
                    manifest = load_manifest(entry)
                    recipe = manifest.container_recipe
                    expected_runtime_seconds = recipe.expected_smoke_runtime_seconds

        if expected_runtime_seconds is None or expected_runtime_seconds <= 0:
            source = "fallback_default"
            confidence = "unavailable"
            expected_runtime_seconds = 10.0

        # 3. Determine per-second cost
        per_second_cost = raw_data.get("per_second_cost_usd")
        if per_second_cost is None:
            per_second_cost = 0.01  # fallback default

        expected_cost_usd = expected_runtime_seconds * per_second_cost
        return CostEstimate(
            expected_runtime_seconds=float(expected_runtime_seconds),
            expected_cost_usd=float(expected_cost_usd),
            source=source,
            confidence=confidence,
        )

    def _calculate_freshness(self, entry: CatalogEntry, hypothesis: HypothesisSpec) -> float:
        """Calculates soft-decay freshness signal based on last commit age."""
        try:
            manifest = load_manifest(entry)
            commit_date = manifest.maintenance_signal.last_commit_date
            if commit_date is None:
                return 0.0

            # Use deterministic hypothesis creation time as time anchor
            ref_date = hypothesis.created_at
            # Make sure both datetimes are timezone-aware or naive to avoid subtract type mismatch
            if commit_date.tzinfo is not None and ref_date.tzinfo is None:
                ref_date = ref_date.replace(tzinfo=datetime.UTC)
            elif commit_date.tzinfo is None and ref_date.tzinfo is not None:
                commit_date = commit_date.replace(tzinfo=datetime.UTC)

            delta = ref_date - commit_date
            days = float(delta.days)

            # Check unmaintained flag in raw manifest data
            try:
                with open(entry.manifest_path, encoding="utf-8") as f:
                    raw_data = yaml.safe_load(f)
                unmaintained_flag = raw_data.get("unmaintained_flag", False)
            except Exception:
                unmaintained_flag = False

            if days > 730 or unmaintained_flag:
                return 0.0
            if days <= 180:
                return 1.0

            # Linear decay from 180 to 730 days
            return 1.0 - (days - 180.0) / (730.0 - 180.0)
        except Exception as e:
            logger.warning("Freshness calculation failed: %s", e)
            return 0.0

    def explain(
        self,
        result: SelectionResult,
        candidate_id: SimulatorId,
    ) -> str:
        """Returns the human-readable rationale for one candidate's score."""
        logger.info("Selector.explain(candidate_id=%s) called", candidate_id)
        for cand in result.candidates:
            if cand.simulator_id == candidate_id:
                return "\n".join(cand.rationale_lines)
        return f"Candidate {candidate_id} not found in the selection result."

    @classmethod
    def mock_default(cls) -> Selector:
        """Constructs a default mock Selector pre-configured with catalog fixture 'phase_a'."""
        logger.info("Selector.mock_default() called")
        catalog = Catalog.from_fixture("phase_a")
        return cls(
            catalog=catalog,
            telemetry=TelemetryStub.no_history(),
            weights_path=Path("config/selector/weights.yaml"),
            mock_mode=True,
        )
