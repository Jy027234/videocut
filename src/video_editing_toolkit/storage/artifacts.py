"""Artifact reference contract and local artifact store."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from video_editing_toolkit.storage.signed_urls import create_signed_artifact_token, sign_download_url


ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


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
        files = [path for path in artifact_dir.iterdir() if path.is_file()]
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

        return ArtifactRef(
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
