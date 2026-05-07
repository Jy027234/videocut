"""Materialize caller artifact refs into the local worker artifact store."""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from video_editing_toolkit.storage.artifacts import LocalArtifactStore, validate_artifact_id


DEFAULT_MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^sha256:[a-fA-F0-9]{64}$")
ARTIFACT_INPUT_KEYS = frozenset(
    {
        "artifact_id",
        "artifact_ids",
        "artifact_ref",
        "artifact_refs",
    }
)
NO_UPLOAD_CAPABILITIES = frozenset(
    {
        "video.project_edit.create_project",
        "video.delivery.generate_variants",
    }
)

ArtifactBytesFetcher = Callable[[str, Mapping[str, str], float, int], bytes]


@dataclass(frozen=True)
class ArtifactMaterializationConfig:
    artifact_base_url: str | None = None
    token: str | None = None
    timeout_seconds: float = 10.0
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES


@dataclass(frozen=True)
class ArtifactMaterializationSummary:
    requested_count: int
    materialized_count: int
    cached_count: int
    artifact_ids: tuple[str, ...]


class ArtifactMaterializationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        error_message: str,
        *,
        artifact_id: str | None = None,
    ) -> None:
        super().__init__(error_message)
        self.error_code = error_code
        self.error_message = error_message
        self.artifact_id = artifact_id


def materialize_artifact_refs(
    envelope: Mapping[str, Any],
    *,
    artifact_store: LocalArtifactStore,
    config: ArtifactMaterializationConfig,
    fetch_bytes: ArtifactBytesFetcher | None = None,
) -> ArtifactMaterializationSummary:
    """Download selected artifact refs and store them under their original ids."""

    refs = _selected_artifact_refs(envelope)
    if not refs:
        return ArtifactMaterializationSummary(
            requested_count=0,
            materialized_count=0,
            cached_count=0,
            artifact_ids=(),
        )

    fetcher = fetch_bytes or _fetch_url_bytes
    tenant_id = _tenant_id(envelope)
    materialized = 0
    cached = 0
    artifact_ids: list[str] = []
    for raw_ref in refs:
        artifact_id = _required_artifact_id(raw_ref)
        artifact_ids.append(artifact_id)
        _assert_tenant_allowed(raw_ref, tenant_id=tenant_id, artifact_id=artifact_id)

        expected_size = _optional_size(raw_ref.get("size_bytes"), artifact_id=artifact_id)
        expected_checksum = _optional_sha256(raw_ref.get("checksum"), artifact_id=artifact_id)
        local_path = artifact_store.open_local_path(artifact_id)
        if local_path is not None:
            _assert_local_content(
                local_path.read_bytes(),
                artifact_id=artifact_id,
                expected_size=expected_size,
                expected_checksum=expected_checksum,
            )
            cached += 1
            continue

        download_url = _download_url(raw_ref, artifact_id=artifact_id)
        resolved_url = _resolve_download_url(
            download_url,
            artifact_base_url=config.artifact_base_url,
            artifact_id=artifact_id,
        )
        content = _fetch_artifact_bytes(
            fetcher,
            resolved_url,
            config=config,
            artifact_id=artifact_id,
        )
        _assert_local_content(
            content,
            artifact_id=artifact_id,
            expected_size=expected_size,
            expected_checksum=expected_checksum,
        )
        artifact_store.put_bytes(
            content=content,
            artifact_id=artifact_id,
            artifact_type=_string_field(raw_ref, "artifact_type", "artifact"),
            owner_tenant_id=_string_field(raw_ref, "owner_tenant_id", tenant_id),
            created_by_run_id=_string_field(raw_ref, "created_by_run_id", "agentctl_input"),
            filename=_filename_from_download_url(download_url, artifact_id=artifact_id),
            mime_type=_string_field(raw_ref, "mime_type", "application/octet-stream"),
            data_class=_string_field(raw_ref, "data_class", "sensitive"),
            retention_policy=_string_field(raw_ref, "retention_policy", "short_lived"),
            access_policy=_mapping_field(raw_ref, "access_policy"),
        )
        materialized += 1

    return ArtifactMaterializationSummary(
        requested_count=len(refs),
        materialized_count=materialized,
        cached_count=cached,
        artifact_ids=tuple(artifact_ids),
    )


