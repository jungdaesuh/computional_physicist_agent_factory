"""C5 cadence parsing over strategy archive summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

C5Outcome = Literal["domain_shift", "no_consensus"]


@dataclass(frozen=True, slots=True)
class StrategyArchiveSummary:
    """Minimal strategy archive view needed by the C5 cadence parser."""

    strategy_sha: str
    summary_md: str


@dataclass(frozen=True, slots=True)
class DomainShift:
    """Approved domain movement extracted from strategy archive summaries."""

    strategy_sha: str
    domain: str
    rationale: str


@dataclass(frozen=True, slots=True)
class C5CadenceResult:
    """C5 direction result; no_consensus is explicit when no shift is extracted."""

    outcome: C5Outcome
    allowed_domain_shifts: tuple[DomainShift, ...]


def parse_c5_cadence(summaries: tuple[StrategyArchiveSummary, ...]) -> C5CadenceResult:
    """Parse allowed-domain shift directives from strategy summaries."""
    shifts: list[DomainShift] = []
    for summary in summaries:
        for raw_line in summary.summary_md.splitlines():
            line = raw_line.strip()
            normalized = line.lower().replace("_", "-")
            if not normalized.startswith("allowed-domain-shift:"):
                continue
            directive = line.split(":", maxsplit=1)[1].strip()
            domain, separator, rationale = directive.partition("|")
            if separator == "":
                rationale = ""
            clean_domain = domain.strip()
            if clean_domain == "":
                continue
            shifts.append(
                DomainShift(
                    strategy_sha=summary.strategy_sha,
                    domain=clean_domain,
                    rationale=rationale.strip(),
                )
            )

    if not shifts:
        return C5CadenceResult(outcome="no_consensus", allowed_domain_shifts=())

    return C5CadenceResult(outcome="domain_shift", allowed_domain_shifts=tuple(shifts))
