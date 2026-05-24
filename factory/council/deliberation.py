# deliberation.py — Decision Council Deliberation Engine
#
# This file implements the three-stage deliberation protocol:
# 1. First Opinions (Stage 1): Parallel solicitation of structured opinions
#    from heterogeneous models, each operating under a distinct persona.
# 2. Anonymized Cross-Review (Stage 2): Anonymized cross-critique and ranking of
#    Stage 1 opinions by each council member to prevent sycophancy/bandwagoning.
# 3. Chairman Synthesis (Stage 3): Selection of a chairman model to synthesize
#    the majority view and preserve all material dissenting opinions.
#
# Use cases:
# - Run three-stage deliberation for decision gates (C1-C5).
# - Run calibration probes to audit lineup disagreement rate.
# - Enforce multi-vendor/persona diversity and detect sycophancy.

from __future__ import annotations

import concurrent.futures
import json
import logging
import random
import time
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import yaml

from factory.artifacts import (
    ArtifactHash,
    CouncilId,
    CouncilVerdict,
    DissentEntry,
    HypothesisId,
    PersonaName,
)
from factory.council.chairman import (
    NLIDissentValidator,
    PricingTable,
    load_pricing_table_wrapper,
    reprompt_chairman,
    select_chairman,
)
from factory.council.errors import (
    BudgetTokenUsageMissing,
    ChairmanDissentOmission,
    CouncilError,
    CouncilSycophancyDetected,
    ModelTimeout,
    OpenRouterError,
    PersonaRefusal,
)
from factory.council.types import (
    CalibrationReport,
    CouncilContext,
    CouncilLineup,
    FirstOpinion,
    ModelSpec,
    ProbeResult,
)
from factory.llm_client import (
    DecisionClient,
    OpenRouterClient,
    OpenRouterMessage,
    OpenRouterResponse,
    OpenRouterResponseFormat,
)

logger = logging.getLogger("factory.council.deliberation")

if TYPE_CHECKING:
    from factory.budget import BudgetTracker


class SycophancyDetector:
    """Detects sycophancy by computing semantic similarity across first opinions.

    Uses sentence-transformers/all-mpnet-base-v2 (local and vendor-agnostic)
    to calculate pairwise cosine similarities. If any pair exceeds the 0.85
    threshold, the lineup is flagged for groupthink.
    """

    def __init__(self, mock_mode: bool = False) -> None:
        """Initializes the Sycophancy Detector.

        Args:
            mock_mode: If True, uses word overlap similarity instead of sentence-transformers.
        """
        logger.info("SycophancyDetector.__init__ called with mock_mode=%s", mock_mode)
        self.mock_mode = mock_mode
        self._model = None

        if not mock_mode:
            try:
                from sentence_transformers import SentenceTransformer

                logger.info("Loading sentence-transformers/all-mpnet-base-v2")
                self._model = SentenceTransformer("sentence-transformers/all-mpnet-base-v2")
                logger.info("SentenceTransformer loaded successfully.")
            except Exception as e:
                raise CouncilError(
                    "Could not load sentence-transformers/all-mpnet-base-v2 for live "
                    "sycophancy detection."
                ) from e

    def detect_sycophancy(
        self,
        opinions: Sequence[FirstOpinion],
    ) -> float:
        """Computes the maximum pairwise cosine similarity among first opinions.

        Args:
            opinions: The list of first opinions from Stage 1.

        Returns:
            The maximum pairwise cosine similarity value.
        """
        n = len(opinions)
        if n < 2:
            return 0.0

        if self.mock_mode:
            sims = []
            for i in range(n):
                for j in range(i + 1, n):
                    sims.append(self.mock_cosine_similarity(opinions[i].view, opinions[j].view))
            return max(sims)
        if self._model is None:
            raise CouncilError("Sycophancy detector model is not initialized.")

        import numpy as np

        embeddings = self._model.encode([o.view for o in opinions])
        sims = []
        for i in range(n):
            for j in range(i + 1, n):
                emb1 = embeddings[i]
                emb2 = embeddings[j]
                dot = np.dot(emb1, emb2)
                norm1 = np.linalg.norm(emb1)
                norm2 = np.linalg.norm(emb2)
                cos = 0.0 if norm1 == 0.0 or norm2 == 0.0 else float(dot / (norm1 * norm2))
                sims.append(cos)
        return max(sims)

    def mock_cosine_similarity(self, text1: str, text2: str) -> float:
        """Jaccard-like word overlap cosine similarity for mock mode.

        Args:
            text1: First opinion text.
            text2: Second opinion text.

        Returns:
            The overlap score between 0.0 and 1.0.
        """
        import re

        words1 = re.findall(r"\w+", text1.lower())
        words2 = re.findall(r"\w+", text2.lower())
        if not words1 or not words2:
            return 0.0
        from collections import Counter

        c1 = Counter(words1)
        c2 = Counter(words2)
        intersection = sum((c1 & c2).values())
        norm1 = sum(v**2 for v in c1.values()) ** 0.5
        norm2 = sum(v**2 for v in c2.values()) ** 0.5
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return float(intersection / (norm1 * norm2))


