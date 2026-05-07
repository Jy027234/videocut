from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import extract_service_token, get_current_user, get_service_actor
from ..models import AuditLog, ToolkitArtifact
from ..rbac import has_permission
from ..schemas import ToolkitArtifactCreateRequest, ToolkitArtifactRef, ToolkitArtifactResponse

router = APIRouter(prefix="/toolkit-artifacts", tags=["Toolkit Artifacts"])


@dataclass(frozen=True)
class ArtifactActor:
    tenant_id: str
    actor_type: str
    actor_id: str
    scopes: tuple[str, ...]


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _scope_allowed(scopes: list[str] | tuple[str, ...], required: str) -> bool:
    return (
        has_permission(scopes, required)
        or has_permission(scopes, "toolkit.*")
        or has_permission(scopes, "agentctl.*")
    )


def _resolve_actor(
    request: Request,
    db: Session,
    *,
    authorization: str | None,
    x_service_token: str | None,
    required_scope: str,
) -> ArtifactActor:
    if extract_service_token(authorization, x_service_token):
        actor = get_service_actor(db, authorization=authorization, x_service_token=x_service_token)
        scopes = tuple(actor.scopes)
        if not _scope_allowed(scopes, required_scope):
            raise HTTPException(status_code=403, detail=f"Service token missing {required_scope}")
        return ArtifactActor(
            tenant_id=actor.service_account.tenant_id,
            actor_type="service_account",
            actor_id=actor.service_account.id,
            scopes=scopes,
        )

    current = get_current_user(request=request, db=db, authorization=authorization)
    if not has_permission(current.permissions, required_scope):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {required_scope}",
        )
    return ArtifactActor(
        tenant_id=current.tenant.id,
        actor_type="user",
        actor_id=current.user.id,
        scopes=tuple(current.permissions),
    )


def _decode_content(body: ToolkitArtifactCreateRequest, *, max_bytes: int) -> bytes | None:
    if body.content_base64 is None:
        return None
    try:
        content = base64.b64decode(body.content_base64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="content_base64 must be valid base64") from exc
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail="Toolkit artifact exceeds inline byte limit",
        )
    return content


def _checksum(content: bytes | None) -> str | None:
    if content is None:
        return None
    return hashlib.sha256(content).hexdigest()


def _safe_file_name(value: str | None) -> str | None:
    if not value:
        return None
    name = PurePath(value.replace("\\", "/")).name.strip()
    return name[:255] or None


def _artifact_ref(row: ToolkitArtifact) -> ToolkitArtifactRef:
    return ToolkitArtifactRef(
        artifact_id=row.id,
        artifact_type=row.artifact_type,
        owner_tenant_id=row.tenant_id,
        created_by_run_id=row.run_id or "platform_core",
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        checksum=f"sha256:{row.checksum_sha256}" if row.checksum_sha256 else "sha256:unknown",
        data_class=row.data_class,
        retention_policy=row.retention_policy,
        access_policy=row.access_policy_json or {},
        download_url=f"/toolkit-artifacts/{row.id}/bytes",
        expires_at=row.expires_at,
    )


def _artifact_response(row: ToolkitArtifact) -> ToolkitArtifactResponse:
    ref = _artifact_ref(row)
    return ToolkitArtifactResponse(
        artifact_id=row.id,
        tenant_id=row.tenant_id,
        owner_type=row.owner_type,
        owner_id=row.owner_id,
        toolkit_id=row.toolkit_id,
        capability=row.capability,
        artifact_type=row.artifact_type,
        file_name=row.file_name,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        checksum=ref.checksum,
        data_class=row.data_class,
        retention_policy=row.retention_policy,
        access_policy=row.access_policy_json or {},
        storage_kind=row.storage_kind,
        status=row.status,
        expires_at=row.expires_at,
        run_id=row.run_id,
        trace_id=row.trace_id,
        metadata=row.metadata_json or {},
        artifact_ref=ref,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _get_authorized_artifact(
    db: Session,
    artifact_id: str,
    actor: ArtifactActor,
) -> ToolkitArtifact:
    row = db.get(ToolkitArtifact, artifact_id)
    if row is None or row.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=404, detail="Toolkit artifact not found")
    if row.expires_at is not None and _aware(row.expires_at) <= _now():
        raise HTTPException(status_code=404, detail="Toolkit artifact not found")
    if row.status != "ready":
        raise HTTPException(status_code=409, detail="Toolkit artifact is not ready")
    return row


