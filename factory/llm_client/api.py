# api.py — OpenRouter LLM Client and DecisionClient Protocol
#
# This module defines the shared LLM client substrate for the entire factory.
# All text completions and structured LLM reasoning route through here.
#
# Use cases:
# 1. Calling heterogeneous frontier models in decision councils.
# 2. Driving cheap agentic code-gen/Gap Miner tasks with google/gemini-3.5-flash.
# 3. Running tests using FileClient transcript replay without network dependency.
# 4. Rate-limiting and retrying completions automatically.

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict

from openai import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    RateLimitError,
)
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
from openai.types.chat.completion_create_params import ResponseFormat

from factory.artifacts import FactoryError
from factory.budget import BudgetTokenUsageMissing
from factory.llm_client.limiter import TokenBucket, get_process_token_bucket
from factory.llm_client.pricing import (
    ModelPricing,
    calculate_model_cost,
    load_pricing_document,
    require_model_pricing,
)
from factory.llm_client.pricing import (
    load_pricing_table as _load_pricing_table,
)

logger = logging.getLogger("factory.llm_client.api")
DEFAULT_HTTP_REFERER = "https://github.com/jungdaesuh/computional_physicist_agent_factory"
DEFAULT_OPENROUTER_TITLE = "ai-co-computational-physicist"

# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------


class LLMClientError(FactoryError):
    """Base exception for LLM client failures."""

    pass


class TransientAPIError(LLMClientError):
    """Base for API errors that are temporary and should be retried."""

    pass


class OpenRouterAuthError(LLMClientError):
    """Raised when authentication fails (credentials invalid). Do not retry."""

    pass


class OpenRouterRateLimitError(TransientAPIError):
    """Raised when rate limits are exceeded."""

    pass


class OpenRouterConnectError(TransientAPIError):
    """Raised when network connection fails."""

    pass


class OpenRouterModelUnavailable(LLMClientError):
    """Raised when OpenRouter reports that a requested model is unavailable."""

    pass


class OpenRouterError(LLMClientError):
    """Raised for non-retryable OpenRouter request failures."""

    pass


# --------------------------------------------------------------------------
# Protocol and Response Dataclass
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenRouterResponse:
    """Standardized response containing text, usage metadata, and calculated cost."""

    text: str
    model_id_actual: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


OpenRouterMessage = Mapping[str, str]
OpenRouterResponseFormat = ResponseFormat


class TranscriptEntry(TypedDict):
    text: str
    model_id_actual: str
    input_tokens: int
    output_tokens: int


class DecisionClient(Protocol):
    """Protocol for LLM interactions in the factory.

    Synchronous completion client.
    """

    def invoke(
        self,
        messages: Sequence[OpenRouterMessage],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: OpenRouterResponseFormat | None = None,
    ) -> OpenRouterResponse:
        """Invoke a completions request.

        Args:
            messages: List of message dicts (role, content).
            model: Model name.
            max_tokens: Completion length cap.
            response_format: Optional response format (e.g. JSON mode).
        """
        ...


# --------------------------------------------------------------------------
# Pricing Loader Helper
# --------------------------------------------------------------------------


def _to_chat_messages(messages: Sequence[OpenRouterMessage]) -> list[ChatCompletionMessageParam]:
    """Convert the factory message shape into the OpenAI SDK's typed message union."""
    converted: list[ChatCompletionMessageParam] = []
    for message in messages:
        role = message["role"]
        content = message["content"]
        if role == "system":
            system_message: ChatCompletionSystemMessageParam = {
                "role": "system",
                "content": content,
            }
            converted.append(system_message)
        elif role == "assistant":
            assistant_message: ChatCompletionAssistantMessageParam = {
                "role": "assistant",
                "content": content,
            }
            converted.append(assistant_message)
        elif role == "user":
            user_message: ChatCompletionUserMessageParam = {
                "role": "user",
                "content": content,
            }
            converted.append(user_message)
        else:
            raise ValueError(f"Unsupported OpenRouter message role: {role}")
    return converted


def load_pricing_table() -> dict[str, dict[str, float]]:
    """Load the strict OpenRouter pricing table without default fallbacks."""
    logger.info("load_pricing_table() called")
    return _load_pricing_table()


# --------------------------------------------------------------------------
# Concrete clients
# --------------------------------------------------------------------------


