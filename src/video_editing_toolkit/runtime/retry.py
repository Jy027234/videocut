"""Retry policy helpers for the local P0 runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_MAX_ATTEMPTS = 1
DEFAULT_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 16.0)

TERMINAL_ERROR_CODES = frozenset(
    {
        "handler_not_registered",
        "request.invalid",
        "capability.unsupported",
        "adapter.not_implemented",
        "artifact_ref.invalid",
        "artifact_ref.access_denied",
        "resource.input_too_large",
        "resource.output_too_large",
        "resource.media_duration_too_long",
        "worker.cancelled",
    }
)

RETRYABLE_ERROR_CODES = frozenset(
    {
        "adapter.unavailable",
        "resource.timeout_exceeded",
        "resource.concurrency_limit_exceeded",
        "internal.error",
    }
)


@dataclass(frozen=True, slots=True)
class RetryDecision:
    """Machine-readable retry outcome for one failed attempt."""

    retryable_failure: bool
    should_retry: bool
    terminal_reason: str | None
    next_retry_delay_seconds: float | None


def coerce_max_attempts(value: Any, *, default: int = DEFAULT_MAX_ATTEMPTS) -> int:
    """Return a safe max_attempts value for P0 local scheduling."""

    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(1, min(value, 10))
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(1, min(parsed, 10))
    return default


def initial_retry_state(*, max_attempts: int) -> dict[str, Any]:
    """Build the public retry state for a newly queued run."""

    return {
        "attempt": 0,
        "max_attempts": max_attempts,
        "retryable_failure": None,
        "scheduled": False,
        "next_retry_delay_seconds": None,
        "terminal_reason": None,
        "backoff_schedule_seconds": list(DEFAULT_BACKOFF_SECONDS),
    }


def running_retry_state(*, attempt: int, max_attempts: int) -> dict[str, Any]:
    state = initial_retry_state(max_attempts=max_attempts)
    state["attempt"] = attempt
    return state


def complete_retry_state(*, attempt: int, max_attempts: int) -> dict[str, Any]:
    state = running_retry_state(attempt=attempt, max_attempts=max_attempts)
    state["retryable_failure"] = False
    state["terminal_reason"] = "succeeded"
    return state


def cancelled_retry_state(*, attempt: int, max_attempts: int) -> dict[str, Any]:
    state = running_retry_state(attempt=attempt, max_attempts=max_attempts)
    state["retryable_failure"] = False
    state["terminal_reason"] = "cancelled"
    return state


def failure_retry_state(
    *,
    attempt: int,
    max_attempts: int,
    error_code: str | None,
) -> tuple[dict[str, Any], RetryDecision]:
    """Return public retry state and the decision for a failed attempt."""

    decision = decide_retry(
        attempt=attempt,
        max_attempts=max_attempts,
        error_code=error_code,
    )
    state = running_retry_state(attempt=attempt, max_attempts=max_attempts)
    state["retryable_failure"] = decision.retryable_failure
    state["scheduled"] = decision.should_retry
    state["next_retry_delay_seconds"] = decision.next_retry_delay_seconds
    state["terminal_reason"] = decision.terminal_reason
    return state, decision


def decide_retry(
    *,
    attempt: int,
    max_attempts: int,
    error_code: str | None,
) -> RetryDecision:
    """Classify a failed attempt without randomness or wall-clock dependence."""

    if error_code in TERMINAL_ERROR_CODES:
        return RetryDecision(
            retryable_failure=False,
            should_retry=False,
            terminal_reason="terminal_error",
            next_retry_delay_seconds=None,
        )

    retryable = error_code in RETRYABLE_ERROR_CODES or error_code is None
    if not retryable:
        retryable = "." not in error_code

    if not retryable:
        return RetryDecision(
            retryable_failure=False,
            should_retry=False,
            terminal_reason="terminal_error",
            next_retry_delay_seconds=None,
        )

    if attempt >= max_attempts:
        return RetryDecision(
            retryable_failure=True,
            should_retry=False,
            terminal_reason="max_attempts_exhausted",
            next_retry_delay_seconds=None,
        )

    return RetryDecision(
        retryable_failure=True,
        should_retry=True,
        terminal_reason=None,
        next_retry_delay_seconds=backoff_seconds_for_attempt(attempt),
    )


def backoff_seconds_for_attempt(attempt: int) -> float:
    """Return the deterministic retry delay after a failed attempt."""

    if attempt <= 0:
        return DEFAULT_BACKOFF_SECONDS[0]
    index = min(attempt - 1, len(DEFAULT_BACKOFF_SECONDS) - 1)
    return DEFAULT_BACKOFF_SECONDS[index]
