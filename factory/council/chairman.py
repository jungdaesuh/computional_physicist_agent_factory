# chairman.py — Chairman Selection Policy, Dissent Validation, and Re-prompting
#
# This module implements the core algorithms for managing the chairman model in decision councils.
# It is a key subcomponent of the Spec 001 Council Library (Spec ID: 001-council-chairman).
#
# Main features:
# 1. **Chairman Selection Policies**: Supports random selection, round-robin (replayable),
#    and inverse-cost-based weighted selection (cheaper models preferred to reduce budget).
# 2. **NLI dissent validation**: Uses 'cross-encoder/nli-deberta-v3-base' on CPU/MPS to verify
#    that dissenting views from stage 1 are not synthesized away by the chairman. A stance
#    is a "material dissent" if NLI(premise=majority_view, hypothesis=opinion) classifies
#    it as a contradiction with probability >= 0.60.
# 3. **Representational Checks**: Checks that each material dissent is semantic-entailed by
#    at least one entry in `CouncilVerdict.preserved_dissents`.
# 4. **Auto Re-Prompting**: Re-prompts the chairman model once with the omitted dissent
#    verbatim if dissent omission occurs.
#
# Design principles applied:
# - Deep modules: Simple signatures concealing complex sequence classification/probability.
# - Obvious code: Static typing, clear variable names, and explicit validation thresholds.
# - Log compliance: Logs all function calls at the INFO level for clear audit trails.

from __future__ import annotations

import logging
import random
from collections.abc import Sequence
from typing import Literal

from factory.artifacts import DissentEntry
from factory.council.errors import BudgetTokenUsageMissing, CouncilError
from factory.council.types import CouncilLineup, FirstOpinion, ModelSpec

logger = logging.getLogger("factory.council.chairman")


class PricingTable:
    """Helper to lookup input/output token pricing for OpenRouter models.

    This implements the pricing table model configured in config/pricing/openrouter.yaml.
    """

    def __init__(self, data: dict[str, dict[str, float]]) -> None:
        """Initializes the pricing table with data mapping model names to pricing metrics.

        Args:
            data: A dictionary of model ID to pricing dictionaries.
        """
        logger.info("PricingTable.__init__ called with data keys: %s", list(data.keys()))
        self.data = data

    def lookup(self, openrouter_id: str, kind: Literal["input", "output"]) -> float:
        """Looks up the price per 1 million tokens for the given model ID and type.

        Args:
            openrouter_id: The OpenRouter ID of the model.
            kind: The kind of price lookup ("input" or "output").

        Returns:
            The price per 1 million tokens in USD.

        Raises:
            BudgetTokenUsageMissing: If the model ID or pricing kind is missing.
        """
        logger.info("PricingTable.lookup called: model=%s, kind=%s", openrouter_id, kind)
        if openrouter_id not in self.data:
            raise BudgetTokenUsageMissing(
                module="council",
                model_id=openrouter_id,
                description="pricing entry missing",
            )
        key = f"{kind}_per_1m_tokens_usd"
        if key not in self.data[openrouter_id]:
            raise BudgetTokenUsageMissing(
                module="council",
                model_id=openrouter_id,
                description=f"pricing kind missing: {key}",
            )
        return self.data[openrouter_id][key]


def load_pricing_table_wrapper() -> PricingTable:
    """Loads the pricing table from config or default fallback.

    Returns:
        A PricingTable instance wrapping the current OpenRouter pricing.
    """
    logger.info("load_pricing_table_wrapper called")
    from factory.llm_client.api import load_pricing_table

    return PricingTable(load_pricing_table())


