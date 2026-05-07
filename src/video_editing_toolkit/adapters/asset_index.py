"""Structured asset-index adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS, ErrorCode
from video_editing_toolkit.storage import LocalArtifactStore

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


BUILD_ASSET_INDEX = "video.asset_ingest.build_asset_index"


class AssetIndexAdapter(BaseAdapter):
    adapter_name = "asset_index"
    supported_capabilities = frozenset(
        {
            BUILD_ASSET_INDEX,
        }
    )
    default_limits = CPU_LIGHT_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability == BUILD_ASSET_INDEX:
            return self._build_asset_index(request)
        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def build_asset_index(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def _build_asset_index(self, request: AdapterRequest) -> AdapterResult:
        artifact_store = self._artifact_store(request)
        if artifact_store is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="build_asset_index requires a configured artifact store.",
            )

        input_refs = [_public_artifact_ref(ref) for ref in request.artifact_refs]
        worker_paths = _worker_media_paths(request.input)
        asset_count = max(len(input_refs), len(worker_paths))
        assets = [
            {
                "asset_id": f"asset_{index + 1:04d}",
                "input_index": index,
                "artifact_ref": input_refs[index] if index < len(input_refs) else None,
                "worker_input_resolved": index < len(worker_paths),
            }
            for index in range(asset_count)
        ]

        asset_index = {
            "schema": "video_editing_toolkit.asset_index.v0",
            "project_id": request.context.project_id,
            "run_id": request.context.run_id,
            "asset_count": asset_count,
            "assets": assets,
        }
        artifact_ref = artifact_store.put_bytes(
            content=_json_bytes(asset_index),
            artifact_type="asset_index",
            owner_tenant_id=request.context.tenant_id,
            created_by_run_id=request.context.run_id,
            filename="asset_index.json",
            mime_type="application/json",
        )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "asset_count": asset_count,
                "asset_index_artifact_ref": artifact_ref.to_public_dict(),
                "artifact_ref": artifact_ref.to_public_dict(),
                "input_artifact_refs": input_refs,
            },
            artifact_refs=(artifact_ref,),
            usage_metrics={
                "operation": "build_asset_index",
                "asset_count": asset_count,
                "output_bytes": artifact_ref.size_bytes,
            },
        )

    def _artifact_store(self, request: AdapterRequest) -> LocalArtifactStore | None:
        artifact_store = request.input.get("_artifact_store")
        if isinstance(artifact_store, LocalArtifactStore):
            return artifact_store
        return None


def _public_artifact_ref(ref: Any) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in dict(getattr(ref, "metadata", {}) or {}).items()
        if not str(key).startswith("_")
    }
    return {
        "artifact_id": ref.ref,
        "artifact_type": ref.kind,
        "mime_type": ref.media_type,
        "size_bytes": ref.size_bytes,
        "checksum": ref.checksum,
        "data_class": metadata.get("data_class"),
        "retention_policy": metadata.get("retention_policy"),
    }


def _worker_media_paths(input_payload: Mapping[str, Any]) -> tuple[Path, ...]:
    paths = input_payload.get("_worker_media_paths")
    if isinstance(paths, tuple):
        return tuple(Path(path) for path in paths if isinstance(path, str) and path)
    single_path = input_payload.get("_worker_media_path")
    if isinstance(single_path, str) and single_path:
        return (Path(single_path),)
    return ()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
