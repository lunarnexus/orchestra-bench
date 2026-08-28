"""Auto-run completion policy and safe-to-grade adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from bench.orchestration import (
    OrchestrationSettleResult,
    OrchestrationStatusSnapshot,
    StatusProvider,
    wait_for_orchestration_settle,
)


@runtime_checkable
class SettlingHarness(Protocol):
    def wait_for_settled(self, timeout: float | None = None) -> bool:
        ...

    @property
    def last_settle_status(self) -> str:
        ...


@dataclass(frozen=True)
class CompletionPolicy:
    orchestra_enabled: bool = False
    settle_timeout_seconds: float | None = None
    poll_interval_seconds: float = 5.0
    accept_terminal_states: frozenset[str] = field(
        default_factory=lambda: frozenset({"settled", "timeout", "failed"})
    )


CompletionResult = OrchestrationSettleResult



def wait_until_safe_to_grade(
    harness: SettlingHarness,
    *,
    session_id: str = "",
    status_provider: StatusProvider | None = None,
    policy: CompletionPolicy | None = None,
    timeout_seconds: float | None = None,
) -> CompletionResult:
    policy = policy or CompletionPolicy()
    harness_timeout = timeout_seconds if timeout_seconds is not None else policy.settle_timeout_seconds
    harness_settled = harness.wait_for_settled(timeout=harness_timeout)
    harness_status = getattr(harness, "last_settle_status", "unknown")
    if not harness_settled:
        return CompletionResult(
            safe_to_grade=False,
            reason=harness_status or "harness_not_settled",
            harness_status=harness_status,
            session_id=session_id,
            snapshots=(),
        )
    if not policy.orchestra_enabled:
        return CompletionResult(
            safe_to_grade=True,
            reason="harness_terminal",
            harness_status=harness_status,
            session_id=session_id,
            snapshots=(),
        )
    if status_provider is None:
        return CompletionResult(
            safe_to_grade=False,
            reason="missing_status_provider",
            harness_status=harness_status,
            session_id=session_id,
            snapshots=(),
        )
    settle = wait_for_orchestration_settle(
        session_id,
        status_provider,
        timeout_seconds=policy.settle_timeout_seconds,
        poll_interval_seconds=policy.poll_interval_seconds,
        accept_terminal_states=policy.accept_terminal_states,
    )
    return CompletionResult(
        safe_to_grade=settle.safe_to_grade,
        reason=settle.reason,
        harness_status=harness_status,
        session_id=session_id,
        snapshots=settle.snapshots,
    )
