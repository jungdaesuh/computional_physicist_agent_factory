# limiter.py — Process-wide thread-safe Token-Bucket Rate Limiter matching OpenRouter Tiers
#
# This module implements a process-wide, thread-safe token-bucket rate limiter
# to throttle calls made to OpenRouter, matching various tier limitations (e.g. Free, Paid).
#
# Use cases:
# 1. Throttling requests to 20 RPM (Requests Per Minute) for Free Tier or free models.
# 2. Throttling requests to high throughput limits (e.g. 5-10 RPS) for Paid Tier.
# 3. Thread-safe process-wide synchronization for concurrent agent invocations.

from __future__ import annotations

import logging
import threading
import time
from typing import NamedTuple

logger = logging.getLogger("factory.llm_client.limiter")


class OpenRouterTier(NamedTuple):
    """Configuration for an OpenRouter tier.

    Attributes:
        name: Name of the tier (e.g., 'Free', 'Paid').
        rps: Allowed requests per second.
        capacity: Maximum token capacity (allows bursts).
    """

    name: str
    rps: float
    capacity: float


# Predefined standard OpenRouter tiers
# Free tier: 20 requests per minute (20/60 = 0.333... RPS), capacity up to 20 to allow bursts.
FREE_TIER = OpenRouterTier(
    name="Free",
    rps=20.0 / 60.0,
    capacity=20.0,
)

# Paid tier: Standard 5.0 RPS process limit to prevent server overload.
PAID_TIER = OpenRouterTier(
    name="Paid",
    rps=5.0,
    capacity=5.0,
)


class TokenBucket:
    """Thread-safe Token Bucket rate limiter for process-wide request throttling.

    This class enforces rate limits by replenishing tokens at a constant rate
    up to a maximum capacity. Calls block when there are insufficient tokens
    available in the bucket.
    """

    def __init__(self, rps: float, capacity: float | None = None) -> None:
        """Initializes the Token Bucket rate limiter.

        Args:
            rps: Replenish rate in tokens per second (requests per second). Must be > 0.
            capacity: Maximum token capacity. Defaults to max(rps, 1.0) if not specified.

        Raises:
            ValueError: If rps is not strictly positive.
        """
        if rps <= 0:
            raise ValueError("rps must be strictly positive")

        self._rps = rps
        self._capacity = capacity if capacity is not None else max(rps, 1.0)
        if self._capacity <= 0:
            raise ValueError("capacity must be strictly positive")
        self._tokens = self._capacity
        self._last_refill_at = time.monotonic()
        self._lock = threading.Lock()

    @property
    def rps(self) -> float:
        """The replenish rate of the token bucket in tokens per second."""
        return self._rps

    @property
    def capacity(self) -> float:
        """The maximum capacity of the token bucket."""
        return self._capacity

    @property
    def tokens(self) -> float:
        """The current number of tokens available in the bucket, after a dynamic refill."""
        with self._lock:
            self._refill()
            return self._tokens

    def _refill(self) -> None:
        """Refills the bucket with tokens based on the elapsed time since the last refill.

        Must be called while holding the lock.
        """
        now = time.monotonic()
        elapsed = now - self._last_refill_at
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rps)
            self._last_refill_at = now

    def acquire(self, tokens: float = 1.0) -> None:
        """Acquires tokens from the bucket, blocking until they are available.

        Args:
            tokens: Number of tokens to acquire (defaults to 1.0).

        Raises:
            ValueError: If the requested tokens exceed the bucket's maximum capacity.
        """
        if tokens <= 0.0:
            raise ValueError("tokens must be strictly positive")
        if tokens > self._capacity:
            raise ValueError(
                f"Cannot acquire {tokens} tokens, greater than bucket capacity {self._capacity}"
            )

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                needed = tokens - self._tokens
                sleep_time = needed / self._rps

            time.sleep(sleep_time)

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Attempts to acquire tokens without blocking.

        Args:
            tokens: Number of tokens to acquire (defaults to 1.0).

        Returns:
            True if tokens were successfully acquired, False otherwise.

        Raises:
            ValueError: If the requested tokens exceed the bucket's maximum capacity.
        """
        if tokens <= 0.0:
            raise ValueError("tokens must be strictly positive")
        if tokens > self._capacity:
            raise ValueError(
                f"Cannot acquire {tokens} tokens, greater than bucket capacity {self._capacity}"
            )

        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True

            return False


_PROCESS_BUCKETS_LOCK = threading.Lock()
_PROCESS_BUCKETS: dict[tuple[float, float], TokenBucket] = {}


def get_process_token_bucket(
    rps: float = PAID_TIER.rps, capacity: float | None = None
) -> TokenBucket:
    """Return the process-wide TokenBucket for a rate/capacity pair."""
    resolved_capacity = capacity if capacity is not None else max(rps, 1.0)
    key = (rps, resolved_capacity)
    with _PROCESS_BUCKETS_LOCK:
        bucket = _PROCESS_BUCKETS.get(key)
        if bucket is None:
            bucket = TokenBucket(rps=rps, capacity=resolved_capacity)
            _PROCESS_BUCKETS[key] = bucket
        return bucket
