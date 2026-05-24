"""Typed secret resolution through environment and keyring-style backends."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from factory.operator.errors import OperatorError


class KeyringBackend(Protocol):
    """Small keyring contract used without exposing secret values to logs."""

    def get_password(self, service_name: str, username: str) -> str | None:
        """Return a secret value for service and username."""


@dataclass(frozen=True, slots=True)
class SecretRef:
    """Reference to a secret, not the secret value."""

    name: str
    env_var: str | None = None
    keyring_service: str | None = None
    keyring_username: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSecret:
    """Resolved secret value plus non-sensitive source metadata."""

    ref: SecretRef
    value: str = field(repr=False)
    source: str


class SecretResolver:
    """Resolve secrets from env first, then an injected keyring backend."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        keyring_backend: KeyringBackend | None = None,
    ) -> None:
        self._env = env if env is not None else os.environ
        self._keyring_backend = keyring_backend

    def resolve(self, ref: SecretRef) -> ResolvedSecret:
        """Resolve one secret or raise without including secret material."""
        if ref.env_var is not None:
            env_value = self._env.get(ref.env_var)
            if env_value is not None and env_value != "":
                return ResolvedSecret(ref=ref, value=env_value, source=f"env:{ref.env_var}")

        if ref.keyring_service is not None and ref.keyring_username is not None:
            if self._keyring_backend is None:
                raise OperatorError(f"Keyring backend is required for secret: {ref.name}")
            keyring_value = self._keyring_backend.get_password(
                ref.keyring_service,
                ref.keyring_username,
            )
            if keyring_value is not None and keyring_value != "":
                return ResolvedSecret(ref=ref, value=keyring_value, source="keyring")

        raise OperatorError(f"Secret is not configured: {ref.name}")