def _audit_create(request: Request, db: Session, row: ToolkitArtifact, actor: ArtifactActor) -> None:
    db.add(
        AuditLog(
            tenant_id=row.tenant_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            app_id="platform_core",
            action="toolkit_artifact.created",
            resource_type="toolkit_artifact",
            resource_id=row.id,
            metadata_json={
                "toolkit_id": row.toolkit_id,
                "capability": row.capability,
                "artifact_type": row.artifact_type,
                "size_bytes": row.size_bytes,
                "storage_kind": row.storage_kind,
                "trace_id": row.trace_id,
            },
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )


@router.post("", response_model=ToolkitArtifactResponse, status_code=201)
def create_toolkit_artifact(
    body: ToolkitArtifactCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
):
    actor = _resolve_actor(
        request,
        db,
        authorization=authorization,
        x_service_token=x_service_token,
        required_scope="toolkit.artifacts.write",
    )
    if body.tenant_id is not None and body.tenant_id != actor.tenant_id:
        raise HTTPException(status_code=403, detail="Toolkit artifact tenant mismatch")
    content = _decode_content(
        body,
        max_bytes=request.app.state.settings.toolkit_artifact_inline_max_bytes,
    )
    row = ToolkitArtifact(
        tenant_id=actor.tenant_id,
        owner_type=actor.actor_type,
        owner_id=actor.actor_id,
        toolkit_id=body.toolkit_id,
        capability=body.capability,
        artifact_type=body.artifact_type,
        file_name=_safe_file_name(body.file_name),
        mime_type=body.mime_type,
        size_bytes=len(content or b""),
        checksum_sha256=_checksum(content),
        data_class=body.data_class,
        retention_policy=body.retention_policy,
        access_policy_json=body.access_policy,
        storage_kind="inline" if content is not None else "metadata",
        content_bytes=content,
        status="ready",
        expires_at=body.expires_at,
        run_id=body.run_id,
        trace_id=body.trace_id,
        metadata_json=body.metadata,
    )
    db.add(row)
    db.flush()
    _audit_create(request, db, row, actor)
    db.commit()
    db.refresh(row)
    return _artifact_response(row)


@router.get("", response_model=list[ToolkitArtifactResponse])
def list_toolkit_artifacts(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
    toolkit_id: str | None = None,
    trace_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    actor = _resolve_actor(
        request,
        db,
        authorization=authorization,
        x_service_token=x_service_token,
        required_scope="toolkit.artifacts.read",
    )
    now = _now()
    query = db.query(ToolkitArtifact).filter(
        ToolkitArtifact.tenant_id == actor.tenant_id,
        or_(ToolkitArtifact.expires_at.is_(None), ToolkitArtifact.expires_at > now),
    )
    if toolkit_id:
        query = query.filter(ToolkitArtifact.toolkit_id == toolkit_id)
    if trace_id:
        query = query.filter(ToolkitArtifact.trace_id == trace_id)
    rows = query.order_by(ToolkitArtifact.created_at.desc()).limit(limit).all()
    return [_artifact_response(row) for row in rows]


@router.get("/{artifact_id}", response_model=ToolkitArtifactResponse)
def get_toolkit_artifact(
    artifact_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
):
    actor = _resolve_actor(
        request,
        db,
        authorization=authorization,
        x_service_token=x_service_token,
        required_scope="toolkit.artifacts.read",
    )
    return _artifact_response(_get_authorized_artifact(db, artifact_id, actor))


@router.get("/{artifact_id}/bytes")
def get_toolkit_artifact_bytes(
    artifact_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
):
    actor = _resolve_actor(
        request,
        db,
        authorization=authorization,
        x_service_token=x_service_token,
        required_scope="toolkit.artifacts.read",
    )
    row = _get_authorized_artifact(db, artifact_id, actor)
    if row.content_bytes is None:
        raise HTTPException(status_code=409, detail="Toolkit artifact bytes are not available")
    headers: dict[str, str] = {
        "Content-Length": str(row.size_bytes),
        "X-Artifact-Id": row.id,
        "X-Artifact-Checksum": f"sha256:{row.checksum_sha256}" if row.checksum_sha256 else "sha256:unknown",
    }
    if row.file_name:
        headers["Content-Disposition"] = f'attachment; filename="{row.file_name.replace(chr(34), "")}"'
    return Response(content=row.content_bytes, media_type=row.mime_type, headers=headers)
