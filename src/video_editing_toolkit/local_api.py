"""FastAPI local HTTP surface for the P0.7 runtime worker.

The module intentionally does not import FastAPI at module import time so the
default package and test suite stay free of API dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from video_editing_toolkit.agentctl import (
    TOOLKIT_ID,
    _artifact_refs,
    _caller_safe,
    _optional_string,
    _policy_context,
    _required_string,
    _should_hold_agentctl_artifact_refs,
)
from video_editing_toolkit.runtime import (
    LocalRunService,
    RunRequest,
    register_p0_adapter_handlers,
)
from video_editing_toolkit.storage import LocalArtifactStore


DEFAULT_ARTIFACT_ROOT = Path(".video-toolkit-data") / "local-api-artifacts"
DEFAULT_MANIFESTS_DIR = Path("manifests")
LOCAL_API_SCHEMA = "video_editing_toolkit.local_http_api.v0"
PUBLIC_ARTIFACT_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_type",
        "mime_type",
        "size_bytes",
        "checksum",
        "data_class",
        "retention_policy",
        "expires_at",
        "access_policy",
        "download_url",
    }
)


class LocalApiState:
    """Owns the process-local service and caller-visible artifact metadata."""

    def __init__(
        self,
        *,
        artifact_root: str | Path | None = None,
        manifests_dir: str | Path | None = None,
        service: LocalRunService | None = None,
        process_sync: bool = True,
    ) -> None:
        self.artifact_root = Path(
            artifact_root
            or os.environ.get("VIDEO_TOOLKIT_ARTIFACT_ROOT")
            or DEFAULT_ARTIFACT_ROOT
        )
        self.manifests_dir = Path(manifests_dir or DEFAULT_MANIFESTS_DIR)
        self.process_sync = process_sync
        self.service = service or LocalRunService(
            artifact_store=LocalArtifactStore(self.artifact_root)
        )
        register_p0_adapter_handlers(self.service)
        self._artifact_metadata: dict[str, dict[str, Any]] = {}

    def submit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        request = _run_request_from_payload(payload)
        queued = self.service.submit_public(request)
        response = queued
        if self.process_sync:
            processed = self.service.process_next_public()
            if processed is not None:
                response = processed
        self._index_artifacts(response)
        return _caller_safe(response)

    def status(self, run_id: str) -> dict[str, Any] | None:
        response = self.service.status_public(run_id)
        if response is not None:
            self._index_artifacts(response)
        return _caller_safe(response) if response is not None else None

    def cancel(self, run_id: str) -> dict[str, Any] | None:
        response = self.service.cancel_public(run_id)
        if response is not None:
            self._index_artifacts(response)
        return _caller_safe(response) if response is not None else None

    def artifact(self, artifact_id: str) -> dict[str, Any] | None:
        metadata = self._artifact_metadata.get(artifact_id)
        return _caller_safe(metadata) if metadata is not None else None

    def manifests(self) -> dict[str, Any]:
        manifests: list[dict[str, Any]] = []
        if self.manifests_dir.exists():
            for path in sorted(self.manifests_dir.glob("*.json")):
                if path.is_file():
                    manifests.append(
                        {
                            "file_name": path.name,
                            "manifest": json.loads(path.read_text(encoding="utf-8")),
                        }
                    )
        return _caller_safe(
            {
                "schema": LOCAL_API_SCHEMA,
                "transport": "local.http",
                "toolkit_id": TOOLKIT_ID,
                "manifests": manifests,
            }
        )

    def _index_artifacts(self, response: Mapping[str, Any]) -> None:
        for artifact in _collect_public_artifacts(response):
            self._artifact_metadata[artifact["artifact_id"]] = artifact


def create_app(
    *,
    artifact_root: str | Path | None = None,
    manifests_dir: str | Path | None = None,
    service: LocalRunService | None = None,
    process_sync: bool = True,
) -> Any:
    """Create a FastAPI app for tests or local development."""

    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:  # pragma: no cover - exercised in non-api installs
        raise RuntimeError(
            "FastAPI is required for the local HTTP API. "
            'Install with `pip install -e ".[api]"`.'
        ) from exc

    state = LocalApiState(
        artifact_root=artifact_root,
        manifests_dir=manifests_dir,
        service=service,
        process_sync=process_sync,
    )
    app = FastAPI(
        title="Video Editing Toolkit Local API",
        version="0.1.0-p0.7",
    )
    app.state.local_api = state

    @app.post("/local/toolkit-runs")
    def create_toolkit_run(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return state.submit(payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_code": "local_api.invalid_request",
                    "error_message": str(exc),
                },
            ) from exc

    @app.get("/local/toolkit-runs/{run_id}")
    def get_toolkit_run(run_id: str) -> dict[str, Any]:
        response = state.status(run_id)
        if response is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "local_api.run_not_found",
                    "error_message": f"Run {run_id!r} was not found.",
                },
            )
        return response

    @app.post("/local/toolkit-runs/{run_id}/cancel")
    def cancel_toolkit_run(run_id: str) -> dict[str, Any]:
        response = state.cancel(run_id)
        if response is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "local_api.run_not_found",
                    "error_message": f"Run {run_id!r} was not found.",
                },
            )
        return response

    @app.get("/local/artifacts/{artifact_id}")
    def get_artifact(artifact_id: str) -> dict[str, Any]:
        response = state.artifact(artifact_id)
        if response is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "local_api.artifact_not_found",
                    "error_message": f"Artifact {artifact_id!r} was not found.",
                },
            )
        return response

    @app.get("/local/manifests")
    def get_manifests() -> dict[str, Any]:
        return state.manifests()

    return app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the video-editing-toolkit P0.7 local HTTP API.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--artifact-root", default=None)
    parser.add_argument("--manifests-dir", default=None)
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError(
            "uvicorn is required to serve the local HTTP API. "
            'Install with `pip install -e ".[api]"`.'
        ) from exc

    app = create_app(
        artifact_root=args.artifact_root,
        manifests_dir=args.manifests_dir,
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _run_request_from_payload(payload: Mapping[str, Any]) -> RunRequest:
    toolkit_id = _required_string(payload, "toolkit_id")
    capability = _required_string(payload, "capability")
    input_payload = payload.get("input", {})
    if not isinstance(input_payload, Mapping):
        raise ValueError("input must be a JSON object when provided.")

    policy_context = _policy_context(payload)
    artifact_refs = _artifact_refs(payload, policy_context=policy_context)
    if _should_hold_agentctl_artifact_refs(capability, input_payload, artifact_refs):
        artifact_refs = []

    request_kwargs: dict[str, Any] = {}
    run_id = _optional_string(payload.get("run_id"))
    tool_call_id = _optional_string(payload.get("tool_call_id"))
    trace_ref = _optional_string(payload.get("trace_ref")) or _optional_string(payload.get("trace_id"))
    if run_id is not None:
        request_kwargs["run_id"] = run_id
    if tool_call_id is not None:
        request_kwargs["tool_call_id"] = tool_call_id

    return RunRequest(
        toolkit_id=toolkit_id,
        capability=capability,
        input=dict(input_payload),
        version=_optional_string(payload.get("version")) or "0.1.0",
        artifact_refs=artifact_refs,
        policy_context=policy_context,
        dry_run=bool(payload.get("dry_run", False)),
        trace_ref=trace_ref,
        **request_kwargs,
    )


def _collect_public_artifacts(value: Any) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    _collect_public_artifacts_into(value, artifacts)
    return artifacts


def _collect_public_artifacts_into(value: Any, artifacts: list[dict[str, Any]]) -> None:
    if isinstance(value, Mapping):
        artifact = _public_artifact_from_mapping(value)
        if artifact is not None:
            artifacts.append(artifact)
        for child in value.values():
            _collect_public_artifacts_into(child, artifacts)
    elif isinstance(value, list):
        for child in value:
            _collect_public_artifacts_into(child, artifacts)


def _public_artifact_from_mapping(value: Mapping[str, Any]) -> dict[str, Any] | None:
    artifact_id = value.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        return None
    artifact_type = value.get("artifact_type")
    if not isinstance(artifact_type, str) or not artifact_type:
        return None

    metadata = {
        key: child
        for key, child in value.items()
        if key in PUBLIC_ARTIFACT_KEYS
    }
    metadata.setdefault("access_policy", {})
    metadata.setdefault("expires_at", None)
    return dict(metadata)


if __name__ == "__main__":
    raise SystemExit(main())