def select_chairman(
    lineup: CouncilLineup,
    session_counter: int,
    pricing_table: PricingTable | None = None,
) -> ModelSpec:
    """Selects the chairman model from the lineup based on the selection policy.

    Args:
        lineup: The CouncilLineup containing models and the policy.
        session_counter: Counter for the current session, used in round_robin.
        pricing_table: Optional PricingTable, required for weighted_by_cost.

    Returns:
        The selected ModelSpec for the chairman.

    Raises:
        CouncilError: If the selection policy is unknown.
    """
    logger.info(
        "select_chairman called: policy=%s, session_counter=%d, pricing_table_provided=%s",
        lineup.chairman_policy,
        session_counter,
        pricing_table is not None,
    )
    policy = lineup.chairman_policy
    if policy == "random":
        selected = random.choice(lineup.models)
        logger.info("select_chairman (random) selected model: %s", selected.openrouter_id)
        return selected

    elif policy == "round_robin":
        index = session_counter % len(lineup.models)
        selected = lineup.models[index]
        logger.info(
            "select_chairman (round_robin) selected model: %s (index %d from session_counter %d)",
            selected.openrouter_id,
            index,
            session_counter,
        )
        return selected

    elif policy == "weighted_by_cost":
        if pricing_table is None:
            logger.info("pricing_table is None for weighted_by_cost policy; loading default table")
            pricing_table = load_pricing_table_wrapper()

        weights = []
        for m in lineup.models:
            cost = pricing_table.lookup(m.openrouter_id, "output")
            # Inversely weighted by output cost (assign high weight 1e9 to free models)
            w = 1e9 if cost <= 0 else 1.0 / cost
            weights.append(w)

        selected = random.choices(lineup.models, weights=weights, k=1)[0]
        logger.info(
            "select_chairman (weighted_by_cost) selected model: %s with weights %s",
            selected.openrouter_id,
            weights,
        )
        return selected

    else:
        raise CouncilError(f"Unknown chairman selection policy: {policy}")


class NLIDissentValidator:
    """Validates chairman decisions to ensure dissent omission did not occur.

    Uses cross-encoder/nli-deberta-v3-base to verify that any material dissent (contradiction
    against majority view) is semantically represented in the preserved dissents list (entailed).
    """

    def __init__(self, mock_mode: bool = False, local_files_only: bool = False) -> None:
        """Initializes the NLI Dissent Validator.

        Args:
            mock_mode: If True, operates in mock rule-based mode without loading torch/transformers.
            local_files_only: If True, only loads model files cached locally.
        """
        logger.info(
            "NLIDissentValidator.__init__ called: mock_mode=%s, local_files_only=%s",
            mock_mode,
            local_files_only,
        )
        self.mock_mode = mock_mode
        self._tokenizer = None
        self._model = None
        self.device = "cpu"

        if not mock_mode:
            try:
                import torch
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                # Support MPS on Mac platforms, default to CPU
                self.device = "mps" if torch.backends.mps.is_available() else "cpu"
                logger.info(
                    "Loading NLI model cross-encoder/nli-deberta-v3-base on device: %s", self.device
                )

                self._tokenizer = AutoTokenizer.from_pretrained(
                    "cross-encoder/nli-deberta-v3-base",
                    local_files_only=local_files_only,
                )
                self._model = AutoModelForSequenceClassification.from_pretrained(
                    "cross-encoder/nli-deberta-v3-base",
                    local_files_only=local_files_only,
                ).to(self.device)
                logger.info("NLI model loaded successfully.")
            except Exception as e:
                raise CouncilError(
                    "Could not load real HuggingFace NLI model for live dissent validation."
                ) from e

    def predict_nli(self, premise: str, hypothesis: str) -> dict[str, float]:
        """Runs the NLI model to get entailment, contradiction, and neutral probabilities.

        Args:
            premise: The premise string.
            hypothesis: The hypothesis string.

        Returns:
            A dictionary mapping label names ('contradiction', 'entailment',
            'neutral') to probabilities.
        """
        logger.info("predict_nli called: premise=%r, hypothesis=%r", premise, hypothesis)
        if self.mock_mode:
            p_lower = premise.lower()
            h_lower = hypothesis.lower()

            contradict_words = [
                "reject",
                "dissent",
                "object",
                "disagree",
                "oppose",
                "failure",
                "sloshing",
                "not worthy",
            ]
            is_contradict = any(w in h_lower for w in contradict_words) and not any(
                w in p_lower for w in contradict_words
            )

            is_entail = (h_lower in p_lower) or (p_lower in h_lower)
            if not is_entail:
                p_words = set(p_lower.split())
                h_words = set(h_lower.split())
                overlap = p_words.intersection(h_words)
                if len(overlap) >= 3:
                    is_entail = True

            if is_contradict:
                probs = {"contradiction": 0.85, "entailment": 0.05, "neutral": 0.10}
            elif is_entail:
                probs = {"contradiction": 0.05, "entailment": 0.85, "neutral": 0.10}
            else:
                probs = {"contradiction": 0.10, "entailment": 0.10, "neutral": 0.80}

            logger.info("mock predict_nli output: %s", probs)
            return probs

        if self._model is None or self._tokenizer is None:
            raise CouncilError("NLI dissent validator model is not initialized.")

        import torch

        # Run real NLI inference
        inputs = self._tokenizer(premise, hypothesis, return_tensors="pt", truncation=True)
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model(**inputs)

        logits = outputs.logits
        probs_list = torch.softmax(logits, dim=-1).squeeze(0).tolist()

        # label mapping for cross-encoder/nli-deberta-v3-base:
        # Class 0: contradiction, Class 1: entailment, Class 2: neutral
        result = {
            "contradiction": float(probs_list[0]),
            "entailment": float(probs_list[1]),
            "neutral": float(probs_list[2]),
        }
        logger.info("predict_nli output: %s", result)
        return result

    def check_dissent_omission(
        self,
        majority_view: str,
        first_opinions: Sequence[FirstOpinion],
        preserved_dissents: Sequence[DissentEntry],
        threshold: float = 0.60,
    ) -> list[FirstOpinion]:
        """Identifies any first-opinions that contradict the majority view but are not preserved.

        Args:
            majority_view: The majority view summary text.
            first_opinions: The stage 1 opinions of council members.
            preserved_dissents: The list of dissents preserved by the chairman.
            threshold: Contradiction probability threshold to qualify as material dissent.

        Returns:
            A list of FirstOpinion instances that are omitted.
        """
        logger.info(
            "check_dissent_omission called: majority_view_len=%d, opinions_count=%d, "
            "preserved_dissents_count=%d, threshold=%f",
            len(majority_view),
            len(first_opinions),
            len(preserved_dissents),
            threshold,
        )
        omitted: list[FirstOpinion] = []

        for opinion in first_opinions:
            # 1. Stance contradiction check: premise=majority_view, hypothesis=opinion.view
            nli_res = self.predict_nli(premise=majority_view, hypothesis=opinion.view)

            max_label = max(nli_res, key=nli_res.get)  # type: ignore[arg-type]
            is_contradict = (max_label == "contradiction") and (
                nli_res["contradiction"] >= threshold
            )

            if is_contradict:
                logger.info(
                    "Opinion by %s (%s) classified as material dissent with P(contradiction)=%f",
                    opinion.openrouter_id,
                    opinion.persona,
                    nli_res["contradiction"],
                )

                # 2. Check representation in preserved dissents
                represented = False
                for pd in preserved_dissents:
                    # premise = preserved_dissent.view, hypothesis = opinion.view
                    match_res = self.predict_nli(premise=pd.view, hypothesis=opinion.view)
                    match_label = max(match_res, key=match_res.get)  # type: ignore[arg-type]
                    if match_label == "entailment":
                        represented = True
                        logger.info(
                            "Material dissent by %s (%s) is represented "
                            "by preserved dissent from %s",
                            opinion.openrouter_id,
                            opinion.persona,
                            pd.model_id,
                        )
                        break

                if not represented:
                    logger.warning(
                        "Omitted dissent detected! Opinion by %s (%s) is "
                        "not represented in preserved dissents.",
                        opinion.openrouter_id,
                        opinion.persona,
                    )
                    omitted.append(opinion)

        return omitted