class OpenRouterClient:
    """Concrete DecisionClient backed by the openai SDK and OpenRouter base URL."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_referer: str = DEFAULT_HTTP_REFERER,
        app_title: str = DEFAULT_OPENROUTER_TITLE,
    ) -> None:
        """Initializes the OpenRouter client.

        Args:
            api_key: The OpenRouter API key. If not provided, reads from OPENROUTER_API_KEY env.
            http_referer: Site URL used for OpenRouter ranking attribution.
            app_title: Site title used for OpenRouter ranking attribution.
        """
        logger.info("OpenRouterClient.__init__")
        resolved_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not resolved_key:
            # We don't raise immediately to allow mock mode setup, but will raise during invoke
            logger.warning("OPENROUTER_API_KEY is not set.")

        self._api_key = resolved_key
        self._headers = {
            "HTTP-Referer": http_referer,
            "X-OpenRouter-Title": app_title,
        }
        # We instantiate the client lazily on first invoke or directly if key is present
        self._client: OpenAI | None = None
        self._pricing: dict[str, ModelPricing] = load_pricing_document().models

    def _get_client(self) -> OpenAI:
        """Retrieves or instantiates the inner OpenAI client."""
        if not self._api_key:
            raise OpenRouterAuthError(
                "OPENROUTER_API_KEY is missing. Set the environment variable."
            )
        if self._client is None:
            self._client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self._api_key,
            )
        return self._client

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculates cost of a completion run.

        Args:
            model: Model requested.
            input_tokens: Prompts token count.
            output_tokens: Completions token count.
        """
        logger.info(
            "calculate_cost(model=%s, input_tokens=%d, output_tokens=%d)",
            model,
            input_tokens,
            output_tokens,
        )
        return calculate_model_cost(model, input_tokens, output_tokens, self._pricing)

    def invoke(
        self,
        messages: Sequence[OpenRouterMessage],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: OpenRouterResponseFormat | None = None,
    ) -> OpenRouterResponse:
        """Performs a synchronous completions call with exponential backoff retries.

        Args:
            messages: Message history payload.
            model: requested model ID.
            max_tokens: output limit.
            response_format: optional structure spec.
        """
        logger.info(
            "invoke(model=%s, max_tokens=%d, response_format=%s)",
            model,
            max_tokens,
            response_format,
        )
        # Log genai call inputs (stripping inline data message logs)
        logger.info("GENAI CALL INPUT: model=%s, messages_count=%d", model, len(messages))

        client = self._get_client()

        retries = 5
        base_delay = 1.0

        for attempt in range(retries):
            try:
                chat_messages = _to_chat_messages(messages)
                if response_format is None:
                    response = client.chat.completions.create(
                        extra_headers=self._headers,
                        model=model,
                        messages=chat_messages,
                        max_completion_tokens=max_tokens,
                    )
                else:
                    response = client.chat.completions.create(
                        extra_headers=self._headers,
                        model=model,
                        messages=chat_messages,
                        max_completion_tokens=max_tokens,
                        response_format=response_format,
                    )

                if (
                    response.usage is None
                    or response.usage.prompt_tokens is None
                    or response.usage.completion_tokens is None
                ):
                    raise BudgetTokenUsageMissing(
                        module="llm_client",
                        model_id=model,
                        description="usage block absent",
                    )

                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
                cost = self.calculate_cost(model, input_tokens, output_tokens)

                logger.info(
                    "GENAI CALL OUTPUT: model=%s, input_tokens=%d, output_tokens=%d, cost=%f",
                    model,
                    input_tokens,
                    output_tokens,
                    cost,
                )

                content = response.choices[0].message.content or ""
                return OpenRouterResponse(
                    text=content,
                    model_id_actual=response.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                )

            except AuthenticationError as e:
                logger.error("Auth error on OpenRouter call (refusing retry): %s", e)
                raise OpenRouterAuthError(f"Authentication failed: {e}") from e
            except RateLimitError as e:
                logger.warning("Rate limit error (attempt %d/%d): %s", attempt + 1, retries, e)
                if attempt == retries - 1:
                    raise OpenRouterRateLimitError(f"Rate limit exceeded: {e}") from e
            except NotFoundError as e:
                raise OpenRouterModelUnavailable(f"Model unavailable: {model}") from e
            except BadRequestError as e:
                message = str(e)
                if "model" in message.lower():
                    raise OpenRouterModelUnavailable(f"Model unavailable: {model}") from e
                raise OpenRouterError(f"Bad OpenRouter request: {e}") from e
            except APIConnectionError as e:
                logger.warning("Connection error (attempt %d/%d): %s", attempt + 1, retries, e)
                if attempt == retries - 1:
                    raise OpenRouterConnectError(f"Connection failed: {e}") from e
            except APIError as e:
                logger.warning("API error (attempt %d/%d): %s", attempt + 1, retries, e)
                if attempt == retries - 1:
                    raise TransientAPIError(f"Transient API error: {e}") from e
            except BudgetTokenUsageMissing:
                raise
            delay = base_delay * (2**attempt)
            logger.info("Retrying in %f seconds...", delay)
            time.sleep(delay)

        raise TransientAPIError("Retries exhausted without a successful response")


