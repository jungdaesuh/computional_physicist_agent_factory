"""Unit tests for Phase B operator surfaces."""

from __future__ import annotations

import pytest

from factory.operator.api import (
    SecretRef,
    SecretResolver,
    create_g6_approval_event,
    create_g6_rejection_event,
)
from factory.operator.cli import main
from factory.operator.errors import OperatorError


class MockKeyring:
    def get_password(self, service_name: str, username: str) -> str | None:
        if service_name == "factory" and username == "operator":
            return "keyring-secret"
        return None


def test_secret_resolver_prefers_env_and_supports_keyring() -> None:
    env_resolver = SecretResolver(env={"FACTORY_TOKEN": "env-secret"})
    env_secret = env_resolver.resolve(SecretRef(name="token", env_var="FACTORY_TOKEN"))
    assert env_secret.value == "env-secret"
    assert env_secret.source == "env:FACTORY_TOKEN"

    keyring_resolver = SecretResolver(env={}, keyring_backend=MockKeyring())
    keyring_secret = keyring_resolver.resolve(
        SecretRef(
            name="token",
            keyring_service="factory",
            keyring_username="operator",
        )
    )
    assert keyring_secret.value == "keyring-secret"
    assert keyring_secret.source == "keyring"


def test_g6_approval_requires_signature_and_rejection_requires_reason() -> None:
    approval = create_g6_approval_event(
        target_id="report-1",
        operator="ada",
        approval_signature="ada@example.com sha256:abc",
    )
    assert approval.event_type == "g6_approve"
    assert approval.approval_signature == "ada@example.com sha256:abc"
    assert approval.reject_reason is None

    rejection = create_g6_rejection_event(
        target_id="report-1",
        operator="ada",
        reject_reason="missing validation appendix",
    )
    assert rejection.event_type == "g6_reject"
    assert rejection.reject_reason == "missing validation appendix"
    assert rejection.approval_signature is None

    with pytest.raises(OperatorError, match="approval signature"):
        create_g6_approval_event(target_id="report-1", operator="ada", approval_signature=" ")

    with pytest.raises(OperatorError, match="requires a reason"):
        create_g6_rejection_event(target_id="report-1", operator="ada", reject_reason="")


def test_factory_start_mock_multi_cycle_cli(capsys: pytest.CaptureFixture[str]) -> None:
    main(("start", "--mock-mode", "--multi-cycle", "--format", "json"))

    lines = capsys.readouterr().out.splitlines()

    assert lines[0] == '{"event": "factory_start", "mode": "mock", "cycles": 2}'
    assert lines[1].startswith('{"event": "cycle_complete", "cycle_id": "mock-cycle-1"')
    assert lines[2].startswith('{"event": "cycle_complete", "cycle_id": "mock-cycle-2"')
    assert lines[3] == '{"event": "factory_stop", "reason": "cycle_bound_reached"}'
