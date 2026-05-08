"""Local toolkit run lifecycle service."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Callable
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Any

from video_editing_toolkit.runtime.models import (
    RunRecord,
    RunRequest,
    RunResponse,
    RunStatus,
)
from video_editing_toolkit.runtime.queue import InMemoryLocalQueue
from video_editing_toolkit.runtime.retry import (
    cancelled_retry_state,
    coerce_max_attempts,
    complete_retry_state,
    failure_retry_state,
    initial_retry_state,
    running_retry_state,
)
from video_editing_toolkit.runtime.usage import build_usage_summary
from video_editing_toolkit.storage.artifacts import ArtifactRef, LocalArtifactStore

RunHandler = Callable[[RunRequest, LocalArtifactStore], dict[str, Any] | RunResponse]


class LocalRunService:
    """Coordinates submit/status/cancel/cleanup for local toolkit runs."""

    def __init__(
        self,
        *,
        artifact_store: LocalArtifactStore,
        queue: InMemoryLocalQueue | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.queue = queue or InMemoryLocalQueue()
        self._records: dict[str, RunRecord] = {}
        self._handlers: dict[tuple[str, str], RunHandler] = {}
        self._lock = Lock()

    def register_handler(
        self,
        toolkit_id: str,
        capability: str,
        handler: RunHandler,
    ) -> None:
        self._handlers[(toolkit_id, capability)] = handler

    def submit(self, request: RunRequest) -> RunResponse:
        max_attempts = coerce_max_attempts(request.max_attempts)
        request.max_attempts = max_attempts
        response = RunResponse(
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            status=RunStatus.QUEUED,
            retry=initial_retry_state(max_attempts=max_attempts),
            trace_ref=request.trace_ref or f"local_trace:{request.run_id}",
        )
        record = RunRecord(
            request=request,
            response=response,
            max_attempts=max_attempts,
        )

        with self._lock:
            self._records[request.run_id] = record
            self.queue.enqueue(request.run_id)

        return deepcopy(response)

    def submit_public(self, request: RunRequest) -> dict[str, Any]:
        return self.submit(request).to_public_dict()

    def status(self, run_id: str) -> RunResponse | None:
        with self._lock:
            record = self._records.get(run_id)
            return deepcopy(record.response) if record else None

    def status_public(self, run_id: str) -> dict[str, Any] | None:
        response = self.status(run_id)
        return response.to_public_dict() if response else None

    def cancel(self, run_id: str) -> RunResponse | None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return None

            if record.response.status in {
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            }:
                return deepcopy(record.response)

            self.queue.cancel(run_id)
            record.cancelled_at = datetime.now(timezone.utc)
            record.response.retry = cancelled_retry_state(
                attempt=record.attempt,
                max_attempts=record.max_attempts,
            )
            record.update_status(RunStatus.CANCELLED)
            return deepcopy(record.response)

    def cancel_public(self, run_id: str) -> dict[str, Any] | None:
        response = self.cancel(run_id)
        return response.to_public_dict() if response else None

    def cleanup(self, run_id: str, *, delete_artifacts: bool = False) -> bool:
        with self._lock:
            record = self._records.pop(run_id, None)

        if record is None:
            return False

        self.queue.clear_cancelled(run_id)
        if delete_artifacts:
            for artifact_ref in record.response.artifact_refs:
                self.artifact_store.delete(artifact_ref.artifact_id)
        return True

    def process_next(self) -> RunResponse | None:
        run_id = self.queue.dequeue()
        if run_id is None:
            return None
        return self.process(run_id)

    def process_next_public(self) -> dict[str, Any] | None:
        response = self.process_next()
        return response.to_public_dict() if response else None

    def process(self, run_id: str) -> RunResponse | None:
        with self._lock:
            record = self._records.get(run_id)
            if record is None:
                return None
            if record.response.status == RunStatus.CANCELLED:
                return deepcopy(record.response)
            if record.response.status in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
                return deepcopy(record.response)
            record.attempt += 1
            attempt = record.attempt
            record.response.retry = running_retry_state(
                attempt=attempt,
                max_attempts=record.max_attempts,
            )
            record.update_status(RunStatus.RUNNING)

        started = perf_counter()
        request = record.request
        handler = self._handlers.get((request.toolkit_id, request.capability))

        if handler is None:
            response = RunResponse(
                run_id=request.run_id,
                tool_call_id=request.tool_call_id,
                status=RunStatus.FAILED,
                trace_ref=record.response.trace_ref,
                error_code="handler_not_registered",
                error_message=(
                    f"No local handler registered for "
                    f"{request.toolkit_id}.{request.capability}."
                ),
            )
            return self._complete_attempt(record, response, started=started)

        try:
            result = handler(request, self.artifact_store)
            response = self._coerce_handler_result(record, result)
            return self._complete_attempt(record, response, started=started)
        except Exception as exc:
            response = RunResponse(
                run_id=request.run_id,
                tool_call_id=request.tool_call_id,
                status=RunStatus.FAILED,
                trace_ref=record.response.trace_ref,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
            return self._complete_attempt(record, response, started=started)

    def process_public(self, run_id: str) -> dict[str, Any] | None:
        response = self.process(run_id)
        return response.to_public_dict() if response else None

    def _coerce_handler_result(
        self,
        record: RunRecord,
        result: dict[str, Any] | RunResponse,
    ) -> RunResponse:
        if isinstance(result, RunResponse):
            return result

        artifact_refs = result.get("artifact_refs", [])
        return RunResponse(
            run_id=record.request.run_id,
            tool_call_id=record.request.tool_call_id,
            status=RunStatus.SUCCEEDED,
            output=result.get("output", {}),
            artifact_refs=[
                ref for ref in artifact_refs if isinstance(ref, ArtifactRef)
            ],
            usage_metrics=result.get("usage_metrics", {}),
            trace_ref=record.response.trace_ref,
        )

    def _complete_attempt(
        self,
        record: RunRecord,
        response: RunResponse,
        *,
        started: float,
    ) -> RunResponse:
        runtime_ms = round((perf_counter() - started) * 1000, 3)
        existing_runtime_ms = response.usage_metrics.get("runtime_ms")
        if isinstance(existing_runtime_ms, bool) or not isinstance(existing_runtime_ms, (int, float)):
            response.usage_metrics["runtime_ms"] = runtime_ms
        else:
            runtime_ms = round(float(existing_runtime_ms), 3)
        attempt = record.attempt

        if response.status == RunStatus.SUCCEEDED:
            response.retry = complete_retry_state(
                attempt=attempt,
                max_attempts=record.max_attempts,
            )
        elif response.status == RunStatus.FAILED:
            response.retry, decision = failure_retry_state(
                attempt=attempt,
                max_attempts=record.max_attempts,
                error_code=response.error_code,
            )
            if decision.should_retry:
                response.status = RunStatus.QUEUED
        else:
            response.retry = running_retry_state(
                attempt=attempt,
                max_attempts=record.max_attempts,
            )

        response.usage_summary = build_usage_summary(
            request=record.request,
            response=response,
            runtime_ms=runtime_ms,
            attempt=attempt,
        )

        with self._lock:
            if record.cancelled_at is not None:
                record.response.retry = cancelled_retry_state(
                    attempt=attempt,
                    max_attempts=record.max_attempts,
                )
                record.update_status(RunStatus.CANCELLED)
                return deepcopy(record.response)

            record.response = response
            record.updated_at = datetime.now(timezone.utc)
            if (
                response.status == RunStatus.QUEUED
                and response.retry.get("scheduled") is True
            ):
                self.queue.enqueue(record.request.run_id)
            return deepcopy(record.response)
