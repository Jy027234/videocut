"""Local resumable artifact upload contracts."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from video_editing_toolkit.storage.artifacts import ArtifactRef, LocalArtifactStore, validate_artifact_id


SHA256_PATTERN = re.compile(r"^sha256:[a-fA-F0-9]{64}$")


class ResumableUploadError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        error_message: str,
        *,
        session_id: str | None = None,
    ) -> None:
        super().__init__(error_message)
        self.error_code = error_code
        self.error_message = error_message
        self.session_id = session_id


@dataclass(frozen=True)
class ResumableUploadConfig:
    max_session_bytes: int = 512 * 1024 * 1024


class LocalResumableUploadStore:
    """Persist chunk manifests and assemble completed artifacts locally."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        artifact_store: LocalArtifactStore,
        config: ResumableUploadConfig | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.artifact_store = artifact_store
        self.config = config or ResumableUploadConfig()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def create_session(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        owner_tenant_id: str,
        created_by_run_id: str,
        filename: str,
        total_size_bytes: int | None = None,
        expected_checksum: str | None = None,
        mime_type: str | None = None,
        data_class: str = "sensitive",
        retention_policy: str = "short_lived",
        access_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.config.max_session_bytes <= 0:
            raise ResumableUploadError(
                "resumable_size_limit_invalid",
                "Resumable upload size limit must be positive.",
            )
        artifact_id = validate_artifact_id(artifact_id)
        total_size = _optional_non_negative_int(total_size_bytes, "total_size_bytes")
        if total_size is not None and total_size > self.config.max_session_bytes:
            raise ResumableUploadError(
                "resumable_size_limit_exceeded",
                "Resumable upload exceeds the configured size limit.",
            )

        session_id = f"upload_{uuid4().hex}"
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=False)
        self._payload_path(session_id).write_bytes(b"")

        manifest = {
            "session_id": session_id,
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "owner_tenant_id": owner_tenant_id,
            "created_by_run_id": created_by_run_id,
            "filename": Path(filename).name or "artifact.bin",
            "total_size_bytes": total_size,
            "expected_checksum": _optional_sha256(expected_checksum),
            "mime_type": mime_type,
            "data_class": data_class,
            "retention_policy": retention_policy,
            "access_policy": dict(access_policy or {}),
            "received_bytes": 0,
            "chunk_count": 0,
            "chunks": [],
            "completed": False,
            "artifact_ref": None,
        }
        self._write_manifest(session_id, manifest)
        return _public_manifest(manifest)

    def append_chunk(self, session_id: str, *, offset: int, content: bytes) -> dict[str, Any]:
        session_id = self._safe_session_id(session_id)
        manifest = self._read_manifest(session_id)
        _assert_open(manifest)

        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ResumableUploadError(
                "resumable_offset_invalid",
                "Chunk offset must be a non-negative integer.",
                session_id=session_id,
            )
        if offset != manifest["received_bytes"]:
            raise ResumableUploadError(
                "resumable_offset_mismatch",
                "Chunk offset does not match the current session offset.",
                session_id=session_id,
            )
        if not isinstance(content, bytes):
            raise ResumableUploadError(
                "resumable_chunk_invalid",
                "Chunk content must be bytes.",
                session_id=session_id,
            )

        next_offset = offset + len(content)
        total_size = manifest.get("total_size_bytes")
        if isinstance(total_size, int) and next_offset > total_size:
            raise ResumableUploadError(
                "resumable_size_exceeded",
                "Chunk exceeds the declared upload size.",
                session_id=session_id,
            )
        if next_offset > self.config.max_session_bytes:
            raise ResumableUploadError(
                "resumable_size_limit_exceeded",
                "Resumable upload exceeds the configured size limit.",
                session_id=session_id,
            )

        with self._payload_path(session_id).open("ab") as handle:
            handle.write(content)

        chunk = {
            "offset": offset,
            "size_bytes": len(content),
            "checksum": f"sha256:{hashlib.sha256(content).hexdigest()}",
        }
        manifest["chunks"].append(chunk)
        manifest["chunk_count"] = int(manifest["chunk_count"]) + 1
        manifest["received_bytes"] = next_offset
        self._write_manifest(session_id, manifest)
        return _public_manifest(manifest)

    def complete(self, session_id: str) -> ArtifactRef:
        session_id = self._safe_session_id(session_id)
        manifest = self._read_manifest(session_id)
        _assert_open(manifest)

        received_bytes = int(manifest["received_bytes"])
        total_size = manifest.get("total_size_bytes")
        if isinstance(total_size, int) and received_bytes != total_size:
            raise ResumableUploadError(
                "resumable_size_incomplete",
                "Resumable upload has not received the declared byte count.",
                session_id=session_id,
            )

        content = self._payload_path(session_id).read_bytes()
        actual_checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
        expected_checksum = manifest.get("expected_checksum")
        if isinstance(expected_checksum, str) and expected_checksum.lower() != actual_checksum.lower():
            raise ResumableUploadError(
                "resumable_checksum_mismatch",
                "Completed upload checksum does not match the session manifest.",
                session_id=session_id,
            )

        ref = self.artifact_store.put_bytes(
            content=content,
            artifact_id=str(manifest["artifact_id"]),
            artifact_type=str(manifest["artifact_type"]),
            owner_tenant_id=str(manifest["owner_tenant_id"]),
            created_by_run_id=str(manifest["created_by_run_id"]),
            filename=str(manifest["filename"]),
            mime_type=manifest.get("mime_type") if isinstance(manifest.get("mime_type"), str) else None,
            data_class=str(manifest["data_class"]),
            retention_policy=str(manifest["retention_policy"]),
            access_policy=dict(manifest["access_policy"]) if isinstance(manifest["access_policy"], dict) else {},
        )
        manifest["completed"] = True
        manifest["final_checksum"] = actual_checksum
        manifest["artifact_ref"] = ref.to_public_dict()
        self._write_manifest(session_id, manifest)
        return ref

    def load_manifest(self, session_id: str) -> dict[str, Any]:
        return _public_manifest(self._read_manifest(self._safe_session_id(session_id)))

    def _session_dir(self, session_id: str) -> Path:
        safe_id = self._safe_session_id(session_id)
        root = self.root_dir.resolve()
        session_dir = (root / safe_id).resolve()
        if session_dir.parent != root:
            raise ResumableUploadError("resumable_session_invalid", "Resumable upload session is invalid.")
        return session_dir

    def _manifest_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "manifest.json"

    def _payload_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "payload.bin"

    def _read_manifest(self, session_id: str) -> dict[str, Any]:
        path = self._manifest_path(session_id)
        if not path.exists():
            raise ResumableUploadError(
                "resumable_session_not_found",
                "Resumable upload session was not found.",
                session_id=session_id,
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ResumableUploadError(
                "resumable_manifest_invalid",
                "Resumable upload manifest is invalid.",
                session_id=session_id,
            ) from exc
        if not isinstance(payload, dict):
            raise ResumableUploadError(
                "resumable_manifest_invalid",
                "Resumable upload manifest is invalid.",
                session_id=session_id,
            )
        return payload

    def _write_manifest(self, session_id: str, manifest: dict[str, Any]) -> None:
        self._manifest_path(session_id).write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _safe_session_id(self, session_id: str) -> str:
        try:
            return validate_artifact_id(session_id)
        except ValueError as exc:
            raise ResumableUploadError(
                "resumable_session_invalid",
                "Resumable upload session is invalid.",
            ) from exc


def _assert_open(manifest: dict[str, Any]) -> None:
    if manifest.get("completed") is True:
        raise ResumableUploadError(
            "resumable_session_completed",
            "Resumable upload session is already completed.",
            session_id=str(manifest.get("session_id") or ""),
        )


def _public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(manifest)


def _optional_non_negative_int(value: int | None, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResumableUploadError(
            "resumable_size_invalid",
            f"{name} must be a non-negative integer.",
        )
    return value


def _optional_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if re.fullmatch(r"[a-f0-9]{64}", normalized):
        normalized = f"sha256:{normalized}"
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ResumableUploadError(
            "resumable_checksum_invalid",
            "Expected checksum must be a sha256 digest.",
        )
    return normalized