class Council:
    """The central deliberation engine coordinating the decision council stages."""

    def __init__(
        self,
        lineup: CouncilLineup,
        session_dir: Path,
        cost_cap_usd: float | None = None,
        mock_mode: bool = False,
        budget_tracker: BudgetTracker | None = None,
        pricing_table: PricingTable | None = None,
        http_referer: str | None = None,
    ) -> None:
        """Initializes the Council Deliberation engine.

        Args:
            lineup: A validated CouncilLineup instance.
            session_dir: Path to write session logs to.
            cost_cap_usd: Optional cost cap, halting execution if reached.
            mock_mode: If True, uses mock LLM clients and offline evaluation.
            budget_tracker: Optional BudgetTracker context.
            pricing_table: Optional PricingTable mapping model IDs to rates.
            http_referer: Optional ranking header override.
        """
        logger.info(
            "Council.__init__ called with lineup models: %s, session_dir: %s, "
            "cost_cap: %s, mock_mode: %s",
            [m.openrouter_id for m in lineup.models],
            session_dir,
            cost_cap_usd,
            mock_mode,
        )
        self.lineup = lineup
        self.session_dir = session_dir
        self.cost_cap_usd = cost_cap_usd
        self.mock_mode = mock_mode
        self.budget_tracker = budget_tracker
        self.pricing_table = pricing_table or load_pricing_table_wrapper()
        self.http_referer = http_referer
        self.session_counter = 0

    def log_event(self, session_id: str, event_data: dict[str, Any]) -> None:
        """Logs a session event to the target JSONL file.

        Args:
            session_id: Current session ID.
            event_data: Event properties to log.
        """
        self.session_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.session_dir / f"{session_id}.jsonl"
        payload = {"ts": datetime.utcnow().isoformat(), **event_data}
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def _is_refusal(self, text: str) -> bool:
        """Checks if a model response indicates a refusal or safety policy block.

        Args:
            text: Raw model output.

        Returns:
            True if the response text looks like a refusal.
        """
        text_lower = text.lower()
        refusal_keywords = [
            "i cannot fulfill",
            "i am unable to",
            "my safety guidelines",
            "as an ai",
            "inappropriate",
            "offensive",
            "cannot provide",
            "violates",
        ]
        return any(kw in text_lower for kw in refusal_keywords)

    def _raise_mapped_exception(self, model: str, exc: Exception) -> None:
        """Maps standard exceptions to council-specific hierarchy.

        Args:
            model: The target model ID.
            exc: The caught raw exception.
        """
        exc_str = str(exc).lower()
        if "timeout" in exc_str or "connection" in exc_str:
            raise ModelTimeout(f"Model call to {model} timed out: {exc}") from exc
        if "unauthorized" in exc_str or "auth" in exc_str:
            raise OpenRouterError(f"Authentication failed for {model}: {exc}") from exc
        if "rate limit" in exc_str:
            raise OpenRouterError(f"Rate limit exceeded for {model}: {exc}") from exc
        if isinstance(exc, json.JSONDecodeError):
            raw_text = getattr(exc, "doc", "")
            if self._is_refusal(raw_text):
                raise PersonaRefusal(f"Persona refusal from {model}: {raw_text}") from exc
            raise OpenRouterError(f"Failed to parse JSON response from {model}: {exc}") from exc
        if isinstance(exc, BudgetTokenUsageMissing):
            raise exc

        raise OpenRouterError(f"OpenRouter error for {model}: {exc}") from exc

    def deliberate(
        self,
        council_id: CouncilId,
        question: str,
        context: CouncilContext,
        parent_hashes: Sequence[ArtifactHash] = (),
    ) -> CouncilVerdict:
        """Runs the three-stage decision deliberation protocol.

        Args:
            council_id: The ID representing the specific gate.
            question: The objective scientific question.
            context: Serialized parent artifact details.
            parent_hashes: Optional list of parent artifact hashes.

        Returns:
            A finalized CouncilVerdict.
        """
        logger.info(
            "Council.deliberate called: council_id=%s, question=%r, parent_hashes_count=%d",
            council_id,
            question,
            len(parent_hashes),
        )
        session_start_time = time.perf_counter()
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        project_root = Path(__file__).resolve().parents[2]

        # Extract hypothesis ID for budget tracking
        hypothesis_id_val = context.get("hypothesis_id")
        hypothesis_id = HypothesisId(str(hypothesis_id_val)) if hypothesis_id_val else None

        # Standard models list representation
        lineup_models_log = [
            {
                "openrouter_id": m.openrouter_id,
                "vendor": m.vendor,
                "persona": self.lineup.persona_assignment[m.openrouter_id],
            }
            for m in self.lineup.models
        ]

        # Log session start
        self.log_event(
            session_id,
            {
                "event": "session_start",
                "council_id": council_id.value if hasattr(council_id, "value") else str(council_id),
                "lineup_models": lineup_models_log,
                "chairman_policy": self.lineup.chairman_policy,
                "chairman_model_id": "TBD",
            },
        )

        running_cost = 0.0
        total_tokens = 0

        # Choose Client
        client: DecisionClient
        if self.mock_mode:
            from factory.council.mock import MockOpenRouterClient

            client = MockOpenRouterClient()
        elif self.http_referer is None:
            client = OpenRouterClient()
        else:
            client = OpenRouterClient(http_referer=self.http_referer)

        # Shared LLM invoker helper
        def call_llm(
            messages: Sequence[OpenRouterMessage],
            model_spec: ModelSpec,
            response_format: OpenRouterResponseFormat | None,
            stage_desc: str,
        ) -> OpenRouterResponse:
            nonlocal running_cost, total_tokens
            logger.info("Calling LLM model=%s for %s", model_spec.openrouter_id, stage_desc)

            t_start = time.perf_counter()
            response: OpenRouterResponse | None = None
            last_err: Exception | None = None

            for attempt in range(2):
                try:
                    response = client.invoke(
                        messages=messages,
                        model=model_spec.openrouter_id,
                        max_tokens=model_spec.max_tokens,
                        response_format=response_format,
                    )
                    if response_format and response_format.get("type") == "json_object":
                        # Validate JSON correctness
                        json.loads(response.text)
                    break
                except Exception as e:
                    last_err = e
                    if attempt == 0:
                        logger.warning(
                            "Call to %s failed: %s. Retrying once.",
                            model_spec.openrouter_id,
                            e,
                        )
                    else:
                        logger.error(
                            "Retry call to %s failed: %s",
                            model_spec.openrouter_id,
                            e,
                        )

            if response is None:
                assert last_err is not None
                self._raise_mapped_exception(model_spec.openrouter_id, last_err)
                raise RuntimeError("Unreachable")  # satisfy typechecker

            t_end = time.perf_counter()
            duration = t_end - t_start

            if response.input_tokens is None or response.output_tokens is None:
                raise BudgetTokenUsageMissing(
                    module="council",
                    model_id=model_spec.openrouter_id,
                    description="usage block absent",
                )

            # Pricing lookup & cost aggregation
            input_price_1m = self.pricing_table.lookup(model_spec.openrouter_id, "input")
            output_price_1m = self.pricing_table.lookup(model_spec.openrouter_id, "output")
            call_cost = (response.input_tokens * input_price_1m / 1_000_000.0) + (
                response.output_tokens * output_price_1m / 1_000_000.0
            )

            running_cost += call_cost
            total_tokens += response.input_tokens + response.output_tokens

            if self.budget_tracker and hypothesis_id:
                self.budget_tracker.record(
                    hypothesis_id=hypothesis_id,
                    module="council",
                    cost_usd=call_cost,
                    tokens=response.input_tokens + response.output_tokens,
                    wall_clock_seconds=duration,
                    description=f"{stage_desc}: {model_spec.openrouter_id}",
                )

            return response

        # ----------------------------------------------------------------------
        # STAGE 1: First Opinions
        # ----------------------------------------------------------------------
        logger.info("Executing Council Stage 1 (First Opinions)")
        if self.cost_cap_usd is not None and running_cost > self.cost_cap_usd:
            return self._build_no_consensus_verdict(
                council_id, question, parent_hashes, session_id, running_cost, 0.0
            )

        first_opinions: list[FirstOpinion] = []

        def run_stage1_model(model_spec: ModelSpec) -> FirstOpinion:
            persona = self.lineup.persona_assignment[model_spec.openrouter_id]
            template_path = (
                project_root / "config" / "council" / "personas" / f"{persona.lower()}.md"
            )
            with open(template_path, encoding="utf-8") as f:
                template_content = f.read()

            context_str = json.dumps(context, indent=2)
            rendered_instruction = template_content.format(
                council_id=council_id.value if hasattr(council_id, "value") else str(council_id),
                context=context_str,
                question=question,
            )

            self.log_event(
                session_id,
                {
                    "event": "stage1_prompt",
                    "model_id": model_spec.openrouter_id,
                    "vendor": model_spec.vendor,
                    "persona": persona,
                    "system_instruction": rendered_instruction,
                    "user_content": question,
                },
            )

            messages = [
                {"role": "system", "content": rendered_instruction},
                {
                    "role": "user",
                    "content": (
                        "Please analyze the question and context, and output your view "
                        "and self_rank in the specified JSON format."
                    ),
                },
            ]

            response = call_llm(
                messages,
                model_spec,
                response_format={"type": "json_object"},
                stage_desc="stage1",
            )

            # Price calculations for specific call log
            in_rate = self.pricing_table.lookup(model_spec.openrouter_id, "input")
            out_rate = self.pricing_table.lookup(model_spec.openrouter_id, "output")
            op_cost = (response.input_tokens * in_rate / 1e6) + (
                response.output_tokens * out_rate / 1e6
            )

            self.log_event(
                session_id,
                {
                    "event": "stage1_response",
                    "model_id": model_spec.openrouter_id,
                    "model_id_actual": response.model_id_actual,
                    "response": response.text,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": op_cost,
                },
            )

            res_json = json.loads(response.text)
            view = res_json.get("view", "")
            self_rank = int(res_json.get("self_rank", 3))

            return FirstOpinion(
                openrouter_id=model_spec.openrouter_id,
                vendor=model_spec.vendor,
                persona=persona,
                view=view,
                self_rank=self_rank,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.lineup.models)) as executor:
            futures = [executor.submit(run_stage1_model, m) for m in self.lineup.models]
            for i, fut in enumerate(futures):
                m = self.lineup.models[i]
                try:
                    opinion = fut.result()
                    first_opinions.append(opinion)
                except Exception as e:
                    logger.error("Stage 1 failed for model %s: %s", m.openrouter_id, e)
                    raise CouncilError(
                        f"Stage 1 failed for model {m.openrouter_id}; "
                        "all council vendors must complete."
                    ) from e

        if len(first_opinions) != len(self.lineup.models):
            raise CouncilError(
                f"Stage 1 aborted: expected {len(self.lineup.models)} first opinions, "
                f"got {len(first_opinions)}."
            )

        # ----------------------------------------------------------------------
        # Sycophancy Check
        # ----------------------------------------------------------------------
        detector = SycophancyDetector(mock_mode=self.mock_mode)
        max_agreement = detector.detect_sycophancy(first_opinions)
        logger.info("Sycophancy check max agreement = %f", max_agreement)
        if max_agreement > 0.85:
            self.log_event(
                session_id, {"event": "sycophancy_detected", "max_agreement": max_agreement}
            )
            raise CouncilSycophancyDetected(
                f"Sycophancy detected: max agreement {max_agreement:.3f} > threshold 0.85"
            )

        # ----------------------------------------------------------------------
        # STAGE 2: Anonymized Cross-Review
        # ----------------------------------------------------------------------
        logger.info("Executing Council Stage 2 (Anonymized Cross-Review)")
        if self.cost_cap_usd is not None and running_cost > self.cost_cap_usd:
            return self._build_no_consensus_verdict(
                council_id,
                question,
                parent_hashes,
                session_id,
                running_cost,
                time.perf_counter() - session_start_time,
            )

        # Assign letters by random shuffle
        shuffled_opinions = list(first_opinions)
        random.shuffle(shuffled_opinions)
        voices = ["A", "B", "C", "D"][: len(shuffled_opinions)]
        voice_to_opinion = {voices[i]: shuffled_opinions[i] for i in range(len(shuffled_opinions))}
        opinion_to_voice = {shuffled_opinions[i]: voices[i] for i in range(len(shuffled_opinions))}

        opinions_block = ""
        for voice, op in voice_to_opinion.items():
            opinions_block += f"Voice {voice}:\n{op.view}\n\n"

        reviewer_results: dict[str, dict[str, Any]] = {}

        def run_stage2_model(model_spec: ModelSpec) -> tuple[str, dict[str, Any]]:
            matching_ops = [
                op for op in first_opinions if op.openrouter_id == model_spec.openrouter_id
            ]
            if not matching_ops:
                raise CouncilError(
                    f"Stage 2 missing Stage 1 opinion for model {model_spec.openrouter_id}; "
                    "all council vendors must participate."
                )

            op = matching_ops[0]
            reviewer_voice = opinion_to_voice[op]
            reviewees = [v for v in voices if v != reviewer_voice]

            persona = self.lineup.persona_assignment[model_spec.openrouter_id]

            system_instruction = (
                f"You are a reviewer for a decision council. "
                f"Your persona is {persona.value if hasattr(persona, 'value') else persona}. "
                f"Analyze the anonymized opinions of the other members.\n"
                f"Provide your rankings and critiques in JSON format matching the schema:\n"
                f"{{\n"
                f'  "rankings": {{\n'
                f'    "A": <integer rank 1-N>,\n'
                f'    "B": <integer rank 1-N>,\n'
                f"    ...\n"
                f"  }},\n"
                f'  "critiques": {{\n'
                f'    "A": "<one-line critique>",\n'
                f'    "B": "<one-line critique>",\n'
                f"    ...\n"
                f"  }}\n"
                f"}}"
            )

            user_content = (
                f"Here are the first opinions of the other council members:\n\n"
                f"{opinions_block}\n"
                f"Please rank and critique them anonymized as Voice letters."
            )

            self.log_event(
                session_id,
                {
                    "event": "stage2_anonymized_prompt",
                    "reviewer_voice": reviewer_voice,
                    "reviewees": reviewees,
                    "user_content": user_content,
                },
            )

            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ]

            response = call_llm(
                messages,
                model_spec,
                response_format={"type": "json_object"},
                stage_desc="stage2",
            )

            res_json = json.loads(response.text)
            rankings = res_json.get("rankings")
            critiques = res_json.get("critiques")
            if not isinstance(rankings, dict) or not isinstance(critiques, dict):
                raise CouncilError(
                    f"Stage 2 response from {model_spec.openrouter_id} is missing "
                    "rankings or critiques."
                )

            in_rate = self.pricing_table.lookup(model_spec.openrouter_id, "input")
            out_rate = self.pricing_table.lookup(model_spec.openrouter_id, "output")
            op_cost = (response.input_tokens * in_rate / 1e6) + (
                response.output_tokens * out_rate / 1e6
            )
            self.log_event(
                session_id,
                {
                    "event": "stage2_response",
                    "model_id": model_spec.openrouter_id,
                    "model_id_actual": response.model_id_actual,
                    "reviewer_voice": reviewer_voice,
                    "rankings": rankings,
                    "critiques": critiques,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": op_cost,
                },
            )
            return model_spec.openrouter_id, res_json

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=len(self.lineup.models)
        ) as executor_s2:
            futures_s2 = [executor_s2.submit(run_stage2_model, m) for m in self.lineup.models]
            for i, fut_s2 in enumerate(futures_s2):
                m = self.lineup.models[i]
                try:
                    m_id, res = fut_s2.result()
                    reviewer_results[m_id] = res
                except Exception as e:
                    logger.error("Stage 2 failed for model %s: %s", m.openrouter_id, e)
                    raise CouncilError(
                        f"Stage 2 failed for model {m.openrouter_id}; "
                        "all council vendors must complete cross-review."
                    ) from e

        if len(reviewer_results) != len(self.lineup.models):
            raise CouncilError(
                f"Stage 2 aborted: expected {len(self.lineup.models)} reviewer results, "
                f"got {len(reviewer_results)}."
            )

        # ----------------------------------------------------------------------
        # STAGE 3: Chairman Synthesis
        # ----------------------------------------------------------------------
        logger.info("Executing Council Stage 3 (Chairman Synthesis)")
        if self.cost_cap_usd is not None and running_cost > self.cost_cap_usd:
            return self._build_no_consensus_verdict(
                council_id,
                question,
                parent_hashes,
                session_id,
                running_cost,
                time.perf_counter() - session_start_time,
            )

        chairman_model = select_chairman(self.lineup, self.session_counter, self.pricing_table)
        self.session_counter += 1

        opinions_with_labels = ""
        for op in first_opinions:
            persona = op.persona.value if hasattr(op.persona, "value") else op.persona
            opinions_with_labels += (
                f"- Model: {op.openrouter_id} (Vendor: {op.vendor}, Persona: {persona})\n"
                f"  Opinion: {op.view}\n"
                f"  Self-confidence rank: {op.self_rank}\n\n"
            )

        reviews_with_labels = ""
        for m_id, res in reviewer_results.items():
            matching_ops = [op for op in first_opinions if op.openrouter_id == m_id]
            if not matching_ops:
                continue
            op = matching_ops[0]
            voice = opinion_to_voice[op]
            rankings = res.get("rankings", {})
            critiques = res.get("critiques", {})
            persona = op.persona.value if hasattr(op.persona, "value") else op.persona

            reviews_with_labels += (
                f"- Model: {op.openrouter_id} (Vendor: {op.vendor}, "
                f"Persona: {persona}), voice label: {voice}\n"
                f"  Reviews:\n"
            )
            for r_voice, rank in rankings.items():
                target_op = voice_to_opinion.get(r_voice)
                if target_op:
                    target_persona = (
                        target_op.persona.value
                        if hasattr(target_op.persona, "value")
                        else target_op.persona
                    )
                    target_desc = f"{target_op.openrouter_id} ({target_persona})"
                else:
                    target_desc = f"Voice {r_voice}"
                critique = critiques.get(r_voice, "")
                reviews_with_labels += (
                    f"    * Ranked {target_desc} as {rank}. Critique: {critique}\n"
                )
            reviews_with_labels += "\n"

        chairman_persona = self.lineup.persona_assignment[chairman_model.openrouter_id]
        template_path = (
            project_root / "config" / "council" / "personas" / f"{chairman_persona.lower()}.md"
        )
        with open(template_path, encoding="utf-8") as f:
            template_content = f.read()

        context_str = json.dumps(context, indent=2)
        rendered_instruction = template_content.format(
            council_id=council_id.value if hasattr(council_id, "value") else str(council_id),
            context=context_str,
            question=question,
        )

        chairman_system_instruction = (
            f"{rendered_instruction}\n\n"
            f"You have been selected as the Chairman for this deliberation cycle. "
            f"Your task is to synthesize the opinions and reviews of the council "
            f"members into a final decision.\n"
            f"You MUST output a JSON object matching this exact schema:\n"
            f"{{\n"
            f'  "majority_view": "1-3 paragraphs summarizing the majority position",\n'
            f'  "preserved_dissents": [\n'
            f"    {{\n"
            f'      "model_id": "<model_id of the dissenting model>",\n'
            f'      "persona": "<persona of the dissenting model>",\n'
            f'      "view": "<dissenting view summarized>",\n'
            f'      "rationale": "<detailed rationale for this dissent>"\n'
            f"    }}\n"
            f"  ],\n"
            f'  "chairman_decision": "approve" | "reject" | "qualified" | "no_consensus"\n'
            f"}}"
        )

        chairman_user_content = (
            f"Original question: {question}\n\n"
            f"Stage 1 First Opinions:\n{opinions_with_labels}\n"
            f"Stage 2 Cross-Review Matrix:\n{reviews_with_labels}\n"
            f"Please synthesize the deliberation and generate the final JSON output."
        )

        self.log_event(
            session_id,
            {
                "event": "stage3_chairman_prompt",
                "chairman_model_id": chairman_model.openrouter_id,
                "user_content": chairman_user_content,
            },
        )

        messages = [
            {"role": "system", "content": chairman_system_instruction},
            {"role": "user", "content": chairman_user_content},
        ]

        response = call_llm(
            messages,
            chairman_model,
            response_format={"type": "json_object"},
            stage_desc="stage3",
        )

        res_json = json.loads(response.text)
        in_rate = self.pricing_table.lookup(chairman_model.openrouter_id, "input")
        out_rate = self.pricing_table.lookup(chairman_model.openrouter_id, "output")
        op_cost = (response.input_tokens * in_rate / 1e6) + (
            response.output_tokens * out_rate / 1e6
        )
        self.log_event(
            session_id,
            {
                "event": "stage3_response",
                "model_id": chairman_model.openrouter_id,
                "model_id_actual": response.model_id_actual,
                "chairman_decision": res_json.get("chairman_decision", ""),
                "majority_view": res_json.get("majority_view", ""),
                "preserved_dissents": res_json.get("preserved_dissents", []),
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cost_usd": op_cost,
            },
        )

        # Parse synthesis
        majority_view = res_json.get("majority_view", "")
        chairman_decision_str = res_json.get("chairman_decision", "no_consensus")
        if chairman_decision_str not in ("approve", "reject", "qualified", "no_consensus"):
            chairman_decision_str = "no_consensus"
        chairman_decision = cast(
            Literal["approve", "reject", "qualified", "no_consensus"], chairman_decision_str
        )

        raw_dissents = res_json.get("preserved_dissents", [])
        preserved_dissents = []
        for d in raw_dissents:
            preserved_dissents.append(
                DissentEntry(
                    model_id=d.get("model_id", ""),
                    persona=PersonaName(d.get("persona", "").lower()),
                    view=d.get("view", ""),
                    rationale=d.get("rationale", ""),
                )
            )

        # Verify via NLI Dissent Validator
        validator = NLIDissentValidator(mock_mode=self.mock_mode)
        omitted = validator.check_dissent_omission(
            majority_view=majority_view,
            first_opinions=first_opinions,
            preserved_dissents=preserved_dissents,
            threshold=0.60,
        )

        if omitted:
            logger.warning(
                "Dissent omission detected: %s. Re-prompting chairman once.",
                [o.openrouter_id for o in omitted],
            )
            reprompted_messages = reprompt_chairman(
                original_messages=messages,
                first_response_text=response.text,
                omitted_opinions=omitted,
            )

            response = call_llm(
                reprompted_messages,
                chairman_model,
                response_format={"type": "json_object"},
                stage_desc="stage3_reprompt",
            )

            res_json = json.loads(response.text)
            in_rate = self.pricing_table.lookup(chairman_model.openrouter_id, "input")
            out_rate = self.pricing_table.lookup(chairman_model.openrouter_id, "output")
            op_cost = (response.input_tokens * in_rate / 1e6) + (
                response.output_tokens * out_rate / 1e6
            )
            self.log_event(
                session_id,
                {
                    "event": "stage3_reprompt_response",
                    "model_id": chairman_model.openrouter_id,
                    "model_id_actual": response.model_id_actual,
                    "chairman_decision": res_json.get("chairman_decision", ""),
                    "majority_view": res_json.get("majority_view", ""),
                    "preserved_dissents": res_json.get("preserved_dissents", []),
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": op_cost,
                },
            )

            majority_view = res_json.get("majority_view", "")
            chairman_decision_str = res_json.get("chairman_decision", "no_consensus")
            if chairman_decision_str not in ("approve", "reject", "qualified", "no_consensus"):
                chairman_decision_str = "no_consensus"
            chairman_decision = cast(
                Literal["approve", "reject", "qualified", "no_consensus"], chairman_decision_str
            )

            raw_dissents = res_json.get("preserved_dissents", [])
            preserved_dissents = []
            for d in raw_dissents:
                preserved_dissents.append(
                    DissentEntry(
                        model_id=d.get("model_id", ""),
                        persona=PersonaName(d.get("persona", "").lower()),
                        view=d.get("view", ""),
                        rationale=d.get("rationale", ""),
                    )
                )

            # Final validation check after re-prompt
            omitted_final = validator.check_dissent_omission(
                majority_view=majority_view,
                first_opinions=first_opinions,
                preserved_dissents=preserved_dissents,
                threshold=0.60,
            )
            if omitted_final:
                raise ChairmanDissentOmission(
                    "Chairman model failed to include required dissents after re-prompt."
                )

        # ----------------------------------------------------------------------
        # VERDICT ASSEMBLY
        # ----------------------------------------------------------------------
        wall_clock_seconds = time.perf_counter() - session_start_time

        verdict = CouncilVerdict(
            artifact_type="CouncilVerdict",
            created_at=datetime.utcnow(),
            provenance_hash="0" * 64,
            parent_hashes=tuple(parent_hashes),
            council_id=council_id,
            question=question,
            model_lineup=tuple(m.openrouter_id for m in self.lineup.models),
            persona_assignment=self.lineup.persona_assignment,
            chairman_model=chairman_model.openrouter_id,
            majority_view=majority_view,
            preserved_dissents=tuple(preserved_dissents),
            chairman_decision=chairman_decision,
            total_cost_usd=running_cost,
            wall_clock_seconds=wall_clock_seconds,
            session_id=session_id,
        )

        computed_hash = verdict.compute_hash()
        verdict = verdict.model_copy(update={"provenance_hash": computed_hash})

        self.log_event(
            session_id,
            {
                "event": "session_end",
                "verdict_hash": computed_hash,
                "total_cost_usd": running_cost,
                "wall_clock_s": wall_clock_seconds,
            },
        )

        return verdict

    def _build_no_consensus_verdict(
        self,
        council_id: CouncilId,
        question: str,
        parent_hashes: Sequence[ArtifactHash],
        session_id: str,
        total_cost: float,
        wall_clock: float,
    ) -> CouncilVerdict:
        """Construct a no-consensus fallback verdict."""
        verdict = CouncilVerdict(
            artifact_type="CouncilVerdict",
            created_at=datetime.utcnow(),
            provenance_hash="0" * 64,
            parent_hashes=tuple(parent_hashes),
            council_id=council_id,
            question=question,
            model_lineup=tuple(m.openrouter_id for m in self.lineup.models),
            persona_assignment=self.lineup.persona_assignment,
            chairman_model=self.lineup.models[0].openrouter_id,
            majority_view="Halted due to budget limit or other failure. Consensus was not reached.",
            preserved_dissents=(),
            chairman_decision="no_consensus",
            total_cost_usd=total_cost,
            wall_clock_seconds=wall_clock,
            session_id=session_id,
        )
        computed = verdict.compute_hash()
        return verdict.model_copy(update={"provenance_hash": computed})

    def calibrate(
        self,
        probe_set: Path | None = None,
    ) -> CalibrationReport:
        """Run divisive probes against the current lineup."""
        project_root = Path(__file__).resolve().parents[2]
        probes_path = probe_set or project_root / "config" / "council" / "probes.yaml"

        logger.info("Council.calibrate called with probes_path=%s", probes_path)

        with open(probes_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        probes = data.get("probes", [])

        # Choose appropriate client
        client: DecisionClient
        if self.mock_mode:
            from factory.council.mock import MockOpenRouterClient

            client = MockOpenRouterClient()
        else:
            client = OpenRouterClient()

        probe_results: list[ProbeResult] = []
        detector = SycophancyDetector(mock_mode=self.mock_mode)

        for probe in probes:
            probe_id = probe.get("id", "")
            probe_question = probe.get("question", "")
            logger.info("Running calibration probe %s: %r", probe_id, probe_question)

            # Retrieve first opinions from the 4 models in parallel
            opinions: list[FirstOpinion] = []

            def run_probe_model(
                model_spec: ModelSpec,
                probe_question: str = probe_question,
            ) -> FirstOpinion:
                persona = self.lineup.persona_assignment[model_spec.openrouter_id]
                template_path = (
                    project_root / "config" / "council" / "personas" / f"{persona.lower()}.md"
                )
                with open(template_path, encoding="utf-8") as f:
                    template_content = f.read()

                rendered_instruction = template_content.format(
                    council_id="CALIBRATION",
                    context="Calibration Probe Context",
                    question=probe_question,
                )

                messages = [
                    {"role": "system", "content": rendered_instruction},
                    {
                        "role": "user",
                        "content": (
                            "Please analyze the question and context, and output your "
                            "view and self_rank in the specified JSON format."
                        ),
                    },
                ]

                response = client.invoke(
                    messages=messages,
                    model=model_spec.openrouter_id,
                    max_tokens=model_spec.max_tokens,
                    response_format={"type": "json_object"},
                )

                res_json = json.loads(response.text)
                view = res_json.get("view", "")
                self_rank = int(res_json.get("self_rank", 3))

                return FirstOpinion(
                    openrouter_id=model_spec.openrouter_id,
                    vendor=model_spec.vendor,
                    persona=persona,
                    view=view,
                    self_rank=self_rank,
                )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(self.lineup.models)
            ) as executor:
                futures = [executor.submit(run_probe_model, m) for m in self.lineup.models]
                for i, fut in enumerate(futures):
                    m = self.lineup.models[i]
                    try:
                        opinion = fut.result()
                        opinions.append(opinion)
                    except Exception as e:
                        logger.error(
                            "Calibration probe %s failed for model %s: %s",
                            probe_id,
                            m.openrouter_id,
                            e,
                        )

            if len(opinions) < 2:
                logger.warning("Fewer than 2 opinions collected for probe %s. Skipping.", probe_id)
                continue

            # Calculate disagreement rate: 1.0 - max pairwise cosine similarity
            max_agreement = detector.detect_sycophancy(opinions)
            disagreement_rate = 1.0 - max_agreement

            responses_by_model = {op.openrouter_id: op.view for op in opinions}
            responses_by_persona: dict[PersonaName, list[str]] = {}
            for op in opinions:
                responses_by_persona.setdefault(op.persona, []).append(op.view)

            probe_results.append(
                ProbeResult(
                    probe_id=probe_id,
                    question=probe_question,
                    responses_by_model=responses_by_model,
                    responses_by_persona=responses_by_persona,
                    disagreement_rate=disagreement_rate,
                )
            )

        if not probe_results:
            raise CouncilError("No calibration probes successfully completed.")

        overall_disagreement = float(
            sum(pr.disagreement_rate for pr in probe_results) / len(probe_results)
        )
        flagged_sycophancy = overall_disagreement < 0.40

        notes = [
            f"Calibration run at {datetime.utcnow().isoformat()} UTC",
            "Embedding model: sentence-transformers/all-mpnet-base-v2",
            "Disagreement rate acceptance floor: 0.40",
            f"Overall disagreement rate: {overall_disagreement:.4f}",
        ]

        return CalibrationReport(
            probe_results=probe_results,
            overall_disagreement_rate=overall_disagreement,
            flagged_sycophancy=flagged_sycophancy,
            notes=notes,
        )

    @classmethod
    def mock_lineup(cls) -> CouncilLineup:
        """Returns a deterministic 4-vendor mock lineup for offline validation and tests."""
        models = [
            ModelSpec(openrouter_id="openai/gpt-5.5", vendor="openai"),
            ModelSpec(openrouter_id="anthropic/claude-opus-4.7", vendor="anthropic"),
            ModelSpec(openrouter_id="google/gemini-3.1-pro-preview", vendor="google"),
            ModelSpec(openrouter_id="x-ai/grok-4.3", vendor="x-ai"),
        ]
        persona_assignment = {
            "openai/gpt-5.5": PersonaName.PESSIMIST,
            "anthropic/claude-opus-4.7": PersonaName.VISIONARY,
            "google/gemini-3.1-pro-preview": PersonaName.PESSIMIST,
            "x-ai/grok-4.3": PersonaName.PRAGMATIST,
        }
        return CouncilLineup(
            models=models,
            persona_assignment=persona_assignment,
            chairman_policy="round_robin",
        )
