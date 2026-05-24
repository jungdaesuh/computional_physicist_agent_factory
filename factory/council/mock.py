# mock.py — Mock implementation of the council API
#
# Implements mock functionality for local debugging and tests.
# Returns fixture data without performing real operations.

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from factory.llm_client import OpenRouterMessage, OpenRouterResponse, OpenRouterResponseFormat

logger = logging.getLogger("factory.council.mock")


class MockOpenRouterClient:
    """Mock OpenRouterClient for tests and offline usage.

    Does not depend on network or the live openai package.
    """

    def __init__(self) -> None:
        self.should_omit_dissent_first_time = False
        self.dissent_omission_call_count = 0
        self.stage1_call_count = 0
        self.stage2_call_count = 0
        self.stage3_call_count = 0

    def invoke(
        self,
        messages: Sequence[OpenRouterMessage],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: OpenRouterResponseFormat | None = None,
    ) -> OpenRouterResponse:
        logger.info(
            "MockOpenRouterClient.invoke called: model=%s, max_tokens=%d, response_format=%s",
            model,
            max_tokens,
            response_format,
        )

        # Check system/user messages to determine the stage
        prompt_text = ""
        for msg in messages:
            prompt_text += msg["content"] + "\n"

        # Determine Stage based on prompt content
        if "Voice A" in prompt_text or "Rank them" in prompt_text or "reviewer" in prompt_text:
            # Stage 2
            self.stage2_call_count += 1
            result_dict = {
                "rankings": {"A": 1, "B": 2, "C": 3, "D": 4},
                "critiques": {
                    "A": "Very structured critique.",
                    "B": "A bit too optimistic.",
                    "C": "Sufficiently cautious.",
                    "D": "Actionable feedback.",
                },
            }
            text = json.dumps(result_dict)
        elif (
            "majority view" in prompt_text
            or "preserved dissents" in prompt_text
            or "chairman" in prompt_text
        ):
            # Stage 3
            self.stage3_call_count += 1

            # If we want to simulate dissent omission for testing
            if self.should_omit_dissent_first_time and self.dissent_omission_call_count == 0:
                self.dissent_omission_call_count += 1
                result_dict = {
                    "majority_view": (
                        "The council is divided. While the visionary and pragmatist "
                        "personas support the proposal for its potential 10x speedup "
                        "and novel neural surrogate search, the pessimist models raise "
                        "critical objections regarding numerical instability and the "
                        "lack of appropriate ALM penalty constraints."
                    ),
                    "preserved_dissents": [],  # OMITTED!
                    "chairman_decision": "qualified",
                }
            else:
                result_dict = {
                    "majority_view": (
                        "The council is divided. While the visionary and pragmatist "
                        "personas support the proposal for its potential 10x speedup "
                        "and novel neural surrogate search, the pessimist models raise "
                        "critical objections regarding numerical instability and the "
                        "lack of appropriate ALM penalty constraints."
                    ),
                    "preserved_dissents": [
                        {
                            "model_id": "openai/gpt-5.5",
                            "persona": "pessimist",
                            "view": (
                                "Reject the proposal because the physics model lacks "
                                "appropriate ALM penalty constraints."
                            ),
                            "rationale": (
                                "Without proper penalty terms in ALM, optimization "
                                "will fail to find feasible stellarator designs."
                            ),
                        },
                        {
                            "model_id": "google/gemini-3.1-pro-preview",
                            "persona": "pessimist",
                            "view": (
                                "Reject. The proposed objective functions have high risk "
                                "of numerical instability."
                            ),
                            "rationale": "Numerical instability makes the results unreplicable.",
                        },
                    ],
                    "chairman_decision": "qualified",
                }
            text = json.dumps(result_dict)
        else:
            # Stage 1 or Calibration Probe
            self.stage1_call_count += 1
            if model == "openai/gpt-5.5":
                result_dict = {
                    "view": (
                        "Reject the proposal because the physics model lacks "
                        "appropriate ALM penalty constraints."
                    ),
                    "self_rank": 4,
                }
            elif model == "google/gemini-3.1-pro-preview":
                result_dict = {
                    "view": (
                        "Reject. The proposed objective functions have high risk "
                        "of numerical instability."
                    ),
                    "self_rank": 3,
                }
            elif model == "anthropic/claude-opus-4.7":
                result_dict = {
                    "view": (
                        "Approve the proposal. It introduces a novel neural surrogate "
                        "search that could accelerate algorithm discovery by 10x."
                    ),
                    "self_rank": 5,
                }
            elif model == "x-ai/grok-4.3":
                result_dict = {
                    "view": (
                        "Approve with qualifications. We must add validation checks "
                        "for optimization constraints before full scale-up."
                    ),
                    "self_rank": 4,
                }
            else:
                # Calibration probe or unknown model
                result_dict = {
                    "view": f"Mock opinion for model {model} under probe.",
                    "self_rank": 3,
                }
            text = json.dumps(result_dict)

        # Standard token counts and costs
        input_tokens = 150
        output_tokens = 100
        cost = 0.001

        return OpenRouterResponse(
            text=text,
            model_id_actual=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
