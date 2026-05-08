"""Repeatable local P1 QC evidence smoke runner."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from video_editing_toolkit.adapters.qc import GENERATE_MEDIA_INSPECTION_EVIDENCE
from video_editing_toolkit.agentctl import run_agentctl
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore


SCHEMA = "video_editing_toolkit.p1_qc_evidence_smoke.v0"
RESULT_SCHEMA = "video_editing_toolkit.p1_qc_evidence_smoke_result.v0"
TOOLKIT_ID = "video-editing-toolkit"
DEFAULT_ARTIFACT_ROOT = Path(".video-toolkit-data") / "p1-qc-smoke-artifacts"
_STATIC_FFMPEG_ENV = "VIDEO_TOOLKIT_USE_STATIC_FFMPEG"
_SAFE_ID_SEGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def run_p1_qc_evidence_smoke(
    *,
    input_video: str | Path,
    artifact_root: str | Path | None = None,
    result_json: str | Path | None = None,
    artifact_id: str | None = None,
    tenant_id: str = "tenant_p1_qc_smoke",
    user_id: str = "user_p1_qc_smoke",
    project_id: str = "proj_p1_qc_smoke",
    frame_limit: int = 5,
    use_static_ffmpeg: bool = False,
) -> dict[str, Any]:
    """Run the controlled local P1 QC media-inspection evidence path.

    The returned summary is intentionally compact and caller-safe. When
    ``result_json`` is provided, the full local agentctl response is written to
    that file without embedding local filesystem paths in the JSON payload.
    """

    source_path = _existing_file(input_video)
    selected_root = Path(artifact_root) if artifact_root is not None else DEFAULT_ARTIFACT_ROOT
    selected_artifact_id = artifact_id or _default_artifact_id(source_path)
    selected_frame_limit = _coerce_frame_limit(frame_limit)

    store = LocalArtifactStore(selected_root)
    source_ref = _put_or_reuse_source_ref(
        store,
        source_path=source_path,
        artifact_id=selected_artifact_id,
        tenant_id=tenant_id,
    )
    public_source_ref = _public_artifact_ref(source_ref)

    payload = {
        "toolkit_id": TOOLKIT_ID,
        "capability": GENERATE_MEDIA_INSPECTION_EVIDENCE,
        "input": {
            "project_id": project_id,
            "artifact_ref": public_source_ref,
            "frame_limit": selected_frame_limit,
        },
        "artifact_refs": [public_source_ref],
        "policy_context": {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "allow_p1_qc_media_inspection_execution": True,
        },
    }

    static_ffmpeg_enabled = use_static_ffmpeg or _env_truthy(os.environ.get(_STATIC_FFMPEG_ENV))
    previous_static_ffmpeg = os.environ.get(_STATIC_FFMPEG_ENV)
    if use_static_ffmpeg:
        os.environ[_STATIC_FFMPEG_ENV] = "1"
    try:
        response = run_agentctl(
            payload,
            artifact_root=selected_root,
            allowed_p1_capabilities=(GENERATE_MEDIA_INSPECTION_EVIDENCE,),
        )
    finally:
        if use_static_ffmpeg:
            if previous_static_ffmpeg is None:
                os.environ.pop(_STATIC_FFMPEG_ENV, None)
            else:
                os.environ[_STATIC_FFMPEG_ENV] = previous_static_ffmpeg

    summary = _build_summary(
        response,
        source_ref=public_source_ref,
        frame_limit=selected_frame_limit,
        static_ffmpeg_requested=use_static_ffmpeg,
        static_ffmpeg_enabled=static_ffmpeg_enabled,
        result_json=result_json,
    )

    if result_json is not None:
        _write_result_json(result_json, summary=summary, response=response)

    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a repeatable local P1 QC media-inspection evidence smoke with "
            "explicit P1 allowlist and policy opt-in."
        ),
    )
    parser.add_argument("--input-video", required=True, help="Local source video path.")
    parser.add_argument(
        "--artifact-root",
        help="Local artifact store root. Defaults to .video-toolkit-data/p1-qc-smoke-artifacts.",
    )
    parser.add_argument("--result-json", help="Optional JSON file for the full caller-safe smoke result.")
    parser.add_argument("--artifact-id", help="Optional stable source artifact id.")
    parser.add_argument("--tenant-id", default="tenant_p1_qc_smoke", help="Tenant id for the local smoke run.")
    parser.add_argument("--user-id", default="user_p1_qc_smoke", help="User id for the local smoke run.")
    parser.add_argument("--project-id", default="proj_p1_qc_smoke", help="Project id for the local smoke run.")
    parser.add_argument("--frame-limit", type=int, default=5, help="Maximum visual frames to sample.")
    parser.add_argument(
        "--use-static-ffmpeg",
        action="store_true",
        help="Opt in to the Windows static-ffmpeg fallback for this process.",
    )
    args = parser.parse_args(argv)

    try:
        summary = run_p1_qc_evidence_smoke(
            input_video=args.input_video,
            artifact_root=args.artifact_root,
            result_json=args.result_json,
            artifact_id=args.artifact_id,
            tenant_id=args.tenant_id,
            user_id=args.user_id,
            project_id=args.project_id,
            frame_limit=args.frame_limit,
            use_static_ffmpeg=args.use_static_ffmpeg,
        )
    except ValueError as exc:
        summary = _error_summary("p1_qc_smoke.invalid_request", str(exc))
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    except OSError:
        summary = _error_summary(
            "p1_qc_smoke.io_error",
            "The smoke runner could not read or write a required local file.",
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:
        summary = _error_summary(
            "p1_qc_smoke.execution_failed",
            f"The smoke runner failed before completion: {exc.__class__.__name__}.",
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 1

    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary.get("ok") is True else 2


def _existing_file(value: str | Path) -> Path:
    path = Path(value)
    if not path.exists() or not path.is_file():
        raise ValueError("input_video must point to an existing file.")
    return path


def _coerce_frame_limit(value: int) -> int:
    if isinstance(value, bool) or value < 1:
        raise ValueError("frame_limit must be a positive integer.")
    return min(value, 120)


def _default_artifact_id(source_path: Path) -> str:
    stat = source_path.stat()
    digest = hashlib.sha256(
        "|".join(
            (
                str(source_path.resolve()),
                str(stat.st_size),
                str(stat.st_mtime_ns),
            )
        ).encode("utf-8", errors="ignore")
    ).hexdigest()[:12]
    stem = _SAFE_ID_SEGMENT.sub("_", source_path.stem).strip("._-") or "source"
    stem = stem[:48].strip("._-") or "source"
    return f"artifact_p1_qc_smoke_{stem}_{digest}"[:128]


def _put_or_reuse_source_ref(
    store: LocalArtifactStore,
    *,
    source_path: Path,
    artifact_id: str,
    tenant_id: str,
) -> ArtifactRef:
    existing_path = store.open_local_path(artifact_id)
    if existing_path is not None:
        source_checksum = _sha256_checksum(source_path)
        if _sha256_checksum(existing_path) != source_checksum:
            raise ValueError(
                "artifact_id already exists in the smoke artifact store with different content."
            )
        return _existing_source_ref(
            store,
            artifact_id=artifact_id,
            source_path=source_path,
            tenant_id=tenant_id,
            checksum=source_checksum,
            existing_filename=existing_path.name,
        )

    return store.put_file(
        source_path=source_path,
        artifact_type="source_video",
        owner_tenant_id=tenant_id,
        created_by_run_id="p1_qc_smoke_source",
        filename=source_path.name,
        artifact_id=artifact_id,
        mime_type=mimetypes.guess_type(source_path.name)[0] or "video/mp4",
        data_class="sensitive",
        retention_policy="short_lived",
    )


def _existing_source_ref(
    store: LocalArtifactStore,
    *,
    artifact_id: str,
    source_path: Path,
    tenant_id: str,
    checksum: str,
    existing_filename: str,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type="source_video",
        owner_tenant_id=tenant_id,
        created_by_run_id="p1_qc_smoke_source",
        storage_uri=f"local-artifact://{artifact_id}/{existing_filename}",
        mime_type=mimetypes.guess_type(source_path.name)[0] or "video/mp4",
        size_bytes=source_path.stat().st_size,
        checksum=checksum,
        data_class="sensitive",
        retention_policy="short_lived",
        expires_at=None,
        access_policy={},
        download_url=f"{store.public_base_path}/{artifact_id}",
    )


def _sha256_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _public_artifact_ref(ref: ArtifactRef | Mapping[str, Any]) -> dict[str, Any]:
    raw = ref.to_public_dict() if isinstance(ref, ArtifactRef) else dict(ref)
    return {
        key: value
        for key, value in raw.items()
        if key
        not in {
            "download_url",
            "storage_uri",
            "local_path",
            "worker_path",
            "file_path",
            "filesystem_path",
        }
        and value is not None
    }


def _build_summary(
    response: Mapping[str, Any],
    *,
    source_ref: Mapping[str, Any],
    frame_limit: int,
    static_ffmpeg_requested: bool,
    static_ffmpeg_enabled: bool,
    result_json: str | Path | None,
) -> dict[str, Any]:
    processed = _mapping(response.get("processed"))
    output = _mapping(processed.get("output"))
    evidence = _mapping(output.get("media_inspection_evidence"))
    evidence_summary = _mapping(evidence.get("summary"))
    evidence_ref = _public_artifact_ref(_mapping(output.get("qc_media_inspection_evidence_artifact_ref")))
    error_message = processed.get("error_message")

    return _drop_none(
        {
            "schema": SCHEMA,
            "ok": response.get("ok") is True,
            "capability": GENERATE_MEDIA_INSPECTION_EVIDENCE,
            "status": processed.get("status"),
            "error_code": processed.get("error_code"),
            "error_message": error_message if isinstance(error_message, str) else None,
            "input": {
                "artifact_ref": _public_artifact_ref(source_ref),
                "frame_limit": frame_limit,
            },
            "p1_controls": {
                "allowed_p1_capabilities": [GENERATE_MEDIA_INSPECTION_EVIDENCE],
                "policy_opt_in": True,
                "static_ffmpeg_requested": static_ffmpeg_requested,
                "static_ffmpeg_env_enabled": static_ffmpeg_enabled,
            },
            "evidence": {
                "summary": dict(evidence_summary),
                "inspection_results": _inspection_result_summaries(evidence.get("inspection_results")),
                "warnings": evidence.get("warnings") if isinstance(evidence.get("warnings"), list) else [],
            },
            "artifacts": {
                "qc_media_inspection_evidence_artifact_ref": evidence_ref or None,
                "output_artifact_count": _artifact_count(processed),
            },
            "result_json": _result_json_summary(result_json),
            "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }
    )


def _inspection_result_summaries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        summaries.append(
            _drop_none(
                {
                    "check_id": item.get("check_id"),
                    "status": item.get("status"),
                    "severity": item.get("severity"),
                    "message": item.get("message"),
                }
            )
        )
    return summaries


def _artifact_count(processed: Mapping[str, Any]) -> int:
    artifact_refs = processed.get("artifact_refs")
    if isinstance(artifact_refs, list):
        return len(artifact_refs)
    return 0


def _result_json_summary(result_json: str | Path | None) -> dict[str, Any]:
    if result_json is None:
        return {"written": False}
    return {"written": True, "filename": Path(result_json).name}


def _write_result_json(
    result_json: str | Path,
    *,
    summary: Mapping[str, Any],
    response: Mapping[str, Any],
) -> None:
    path = Path(result_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": RESULT_SCHEMA,
        "smoke_summary": dict(summary),
        "agentctl_response": dict(response),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _drop_none(value: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, child in value.items():
        if child is None:
            continue
        if isinstance(child, dict):
            cleaned[key] = _drop_none(child)
        elif isinstance(child, list):
            cleaned[key] = [
                _drop_none(item) if isinstance(item, dict) else item
                for item in child
                if item is not None
            ]
        else:
            cleaned[key] = child
    return cleaned


def _env_truthy(value: str | None) -> bool:
    return isinstance(value, str) and value.strip().casefold() in _TRUTHY


def _error_summary(error_code: str, error_message: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "ok": False,
        "capability": GENERATE_MEDIA_INSPECTION_EVIDENCE,
        "status": "failed",
        "error_code": error_code,
        "error_message": error_message,
    }


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
