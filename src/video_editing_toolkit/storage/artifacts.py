"""Artifact reference contract and local artifact store."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from video_editing_toolkit.storage.signed_urls import create_signed_artifact_token, sign_download_url


ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ARTIFACT_MANIFEST_FILENAME = "artifact_manifest.json"
RETENTION_POLICY_TTL_SECONDS: dict[str, int | None] = {
    "none": 0,
    "ephemeral": 0,
    "short_lived": 7 * 24 * 60 * 60,
    "temporary": 7 * 24 * 60 * 60,
    "long_lived": None,
    "permanent": None,
}


def validate_artifact_id(artifact_id: str) -> str:
    """Validate an artifact id before using it as a local directory name."""

    if not isinstance(artifact_id, str) or not ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
        raise ValueError("artifact_id must be 1-128 safe characters: A-Z, a-z, 0-9, _, ., -.")
    return artifact_id


@dataclass(slots=True)
class ArtifactRef:
    artifact_id: str
    artifact_type: str
    owner_tenant_id: str
    created_by_run_id: str
    storage_uri: str
    mime_type: str
    size_bytes: int
    checksum: str
    data_class: str = "sensitive"
    retention_policy: str = "short_lived"
    expires_at: datetime | None = None
    access_policy: dict[str, Any] = field(default_factory=dict)
    download_url: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Return a caller-safe artifact reference without storage internals."""

        payload: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "data_class": self.data_class,
            "retention_policy": self.retention_policy,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "access_policy": deepcopy(self.access_policy),
        }
        if self.download_url is not None:
            payload["download_url"] = self.download_url
        return payload


@dataclass(frozen=True, slots=True)
class ArtifactMetadataSummary:
    artifact_id: str
    artifact_type: str
    mime_type: str
    size_bytes: int
    checksum: str
    data_class: str
    retention_policy: str
    created_at: datetime | None = None
    expires_at: datetime | None = None
    access_policy: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        """Return caller-safe artifact metadata without local storage details."""

        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "data_class": self.data_class,
            "retention_policy": self.retention_policy,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "access_policy": deepcopy(self.access_policy),
        }


@dataclass(frozen=True, slots=True)
class ArtifactCleanupSummary:
    deleted_count: int
    skipped_count: int
    deleted_artifact_ids: tuple[str, ...] = ()
    skipped_artifact_ids: tuple[str, ...] = ()
    invalid_artifact_ids: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, Any]:
        """Return caller-safe cleanup results without filesystem paths."""

        return {
            "deleted_count": self.deleted_count,
            "skipped_count": self.skipped_count,
            "deleted_artifact_ids": list(self.deleted_artifact_ids),
            "skipped_artifact_ids": list(self.skipped_artifact_ids),
            "invalid_artifact_ids": list(self.invalid_artifact_ids),
        }


