"""Exception re-exports for the LLM client module."""

from factory.llm_client.api import (
    LLMClientError,
    OpenRouterAuthError,
    OpenRouterConnectError,
    OpenRouterError,
    OpenRouterModelUnavailable,
    OpenRouterRateLimitError,
    TransientAPIError,
)

__all__ = [
    "LLMClientError",
    "OpenRouterAuthError",
    "OpenRouterConnectError",
    "OpenRouterError",
    "OpenRouterModelUnavailable",
    "OpenRouterRateLimitError",
    "TransientAPIError",
]