class RateLimitedDecisionClient:
    """Wraps a DecisionClient with the process-wide token-bucket limiter."""

    def __init__(
        self,
        inner: DecisionClient,
        rps: float = 5.0,
        *,
        capacity: float | None = None,
        token_bucket: TokenBucket | None = None,
    ) -> None:
        """Initializes the rate limited client wrapper.

        Args:
            inner: The DecisionClient to wrap.
            rps: Allowed requests per second.
            capacity: Optional shared bucket capacity.
            token_bucket: Explicit bucket for tests or custom process coordination.
        """
        logger.info("RateLimitedDecisionClient.__init__(rps=%f)", rps)
        self._inner = inner
        self._token_bucket = token_bucket or get_process_token_bucket(rps=rps, capacity=capacity)

    def invoke(
        self,
        messages: Sequence[OpenRouterMessage],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: OpenRouterResponseFormat | None = None,
    ) -> OpenRouterResponse:
        """Invokes inner client under rate limits."""
        logger.info("RateLimitedDecisionClient.invoke")
        self._token_bucket.acquire()
        return self._inner.invoke(
            messages, model=model, max_tokens=max_tokens, response_format=response_format
        )


class FileClient:
    """Mock client that replays text and metadata from a transcript file for tests."""

    def __init__(self, transcript_path: Path) -> None:
        """Initializes the FileClient.

        Args:
            transcript_path: Path to the transcript file.
        """
        logger.info("FileClient.__init__(path=%s)", transcript_path)
        self._path = transcript_path
        self._transcript: list[TranscriptEntry] = []
        self._index = 0
        self._pricing: dict[str, ModelPricing] = load_pricing_document().models
        self.load_transcript()

    def load_transcript(self) -> None:
        """Loads transcript logs from the file."""
        if not self._path.exists():
            raise LLMClientError(f"Transcript file is missing: {self._path}")
        loaded = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list):
            raise LLMClientError(f"Transcript must be a JSON list: {self._path}")
        self._transcript = [_parse_transcript_entry(self._path, item) for item in loaded]

    def invoke(
        self,
        messages: Sequence[OpenRouterMessage],
        *,
        model: str,
        max_tokens: int = 4096,
        response_format: OpenRouterResponseFormat | None = None,
    ) -> OpenRouterResponse:
        """Invokes a replayed mock completion."""
        del messages, max_tokens, response_format
        logger.info("FileClient.invoke")
        if self._index >= len(self._transcript):
            raise LLMClientError(f"Transcript exhausted: {self._path}")

        mock_data = self._transcript[self._index]
        self._index += 1

        text = mock_data["text"]
        input_tokens = mock_data["input_tokens"]
        output_tokens = mock_data["output_tokens"]

        model_pricing = require_model_pricing(model, self._pricing)
        cost = (
            input_tokens * model_pricing.input_per_1m_tokens_usd / 1_000_000.0
            + output_tokens * model_pricing.output_per_1m_tokens_usd / 1_000_000.0
        )

        return OpenRouterResponse(
            text=text,
            model_id_actual=mock_data["model_id_actual"],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )


def _parse_transcript_entry(path: Path, item: object) -> TranscriptEntry:
    if not isinstance(item, dict):
        raise LLMClientError(f"Transcript entry must be an object: {path}")

    text = item.get("text")
    model_id_actual = item.get("model_id_actual")
    input_tokens = item.get("input_tokens")
    output_tokens = item.get("output_tokens")
    if (
        not isinstance(text, str)
        or not isinstance(model_id_actual, str)
        or not isinstance(input_tokens, int)
        or not isinstance(output_tokens, int)
        or isinstance(input_tokens, bool)
        or isinstance(output_tokens, bool)
    ):
        raise LLMClientError(f"Transcript entry has invalid fields: {path}")
    return {
        "text": text,
        "model_id_actual": model_id_actual,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
