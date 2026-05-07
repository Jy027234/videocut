"""P0.5 local chain demo for the toolkit runtime boundary."""

from __future__ import annotations

import json
import struct
import tempfile
import wave
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from video_editing_toolkit.runtime import (
    LocalRunService,
    RunRequest,
    register_p0_adapter_handlers,
)
from video_editing_toolkit.storage import LocalArtifactStore

TOOLKIT_ID = "video-editing-toolkit"
TENANT_ID = "demo_tenant"
PROJECT_ID = "proj_demo_0001"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="video-toolkit-demo-") as temp_dir:
        artifact_store = LocalArtifactStore(Path(temp_dir) / "artifacts")
        service = LocalRunService(artifact_store=artifact_store)
        register_p0_adapter_handlers(service)
        input_media_path = Path(temp_dir) / "demo-input.wav"
        _create_tiny_wav(input_media_path)
        input_artifact_ref = artifact_store.put_file(
            source_path=input_media_path,
            artifact_type="input_audio",
            owner_tenant_id=TENANT_ID,
            created_by_run_id="demo_setup",
            mime_type="audio/wav",
        )

        upload_step = {
            "status": "uploaded",
            "artifact_ref": input_artifact_ref.to_public_dict(),
        }

        probe_step = _run_public_step(
            service,
            capability="video.asset_ingest.probe_media",
            input_payload={"artifact_ref": {"artifact_id": input_artifact_ref.artifact_id}},
            artifact_refs=[input_artifact_ref],
        )

        asset_index_step = _run_public_step(
            service,
            capability="video.asset_ingest.build_asset_index",
            input_payload={
                "artifact_refs": [{"artifact_id": input_artifact_ref.artifact_id}],
                "index_profile": "p0_chain_demo",
            },
            artifact_refs=[input_artifact_ref],
        )

        create_project_step = _run_public_step(
            service,
            capability="video.project_edit.create_project",
            input_payload={"project_id": PROJECT_ID},
        )
        base_version_id = _output_value(
            create_project_step["processed"],
            "version_id",
            default="ver_0001",
        )

        patch_step = _run_public_step(
            service,
            capability="video.project_edit.apply_timeline_patch",
            input_payload={
                "project_id": PROJECT_ID,
                "base_version_id": base_version_id,
                "timeline_patch": {
                    "operations": [
                        {
                            "op": "add_clip",
                            "track_id": "v1",
                            "clip_id": "clip_intro_0001",
                            "asset_ref": {
                                "artifact_id": input_artifact_ref.artifact_id,
                                "artifact_type": input_artifact_ref.artifact_type,
                            },
                            "timeline_start_seconds": 0.0,
                            "source_in_seconds": 0.0,
                            "source_out_seconds": 0.1,
                        }
                    ]
                },
                "change_reason": "Create P0.5 local chain demo intro.",
                "requested_preview": True,
            },
            artifact_refs=[input_artifact_ref],
        )
        preview_version_id = _output_value(
            patch_step["processed"],
            "new_version_id",
            default=base_version_id,
        )

        preview_step = _run_public_step(
            service,
            capability="video.project_edit.render_preview",
            input_payload={
                "project_id": PROJECT_ID,
                "version_id": preview_version_id,
                "preview_profile": "p0_local_stub",
            },
        )
        delivery_step = _run_public_step(
            service,
            capability="video.delivery.create_delivery_manifest",
            input_payload={
                "project_id": PROJECT_ID,
                "version": preview_version_id,
                "target": "review",
                "asset_index_ref": _output_value(
                    asset_index_step["processed"],
                    "asset_index_artifact_ref",
                    "artifact_id",
                    default="asset_index_unavailable",
                ),
                "preview_artifact_ref": _output_value(
                    preview_step["processed"],
                    "preview_artifact_ref",
                    default={},
                ),
            },
            artifact_refs=[input_artifact_ref],
        )

        print(
            json.dumps(
                {
                    "chain": [
                        "upload_artifact",
                        "probe_media",
                        "build_asset_index",
                        "create_project",
                        "apply_timeline_patch",
                        "render_preview",
                        "create_delivery_manifest",
                    ],
                    "platform_mapping": {
                        "upload_artifact": "Platform Core artifact upload",
                        "submit_public": "agentctl tool run submit",
                        "process_next_public": "local worker queue execution",
                        "artifact_refs": "caller-safe artifact handles",
                    },
                    "upload_artifact": upload_step,
                    "probe_media": probe_step,
                    "build_asset_index": asset_index_step,
                    "create_project": create_project_step,
                    "apply_timeline_patch": patch_step,
                    "render_preview": preview_step,
                    "create_delivery_manifest": delivery_step,
                    "notes": [
                        "All run output is produced through LocalRunService public methods.",
                        "Local filesystem paths stay private to the artifact store and worker bridge.",
                        "Placeholder capabilities may fail gracefully until their worker is implemented.",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


def _run_public_step(
    service: LocalRunService,
    *,
    capability: str,
    input_payload: Mapping[str, Any],
    artifact_refs: list[Any] | None = None,
) -> dict[str, Any]:
    request = RunRequest(
        toolkit_id=TOOLKIT_ID,
        capability=capability,
        input=dict(input_payload),
        artifact_refs=artifact_refs or [],
    )
    queued = service.submit_public(request)
    processed = service.process_next_public()
    return _json_safe(
        {
            "capability": capability,
            "queued": queued,
            "processed": processed,
        }
    )


def _output_value(
    processed: Mapping[str, Any] | None,
    *keys: str,
    default: Any,
) -> Any:
    current: Any = processed
    if isinstance(current, Mapping):
        current = current.get("output")
    for key in keys:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    if isinstance(current, str) and current:
        return current
    if isinstance(current, Mapping):
        return dict(current)
    if isinstance(processed, Mapping):
        return current if current is not None else default
    return default


def _create_tiny_wav(path: Path) -> None:
    sample_rate = 8000
    sample_count = 800
    amplitude = 1000

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for index in range(sample_count):
            sample = amplitude if index % 2 == 0 else -amplitude
            wav_file.writeframes(struct.pack("<h", sample))


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {key: _json_safe(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_json_safe(child) for child in value]
    if hasattr(value, "value"):
        return value.value
    return value


if __name__ == "__main__":
    main()