def reprompt_chairman(
    original_messages: list[dict[str, str]],
    first_response_text: str,
    omitted_opinions: Sequence[FirstOpinion],
) -> list[dict[str, str]]:
    """Constructs a re-prompt message list for the chairman when dissent omission occurs.

    Appends the assistant response and a strict instruction detailing omitted dissents verbatim.

    Args:
        original_messages: The messages payload from the first chairman call.
        first_response_text: The string response text from the first chairman call.
        omitted_opinions: The list of FirstOpinions that were omitted.

    Returns:
        A list of messages for the second API call to correct the omission.
    """
    logger.info("reprompt_chairman called: omitted_opinions_count=%d", len(omitted_opinions))

    # Extract verbatim texts of the omitted opinions
    verbatim_dissents = [o.view for o in omitted_opinions]

    # Construct strict warning prompt forcing the models to include the dissent verbatim
    instruction = (
        "CRITICAL ERROR: You omitted the following dissenting opinion(s) from the final "
        "verdict. You MUST preserve and list these dissents verbatim in your JSON output "
        "under 'preserved_dissents':\n"
        + "\n".join(f"- {txt}" for txt in verbatim_dissents)
        + "\n\nPlease correct this. Revise majority_view if needed to acknowledge these points, "
        "and ensure all material dissents are fully represented in 'preserved_dissents'. "
        "Provide your entire updated response as a JSON object."
    )

    reprompted_messages = list(original_messages)
    reprompted_messages.append({"role": "assistant", "content": first_response_text})
    reprompted_messages.append({"role": "user", "content": instruction})
    return reprompted_messages
