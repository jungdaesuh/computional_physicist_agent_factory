"""Context token tracking and deterministic auto-compaction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

AUTO_COMPACT_TOKEN_LIMIT = 24_000


@dataclass(frozen=True)
class ContextMessage:
    """One message retained in the generator-verifier context."""

    role: str
    content: str


@dataclass(frozen=True)
class ContextBudget:
    """Estimated context usage against the auto-compaction limit."""

    estimated_tokens: int
    token_limit: int

    @property
    def over_limit(self) -> bool:
        """Return whether compaction should run before the next model call."""
        return self.estimated_tokens > self.token_limit


@dataclass(frozen=True)
class CompactedContext:
    """Compacted context plus deterministic summary text."""

    messages: tuple[ContextMessage, ...]
    summary: str
    budget: ContextBudget


def estimate_context_tokens(messages: Sequence[ContextMessage]) -> int:
    """Estimate tokens from message content using a deterministic char budget."""
    return sum(max(1, (len(message.content) + 3) // 4) for message in messages)


def context_budget(
    messages: Sequence[ContextMessage],
    *,
    token_limit: int = AUTO_COMPACT_TOKEN_LIMIT,
) -> ContextBudget:
    """Return estimated context usage for the provided messages."""
    return ContextBudget(
        estimated_tokens=estimate_context_tokens(messages),
        token_limit=token_limit,
    )


def should_auto_compact(
    messages: Sequence[ContextMessage],
    *,
    token_limit: int = AUTO_COMPACT_TOKEN_LIMIT,
) -> bool:
    """Return whether AUTO_COMPACT_TOKEN_LIMIT has been exceeded."""
    return context_budget(messages, token_limit=token_limit).over_limit


def compact_messages(
    messages: Sequence[ContextMessage],
    *,
    keep_tail: int = 6,
    token_limit: int = AUTO_COMPACT_TOKEN_LIMIT,
) -> CompactedContext:
    """Summarize older messages while preserving the most recent tail verbatim."""
    budget = context_budget(messages, token_limit=token_limit)
    if not budget.over_limit:
        return CompactedContext(tuple(messages), "", budget)

    tail = tuple(messages[-keep_tail:]) if keep_tail > 0 else ()
    head = tuple(messages[: len(messages) - len(tail)])
    summary = "\n".join(f"{message.role}: {message.content}" for message in head)
    compacted = (
        ContextMessage(role="system", content=f"Compacted prior context:\n{summary}"),
        *tail,
    )
    return CompactedContext(compacted, summary, context_budget(compacted, token_limit=token_limit))


__all__ = [
    "AUTO_COMPACT_TOKEN_LIMIT",
    "CompactedContext",
    "ContextBudget",
    "ContextMessage",
    "compact_messages",
    "context_budget",
    "estimate_context_tokens",
    "should_auto_compact",
]
