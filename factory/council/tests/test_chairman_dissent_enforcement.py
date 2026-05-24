# test_chairman_dissent_enforcement.py — Unit tests for chairman dissent validation
#
# Verifies that NLIDissentValidator identifies omitted dissent and reprompt_chairman constructs
# the correct re-prompt.

import logging

import pytest

from factory.artifacts import DissentEntry, PersonaName
from factory.council.chairman import NLIDissentValidator, reprompt_chairman
from factory.council.errors import CouncilError
from factory.council.types import FirstOpinion

logger = logging.getLogger("factory.council.tests.test_chairman_dissent_enforcement")


def test_nli_dissent_validator_mock() -> None:
    """Tests the NLIDissentValidator in mock mode to verify logic flow."""
    logger.info("Running test_nli_dissent_validator_mock")
    validator = NLIDissentValidator(mock_mode=True)

    majority_view = "The council approves the optimization algorithm for its 10x potential speedup."

    # Contains "Reject proposal because physics model lacks appropriate ALM penalty constraints"
    # The mock model maps "Reject" and "not worthy" to contradiction.
    dissent_opinion = FirstOpinion(
        openrouter_id="openai/gpt-5.5",
        vendor="openai",
        persona=PersonaName.PESSIMIST,
        view=(
            "Reject the proposal because the physics model "
            "lacks appropriate ALM penalty constraints."
        ),
        self_rank=4,
    )

    agreeing_opinion = FirstOpinion(
        openrouter_id="anthropic/claude-opus-4.7",
        vendor="anthropic",
        persona=PersonaName.VISIONARY,
        view=(
            "Approve the proposal. It introduces a novel neural surrogate search "
            "that could accelerate algorithm discovery."
        ),
        self_rank=5,
    )

    opinions = [agreeing_opinion, dissent_opinion]

    # Case 1: Dissent is omitted (preserved_dissents is empty)
    omitted = validator.check_dissent_omission(
        majority_view=majority_view,
        first_opinions=opinions,
        preserved_dissents=[],
        threshold=0.60,
    )
    assert len(omitted) == 1
    assert omitted[0].openrouter_id == "openai/gpt-5.5"

    # Case 2: Dissent is preserved
    preserved = [
        DissentEntry(
            model_id="openai/gpt-5.5",
            persona=PersonaName.PESSIMIST,
            view=(
                "Reject the proposal because the physics model "
                "lacks appropriate ALM penalty constraints."
            ),
            rationale="Without proper penalty terms in ALM, optimization fails.",
        )
    ]
    omitted_2 = validator.check_dissent_omission(
        majority_view=majority_view,
        first_opinions=opinions,
        preserved_dissents=preserved,
        threshold=0.60,
    )
    assert len(omitted_2) == 0


def test_reprompt_chairman_construction() -> None:
    """Verifies that reprompt_chairman builds the correct sequence of messages."""
    logger.info("Running test_reprompt_chairman_construction")
    original_messages = [
        {"role": "system", "content": "You are the chairman of the council."},
        {"role": "user", "content": "What is the verdict?"},
    ]
    first_response = '{"majority_view": "We agree.", "preserved_dissents": []}'

    omitted_opinions = [
        FirstOpinion(
            openrouter_id="openai/gpt-5.5",
            vendor="openai",
            persona=PersonaName.PESSIMIST,
            view="Reject because of sloshing risk.",
            self_rank=4,
        )
    ]

    reprompted = reprompt_chairman(
        original_messages=original_messages,
        first_response_text=first_response,
        omitted_opinions=omitted_opinions,
    )

    # There should be 4 messages in total: 2 original + 1 assistant + 1 user correction
    assert len(reprompted) == 4
    assert reprompted[0] == original_messages[0]
    assert reprompted[1] == original_messages[1]
    assert reprompted[2] == {"role": "assistant", "content": first_response}
    assert reprompted[3]["role"] == "user"
    assert (
        "CRITICAL ERROR: You omitted the following dissenting opinion(s)"
        in reprompted[3]["content"]
    )
    assert "Reject because of sloshing risk." in reprompted[3]["content"]


def test_nli_dissent_validator_real_load_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live dissent validation cannot silently downgrade to mock mode."""
    logger.info("Running test_nli_dissent_validator_real_load_failure_raises")
    transformers = pytest.importorskip("transformers")

    def _raise_missing_model(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("missing local model")

    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", _raise_missing_model)

    with pytest.raises(CouncilError, match="Could not load real HuggingFace NLI model"):
        NLIDissentValidator(mock_mode=False, local_files_only=True)