def _selected_artifact_refs(envelope: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    raw_refs = _top_level_artifact_refs(envelope)
    if not raw_refs:
        return ()
    input_payload = envelope.get("input")
    if not isinstance(input_payload, Mapping):
        input_payload = {}
    if envelope.get("capability") in NO_UPLOAD_CAPABILITIES and not _input_has_artifact_reference(input_payload):
        return ()

    requested_ids = set(_input_artifact_ids(input_payload))
    if requested_ids:
        return tuple(ref for ref in raw_refs if str(ref.get("artifact_id") or ref.get("ref") or "") in requested_ids)
    return tuple(raw_refs)


def _top_level_artifact_refs(envelope: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    refs: list[Mapping[str, Any]] = []
    raw_refs = envelope.get("artifact_refs")
    if isinstance(raw_refs, list):
        refs.extend(item for item in raw_refs if isinstance(item, Mapping))
    raw_ref = envelope.get("artifact_ref")
    if isinstance(raw_ref, Mapping):
        refs.append(raw_ref)
    raw_ids = envelope.get("artifact_ids")
    if isinstance(raw_ids, list):
        refs.extend(item for item in raw_ids if isinstance(item, Mapping))

    unique: dict[str, Mapping[str, Any]] = {}
    for ref in refs:
        artifact_id = str(ref.get("artifact_id") or ref.get("ref") or "")
        if artifact_id and artifact_id not in unique:
            unique[artifact_id] = ref
    return tuple(unique.values())


def _input_artifact_ids(value: Any) -> tuple[str, ...]:
    ids: list[str] = []
    if isinstance(value, Mapping):
        artifact_ref = value.get("artifact_ref")
        if isinstance(artifact_ref, str) and artifact_ref:
            ids.append(artifact_ref)
        elif isinstance(artifact_ref, Mapping):
            item = artifact_ref.get("artifact_id") or artifact_ref.get("ref")
            if isinstance(item, str) and item:
                ids.append(item)

        artifact_refs = value.get("artifact_refs")
        if isinstance(artifact_refs, list):
            for item in artifact_refs:
                if isinstance(item, str) and item:
                    ids.append(item)
                elif isinstance(item, Mapping):
                    ref_id = item.get("artifact_id") or item.get("ref")
                    if isinstance(ref_id, str) and ref_id:
                        ids.append(ref_id)

        artifact_id = value.get("artifact_id")
        if isinstance(artifact_id, str) and artifact_id:
            ids.append(artifact_id)

        artifact_ids = value.get("artifact_ids")
        if isinstance(artifact_ids, list):
            ids.extend(item for item in artifact_ids if isinstance(item, str) and item)

        for key, child in value.items():
            if str(key) not in ARTIFACT_INPUT_KEYS:
                ids.extend(_input_artifact_ids(child))
    elif isinstance(value, list):
        for child in value:
            ids.extend(_input_artifact_ids(child))
    return tuple(dict.fromkeys(ids))


def _input_has_artifact_reference(value: Any) -> bool:
    if isinstance(value, Mapping):
        if any(str(key) in ARTIFACT_INPUT_KEYS for key in value):
            return True
        return any(_input_has_artifact_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(_input_has_artifact_reference(child) for child in value)
    return False


def _required_artifact_id(raw_ref: Mapping[str, Any]) -> str:
    raw_id = raw_ref.get("artifact_id") or raw_ref.get("ref")
    if not isinstance(raw_id, str) or not raw_id:
        raise ArtifactMaterializationError(
            "artifact_id_required",
            "Artifact ref is missing artifact_id.",
        )
    try:
        return validate_artifact_id(raw_id)
    except ValueError as exc:
        raise ArtifactMaterializationError(
            "artifact_id_invalid",
            "Artifact ref contains an invalid artifact_id.",
        ) from exc


def _assert_tenant_allowed(
    raw_ref: Mapping[str, Any],
    *,
    tenant_id: str,
    artifact_id: str,
) -> None:
    owner_tenant_id = raw_ref.get("owner_tenant_id")
    if isinstance(owner_tenant_id, str) and owner_tenant_id and owner_tenant_id != tenant_id:
        raise ArtifactMaterializationError(
            "artifact_owner_tenant_mismatch",
            "Artifact ref is not authorized for this tenant.",
            artifact_id=artifact_id,
        )


def _download_url(raw_ref: Mapping[str, Any], *, artifact_id: str) -> str:
    value = raw_ref.get("download_url")
    if not isinstance(value, str) or not value.strip():
        raise ArtifactMaterializationError(
            "artifact_download_url_required",
            "Artifact ref requires a controlled download_url.",
            artifact_id=artifact_id,
        )
    return value.strip()


def _resolve_download_url(
    download_url: str,
    *,
    artifact_base_url: str | None,
    artifact_id: str,
) -> str:
    if not artifact_base_url:
        raise ArtifactMaterializationError(
            "artifact_base_url_required",
            "Artifact materialization requires an artifact_base_url.",
            artifact_id=artifact_id,
        )
    base = urllib.parse.urlparse(artifact_base_url)
    if base.scheme not in {"http", "https"} or not base.netloc:
        raise ArtifactMaterializationError(
            "artifact_base_url_invalid",
            "Artifact materialization base URL must be http or https.",
            artifact_id=artifact_id,
        )

    parsed = urllib.parse.urlparse(download_url)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc or parsed.scheme != base.scheme:
            raise ArtifactMaterializationError(
                "artifact_download_url_not_allowed",
                "Artifact download_url must be relative or same-origin.",
                artifact_id=artifact_id,
            )
        return download_url
    if not download_url.startswith("/"):
        raise ArtifactMaterializationError(
            "artifact_download_url_not_allowed",
            "Artifact download_url must be relative or same-origin.",
            artifact_id=artifact_id,
        )
    origin = f"{base.scheme}://{base.netloc}"
    return urllib.parse.urljoin(origin, download_url)


def _fetch_artifact_bytes(
    fetcher: ArtifactBytesFetcher,
    url: str,
    *,
    config: ArtifactMaterializationConfig,
    artifact_id: str,
) -> bytes:
    if config.max_artifact_bytes <= 0:
        raise ArtifactMaterializationError(
            "artifact_size_limit_invalid",
            "Artifact materialization size limit must be positive.",
            artifact_id=artifact_id,
        )
    headers = _request_headers(config.token)
    try:
        content = fetcher(url, headers, config.timeout_seconds, config.max_artifact_bytes)
    except ArtifactMaterializationError as exc:
        if exc.artifact_id is None:
            raise ArtifactMaterializationError(
                exc.error_code,
                exc.error_message,
                artifact_id=artifact_id,
            ) from exc
        raise
    except Exception as exc:
        raise ArtifactMaterializationError(
            "artifact_fetch_failed",
            "Artifact bytes could not be fetched.",
            artifact_id=artifact_id,
        ) from exc
    if len(content) > config.max_artifact_bytes:
        raise ArtifactMaterializationError(
            "artifact_size_limit_exceeded",
            "Artifact exceeds the configured materialization size limit.",
            artifact_id=artifact_id,
        )
    return content


def _fetch_url_bytes(
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_bytes: int,
) -> bytes:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = None
                if declared_size is not None and declared_size > max_bytes:
                    raise ArtifactMaterializationError(
                        "artifact_size_limit_exceeded",
                        "Artifact exceeds the configured materialization size limit.",
                    )
            content = response.read(max_bytes + 1)
    except ArtifactMaterializationError:
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ArtifactMaterializationError(
            "artifact_fetch_failed",
            "Artifact bytes could not be fetched.",
        ) from exc

    if len(content) > max_bytes:
        raise ArtifactMaterializationError(
            "artifact_size_limit_exceeded",
            "Artifact exceeds the configured materialization size limit.",
        )
    return content


def _assert_local_content(
    content: bytes,
    *,
    artifact_id: str,
    expected_size: int | None,
    expected_checksum: str | None,
) -> None:
    if expected_size is not None and len(content) != expected_size:
        raise ArtifactMaterializationError(
            "artifact_size_mismatch",
            "Artifact size does not match its artifact_ref.",
            artifact_id=artifact_id,
        )
    if expected_checksum is not None:
        actual = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if actual.lower() != expected_checksum.lower():
            raise ArtifactMaterializationError(
                "artifact_checksum_mismatch",
                "Artifact checksum does not match its artifact_ref.",
                artifact_id=artifact_id,
            )


def _optional_size(value: Any, *, artifact_id: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ArtifactMaterializationError(
            "artifact_size_invalid",
            "Artifact size_bytes must be a non-negative integer.",
            artifact_id=artifact_id,
        )
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ArtifactMaterializationError(
                "artifact_size_invalid",
                "Artifact size_bytes must be a non-negative integer.",
                artifact_id=artifact_id,
            ) from exc
        if parsed >= 0:
            return parsed
    raise ArtifactMaterializationError(
        "artifact_size_invalid",
        "Artifact size_bytes must be a non-negative integer.",
        artifact_id=artifact_id,
    )


def _optional_sha256(value: Any, *, artifact_id: str) -> str | None:
    if not isinstance(value, str) or not value or value == "sha256:unknown":
        return None
    if not SHA256_PATTERN.fullmatch(value):
        raise ArtifactMaterializationError(
            "artifact_checksum_invalid",
            "Artifact checksum must be a sha256 digest.",
            artifact_id=artifact_id,
        )
    return value


def _request_headers(token: str | None) -> Mapping[str, str]:
    headers = {"Accept": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _filename_from_download_url(download_url: str, *, artifact_id: str) -> str:
    parsed = urllib.parse.urlparse(download_url)
    name = Path(parsed.path).name
    return name or f"{artifact_id}.bin"


def _tenant_id(envelope: Mapping[str, Any]) -> str:
    policy_context = envelope.get("policy_context")
    if isinstance(policy_context, Mapping):
        tenant_id = policy_context.get("tenant_id")
        if isinstance(tenant_id, str) and tenant_id:
            return tenant_id
    tenant_id = envelope.get("tenant_id")
    if isinstance(tenant_id, str) and tenant_id:
        return tenant_id
    return "demo_tenant"


def _string_field(payload: Mapping[str, Any], key: str, default: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _mapping_field(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return dict(value) if isinstance(value, Mapping) else {}