class LocalArtifactStore:
    """Stores artifacts on local disk while exposing only controlled refs."""

    def __init__(
        self,
        root_dir: str | Path,
        *,
        public_base_path: str = "/local/artifacts",
        signing_secret: str | bytes | None = None,
        signed_url_ttl_seconds: int = 60 * 60,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.public_base_path = public_base_path.rstrip("/")
        self.signing_secret = signing_secret
        self.signed_url_ttl_seconds = signed_url_ttl_seconds
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(
        self,
        *,
        content: bytes,
        artifact_type: str,
        owner_tenant_id: str,
        created_by_run_id: str,
        filename: str,
        artifact_id: str | None = None,
        mime_type: str | None = None,
        data_class: str = "sensitive",
        retention_policy: str = "short_lived",
        ttl_seconds: int | None = 7 * 24 * 60 * 60,
        access_policy: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        artifact_id = validate_artifact_id(artifact_id) if artifact_id is not None else f"artifact_{uuid4().hex}"
        artifact_dir = self._artifact_dir(artifact_id)
        artifact_dir.mkdir(parents=True, exist_ok=False)

        safe_name = Path(filename).name or "artifact.bin"
        artifact_path = artifact_dir / safe_name
        artifact_path.write_bytes(content)
        return self._build_ref(
            artifact_id=artifact_id,
            artifact_path=artifact_path,
            artifact_type=artifact_type,
            owner_tenant_id=owner_tenant_id,
            created_by_run_id=created_by_run_id,
            mime_type=mime_type,
            data_class=data_class,
            retention_policy=retention_policy,
            ttl_seconds=ttl_seconds,
            access_policy=access_policy,
        )

    def put_file(
        self,
        *,
        source_path: str | Path,
        artifact_type: str,
        owner_tenant_id: str,
        created_by_run_id: str,
        filename: str | None = None,
        artifact_id: str | None = None,
        mime_type: str | None = None,
        data_class: str = "sensitive",
        retention_policy: str = "short_lived",
        ttl_seconds: int | None = 7 * 24 * 60 * 60,
        access_policy: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        artifact_id = validate_artifact_id(artifact_id) if artifact_id is not None else f"artifact_{uuid4().hex}"
        artifact_dir = self._artifact_dir(artifact_id)
        artifact_dir.mkdir(parents=True, exist_ok=False)

        source = Path(source_path)
        safe_name = Path(filename or source.name).name or "artifact.bin"
        artifact_path = artifact_dir / safe_name
        shutil.copy2(source, artifact_path)
        return self._build_ref(
            artifact_id=artifact_id,
            artifact_path=artifact_path,
            artifact_type=artifact_type,
            owner_tenant_id=owner_tenant_id,
            created_by_run_id=created_by_run_id,
            mime_type=mime_type,
            data_class=data_class,
            retention_policy=retention_policy,
            ttl_seconds=ttl_seconds,
            access_policy=access_policy,
        )

    def open_local_path(self, artifact_id: str) -> Path | None:
        try:
            artifact_dir = self._artifact_dir(artifact_id)
        except ValueError:
            return None
        if not artifact_dir.exists():
            return None
        files = [
            path
            for path in artifact_dir.iterdir()
            if path.is_file() and path.name != ARTIFACT_MANIFEST_FILENAME
        ]
        return files[0] if files else None

    def delete(self, artifact_id: str) -> bool:
        try:
            artifact_dir = self._artifact_dir(artifact_id)
        except ValueError:
            return False
        if not artifact_dir.exists():
            return False
        shutil.rmtree(artifact_dir)
        return True

    def list_metadata_summaries(self) -> list[ArtifactMetadataSummary]:
        """List caller-safe metadata summaries for valid local artifacts."""

        summaries: list[ArtifactMetadataSummary] = []
        for artifact_dir in self._iter_artifact_dirs():
            try:
                summary = self._summary_from_dir(artifact_dir)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if summary is not None:
                summaries.append(summary)
        return sorted(summaries, key=lambda item: item.artifact_id)

    def list_metadata_summary_dicts(self) -> list[dict[str, Any]]:
        """List caller-safe artifact metadata dictionaries."""

        return [summary.to_public_dict() for summary in self.list_metadata_summaries()]

    def cleanup_expired(
        self,
        *,
        now: datetime | None = None,
        retention_policy_ttl_seconds: dict[str, int | None] | None = None,
    ) -> ArtifactCleanupSummary:
        """Delete artifacts expired by expires_at or retention policy age."""

        current_time = _ensure_utc(now or datetime.now(timezone.utc))
        policy_ttls = RETENTION_POLICY_TTL_SECONDS | (retention_policy_ttl_seconds or {})
        deleted: list[str] = []
        skipped: list[str] = []
        invalid: list[str] = []

        for artifact_dir in self._iter_artifact_dirs():
            artifact_id = artifact_dir.name
            try:
                validate_artifact_id(artifact_id)
                summary = self._summary_from_dir(artifact_dir)
            except (OSError, ValueError, json.JSONDecodeError):
                invalid.append(_safe_public_artifact_label(artifact_id))
                continue

            if summary is None:
                invalid.append(_safe_public_artifact_label(artifact_id))
                continue

            if self._is_summary_expired(
                summary,
                now=current_time,
                retention_policy_ttl_seconds=policy_ttls,
            ):
                if self.delete(summary.artifact_id):
                    deleted.append(summary.artifact_id)
                else:
                    skipped.append(summary.artifact_id)
            else:
                skipped.append(summary.artifact_id)

        return ArtifactCleanupSummary(
            deleted_count=len(deleted),
            skipped_count=len(skipped),
            deleted_artifact_ids=tuple(deleted),
            skipped_artifact_ids=tuple(skipped),
            invalid_artifact_ids=tuple(invalid),
        )

    def build_signed_download_token(
        self,
        ref: ArtifactRef,
        *,
        secret: str | bytes | None = None,
        ttl_seconds: int | None = None,
        scope: str = "read",
    ) -> str:
        signing_secret = secret if secret is not None else self.signing_secret
        return create_signed_artifact_token(
            artifact_id=ref.artifact_id,
            checksum=ref.checksum,
            secret=signing_secret or b"",
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.signed_url_ttl_seconds,
            scope=scope,
        )

    def build_signed_download_url(
        self,
        ref: ArtifactRef,
        *,
        secret: str | bytes | None = None,
        ttl_seconds: int | None = None,
        scope: str = "read",
    ) -> str:
        signing_secret = secret if secret is not None else self.signing_secret
        return sign_download_url(
            ref.download_url or f"{self.public_base_path}/{ref.artifact_id}",
            artifact_id=ref.artifact_id,
            checksum=ref.checksum,
            secret=signing_secret or b"",
            ttl_seconds=ttl_seconds if ttl_seconds is not None else self.signed_url_ttl_seconds,
            scope=scope,
        )

    def _artifact_dir(self, artifact_id: str) -> Path:
        safe_id = validate_artifact_id(artifact_id)
        root = self.root_dir.resolve()
        artifact_dir = (root / safe_id).resolve()
        if artifact_dir.parent != root:
            raise ValueError("artifact_id resolves outside the artifact store.")
        return artifact_dir

    def _iter_artifact_dirs(self) -> Iterable[Path]:
        if not self.root_dir.exists():
            return ()
        return (path for path in self.root_dir.iterdir() if path.is_dir())

    def _build_ref(
        self,
        *,
        artifact_id: str,
        artifact_path: Path,
        artifact_type: str,
        owner_tenant_id: str,
        created_by_run_id: str,
        mime_type: str | None,
        data_class: str,
        retention_policy: str,
        ttl_seconds: int | None,
        access_policy: dict[str, Any] | None,
    ) -> ArtifactRef:
        content = artifact_path.read_bytes()
        expires_at = None
        if ttl_seconds is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
        download_url = f"{self.public_base_path}/{artifact_id}"
        if self.signing_secret is not None:
            download_url = sign_download_url(
                download_url,
                artifact_id=artifact_id,
                checksum=checksum,
                secret=self.signing_secret,
                ttl_seconds=self.signed_url_ttl_seconds,
            )

        ref = ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            owner_tenant_id=owner_tenant_id,
            created_by_run_id=created_by_run_id,
            storage_uri=f"local-artifact://{artifact_id}/{artifact_path.name}",
            mime_type=mime_type or mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream",
            size_bytes=len(content),
            checksum=checksum,
            data_class=data_class,
            retention_policy=retention_policy,
            expires_at=expires_at,
            access_policy=access_policy or {},
            download_url=download_url,
        )
        self._write_artifact_manifest(
            artifact_path.parent,
            ref=ref,
            created_at=datetime.now(timezone.utc),
        )
        return ref

    def _write_artifact_manifest(
        self,
        artifact_dir: Path,
        *,
        ref: ArtifactRef,
        created_at: datetime,
    ) -> None:
        manifest = ArtifactMetadataSummary(
            artifact_id=ref.artifact_id,
            artifact_type=ref.artifact_type,
            mime_type=ref.mime_type,
            size_bytes=ref.size_bytes,
            checksum=ref.checksum,
            data_class=ref.data_class,
            retention_policy=ref.retention_policy,
            created_at=created_at,
            expires_at=ref.expires_at,
            access_policy=ref.access_policy,
        ).to_public_dict()
        (artifact_dir / ARTIFACT_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _summary_from_dir(self, artifact_dir: Path) -> ArtifactMetadataSummary | None:
        artifact_id = validate_artifact_id(artifact_dir.name)
        artifact_dir = self._artifact_dir(artifact_id)
        manifest_path = artifact_dir / ARTIFACT_MANIFEST_FILENAME
        if manifest_path.exists():
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Artifact manifest must be a JSON object.")
            return _summary_from_manifest(raw, expected_artifact_id=artifact_id)

        artifact_path = self.open_local_path(artifact_id)
        if artifact_path is None:
            return None
        content = artifact_path.read_bytes()
        return ArtifactMetadataSummary(
            artifact_id=artifact_id,
            artifact_type="artifact",
            mime_type=mimetypes.guess_type(artifact_path.name)[0] or "application/octet-stream",
            size_bytes=len(content),
            checksum=f"sha256:{hashlib.sha256(content).hexdigest()}",
            data_class="sensitive",
            retention_policy="short_lived",
            created_at=_ensure_utc(datetime.fromtimestamp(artifact_dir.stat().st_mtime, timezone.utc)),
            expires_at=None,
            access_policy={},
        )

    @staticmethod
    def _is_summary_expired(
        summary: ArtifactMetadataSummary,
        *,
        now: datetime,
        retention_policy_ttl_seconds: dict[str, int | None],
    ) -> bool:
        if summary.expires_at is not None and summary.expires_at <= now:
            return True
        ttl_seconds = retention_policy_ttl_seconds.get(summary.retention_policy)
        if ttl_seconds is None or summary.created_at is None:
            return False
        return summary.created_at + timedelta(seconds=ttl_seconds) <= now


def _summary_from_manifest(raw: dict[str, Any], *, expected_artifact_id: str) -> ArtifactMetadataSummary:
    artifact_id = validate_artifact_id(_required_string(raw, "artifact_id"))
    if artifact_id != expected_artifact_id:
        raise ValueError("Artifact manifest id does not match artifact directory.")
    return ArtifactMetadataSummary(
        artifact_id=artifact_id,
        artifact_type=_required_string(raw, "artifact_type"),
        mime_type=_required_string(raw, "mime_type"),
        size_bytes=_required_int(raw, "size_bytes"),
        checksum=_required_string(raw, "checksum"),
        data_class=_required_string(raw, "data_class"),
        retention_policy=_required_string(raw, "retention_policy"),
        created_at=_optional_datetime(raw.get("created_at")),
        expires_at=_optional_datetime(raw.get("expires_at")),
        access_policy=deepcopy(raw.get("access_policy")) if isinstance(raw.get("access_policy"), dict) else {},
    )


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Artifact manifest field {key} must be a non-empty string.")
    return value


def _required_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"Artifact manifest field {key} must be a non-negative integer.")
    return value


def _optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Artifact manifest datetime fields must be strings or null.")
    return _ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_public_artifact_label(value: str) -> str:
    return value if ARTIFACT_ID_PATTERN.fullmatch(value) else "<invalid>"
