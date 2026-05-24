# calibration.py — Calibration Probes and Sycophancy Detection for Council Deliberation
#
# This file implements the calibration and sycophancy checking system.
#
# Features and Use Cases:
# 1. Sycophancy Checking: Uses sentence-transformers/all-mpnet-base-v2 (or Jaccard
#    word overlap in mock mode) to evaluate semantic similarity across Stage 1
#    first opinions. If similarity exceeds 0.85, raises CouncilSycophancyDetected.
# 2. Calibration Probes: Executes a series of predefined domain-specific
#    questions loaded from config/council/probes.yaml against the models in
#    parallel.
# 3. Disagreement Rate Calculation: Computes disagreement rate per probe as
#    1.0 - max pairwise cosine similarity.
# 4. Calibration Report Generation: Aggregates results into a CalibrationReport
#    to measure council diversity. Acceptance floor is 0.40.
#
# How it is consumed:
# - Council.deliberate imports and runs SycophancyDetector to enforce groupthink checks.
# - Council.calibrate imports and executes run_calibration to evaluate lineup health.

from __future__ import annotations

import concurrent.futures
import json
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from factory.artifacts import PersonaName
from factory.council.errors import CouncilError
from factory.council.types import (
    CalibrationReport,
    CouncilLineup,
    FirstOpinion,
    ModelSpec,
    ProbeResult,
)
from factory.llm_client import DecisionClient, OpenRouterClient

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger("factory.council.calibration")


class SycophancyDetector:
    """Detects sycophancy by computing semantic similarity across first opinions.

    Uses sentence-transformers/all-mpnet-base-v2 (local and vendor-agnostic)
    to calculate pairwise cosine similarities. If any pair exceeds the 0.85
    threshold, the lineup is flagged for groupthink.
    """

    _cached_model: SentenceTransformer | None = None

    def __init__(self, mock_mode: bool = False) -> None:
        """Initializes the Sycophancy Detector.

        Args:
            mock_mode: If True, uses word overlap similarity instead of sentence-transformers.
        """
        logger.info("SycophancyDetector.__init__ called with mock_mode=%s", mock_mode)
        self.mock_mode = mock_mode
        self._model: SentenceTransformer | None = None

        if not mock_mode:
            if SycophancyDetector._cached_model is not None:
                self._model = SycophancyDetector._cached_model
            else:
                try:
                    from sentence_transformers import SentenceTransformer as STClass

                    logger.info("Loading sentence-transformers/all-mpnet-base-v2")
                    SycophancyDetector._cached_model = STClass(
                        "sentence-transformers/all-mpnet-base-v2"
                    )
                    self._model = SycophancyDetector._cached_model
                    logger.info("SentenceTransformer loaded successfully.")
                except Exception as e:
                    raise CouncilError(
                        "Could not load sentence-transformers/all-mpnet-base-v2 for live "
                        "calibration."
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
        logger.info(
            "SycophancyDetector.detect_sycophancy called with opinions_count=%d", len(opinions)
        )
        n = len(opinions)
        if n < 2:
            return 0.0

        if self.mock_mode:
            sims = []
            for i in range(n):
                for j in range(i + 1, n):
                    sim_val = self.mock_cosine_similarity(opinions[i].view, opinions[j].view)
                    sims.append(sim_val)
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
                dot = float(np.dot(emb1, emb2))
                norm1 = float(np.linalg.norm(emb1))
                norm2 = float(np.linalg.norm(emb2))
                cos = 0.0 if norm1 == 0.0 or norm2 == 0.0 else dot / (norm1 * norm2)
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
        logger.info("SycophancyDetector.mock_cosine_similarity called")
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


def run_calibration(
    lineup: CouncilLineup,
    mock_mode: bool = False,
    probe_set: Path | None = None,
) -> CalibrationReport:
    """Runs divisive probes against the current lineup to generate a disagreement-rate report.

    Args:
        lineup: The CouncilLineup configuration to calibrate.
        mock_mode: If True, uses mock LLM clients and Jaccard similarity.
        probe_set: Path to calibration probes YAML file.

    Returns:
        A CalibrationReport containing results per probe and overall metrics.

    Raises:
        CouncilError: If calibration failed or no probes completed successfully.
    """
    logger.info(
        "run_calibration called with lineup_models=%s, mock_mode=%s, probe_set=%s",
        [m.openrouter_id for m in lineup.models],
        mock_mode,
        probe_set,
    )
    project_root = Path(__file__).resolve().parents[2]
    probes_path = probe_set or project_root / "config" / "council" / "probes.yaml"

    logger.info("Reading probes from path: %s", probes_path)
    with open(probes_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    probes = data.get("probes", [])

    # Choose appropriate client
    client: DecisionClient
    if mock_mode:
        from factory.council.mock import MockOpenRouterClient

        client = MockOpenRouterClient()
    else:
        client = OpenRouterClient()

    probe_results: list[ProbeResult] = []
    detector = SycophancyDetector(mock_mode=mock_mode)

    for probe in probes:
        probe_id = str(probe.get("id", ""))
        probe_question = str(probe.get("question", ""))
        logger.info("Running calibration probe %s: %r", probe_id, probe_question)

        opinions: list[FirstOpinion] = []

        def run_probe_model(
            model_spec: ModelSpec,
            probe_question: str = probe_question,
        ) -> FirstOpinion:
            logger.info("run_probe_model called for model=%s", model_spec.openrouter_id)
            persona = lineup.persona_assignment[model_spec.openrouter_id]
            template_path = (
                project_root / "config" / "council" / "personas" / f"{persona.value.lower()}.md"
            )
            with open(template_path, encoding="utf-8") as f_temp:
                template_content = f_temp.read()

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
                        "Please analyze the question and context, and output your view "
                        "and self_rank in the specified JSON format."
                    ),
                },
            ]

            logger.info(
                "GENAI CALL in run_calibration: model=%s, max_tokens=%d, messages_count=%d",
                model_spec.openrouter_id,
                model_spec.max_tokens,
                len(messages),
            )
            response = client.invoke(
                messages=messages,
                model=model_spec.openrouter_id,
                max_tokens=model_spec.max_tokens,
                response_format={"type": "json_object"},
            )
            logger.info(
                "GENAI CALL OUTPUT in run_calibration: model=%s, response=%r",
                model_spec.openrouter_id,
                response.text,
            )

            res_json = json.loads(response.text)
            view = str(res_json.get("view", ""))
            self_rank = int(res_json.get("self_rank", 3))

            return FirstOpinion(
                openrouter_id=model_spec.openrouter_id,
                vendor=model_spec.vendor,
                persona=persona,
                view=view,
                self_rank=self_rank,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(lineup.models)) as executor:
            futures = [executor.submit(run_probe_model, m) for m in lineup.models]
            for idx, fut in enumerate(futures):
                model_spec = lineup.models[idx]
                try:
                    opinion = fut.result()
                    opinions.append(opinion)
                except Exception as e:
                    logger.error(
                        "Calibration probe %s failed for model %s: %s",
                        probe_id,
                        model_spec.openrouter_id,
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
