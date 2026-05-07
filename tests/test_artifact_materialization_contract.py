"""P0.11 artifact materialization contract tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

import pytest

from video_editing_toolkit.storage import (
    ArtifactMaterializationConfig,
    ArtifactMaterializationError,
    LocalArtifactStore,
    materialize_artifact_refs,
)


def test_local_artifact_store_preserves_safe_artifact_id_and_rejects_traversal(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")

    ref = store.put_bytes(
        content=b"input media bytes",
        artifact_id="artifact_platform_001",
        artifact_type="source_video",
        owner_tenant_id="tenant_materialize",
        created_by_run_id="run_materialize",
        filename="input.mp4",
        mime_type="video/mp4",
    )

    assert ref.artifact_id == "artifact_platform_001"
    assert store.open_local_path("artifact_platform_001") is not None
    assert store.open_local_path("../escape") is None
    assert store.delete("../escape") is False

    with pytest.raises(ValueError):
        store.put_bytes(
            content=b"escape",
            artifact_id="../escape",
            artifact_type="source_video",
            owner_tenant_id="tenant_materialize",
            created_by_run_id="run_materialize",
            filename="escape.mp4",
            mime_type="video/mp4",
        )


def test_materialize_artifact_refs_downloads_relative_url_and_keeps_artifact_id(tmp_path: Path) -> None:
    content = b"platform artifact bytes"
    artifact_id = "artifact_platform_video"
    fetcher = FakeArtifactFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": content,
        }
    )
    store = LocalArtifactStore(tmp_path / "artifacts")

    summary = materialize_artifact_refs(
        _envelope(content=content, artifact_id=artifact_id),
        artifact_store=store,
        config=ArtifactMaterializationConfig(
            artifact_base_url="http://platform.local",
            token="worker-token",
            max_artifact_bytes=1024,
        ),
        fetch_bytes=fetcher,
    )

    local_path = store.open_local_path(artifact_id)
    assert summary.requested_count == 1
    assert summary.materialized_count == 1
    assert summary.cached_count == 0
    assert summary.artifact_ids == (artifact_id,)
    assert local_path is not None
    assert local_path.read_bytes() == content
    assert fetcher.requests == [
        {
            "url": "http://platform.local/artifacts/download/input.mp4",
            "headers": {
                "Accept": "application/octet-stream",
                "Authorization": "Bearer worker-token",
            },
            "timeout_seconds": 10.0,
            "max_bytes": 1024,
        }
    ]


def test_materialize_artifact_refs_reuses_cached_content_after_verification(tmp_path: Path) -> None:
    content = b"cached platform bytes"
    artifact_id = "artifact_cached_video"
    store = LocalArtifactStore(tmp_path / "artifacts")
    store.put_bytes(
        content=content,
        artifact_id=artifact_id,
        artifact_type="source_video",
        owner_tenant_id="tenant_materialize",
        created_by_run_id="run_source",
        filename="cached.mp4",
        mime_type="video/mp4",
    )
    fetcher = FakeArtifactFetcher({})

    summary = materialize_artifact_refs(
        _envelope(content=content, artifact_id=artifact_id),
        artifact_store=store,
        config=ArtifactMaterializationConfig(artifact_base_url="http://platform.local"),
        fetch_bytes=fetcher,
    )

    assert summary.materialized_count == 0
    assert summary.cached_count == 1
    assert fetcher.requests == []


def test_materialize_artifact_refs_rejects_off_origin_download_url(tmp_path: Path) -> None:
    content = b"platform artifact bytes"
    fetcher = FakeArtifactFetcher({})
    envelope = _envelope(
        content=content,
        artifact_id="artifact_off_origin",
        download_url="http://169.254.169.254/latest/meta-data",
    )

    with pytest.raises(ArtifactMaterializationError) as exc_info:
        materialize_artifact_refs(
            envelope,
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            config=ArtifactMaterializationConfig(artifact_base_url="http://platform.local"),
            fetch_bytes=fetcher,
        )

    assert exc_info.value.error_code == "artifact_download_url_not_allowed"
    assert exc_info.value.artifact_id == "artifact_off_origin"
    assert "169.254" not in str(exc_info.value)
    assert fetcher.requests == []


def test_materialize_artifact_refs_rejects_checksum_mismatch(tmp_path: Path) -> None:
    expected = b"expected-bytes"
    fetched = b"mismatch-bytes"
    fetcher = FakeArtifactFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": fetched,
        }
    )

    with pytest.raises(ArtifactMaterializationError) as exc_info:
        materialize_artifact_refs(
            _envelope(content=expected, artifact_id="artifact_checksum_mismatch"),
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            config=ArtifactMaterializationConfig(
                artifact_base_url="http://platform.local",
                max_artifact_bytes=1024,
            ),
            fetch_bytes=fetcher,
        )

    assert exc_info.value.error_code == "artifact_checksum_mismatch"
    assert exc_info.value.artifact_id == "artifact_checksum_mismatch"


def test_materialize_artifact_refs_enforces_max_size_after_fetch(tmp_path: Path) -> None:
    content = b"too-large"
    fetcher = FakeArtifactFetcher(
        {
            "http://platform.local/artifacts/download/input.mp4": content,
        }
    )

    with pytest.raises(ArtifactMaterializationError) as exc_info:
        materialize_artifact_refs(
            _envelope(content=content, artifact_id="artifact_too_large"),
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            config=ArtifactMaterializationConfig(
                artifact_base_url="http://platform.local",
                max_artifact_bytes=3,
            ),
            fetch_bytes=fetcher,
        )

    assert exc_info.value.error_code == "artifact_size_limit_exceeded"
    assert exc_info.value.artifact_id == "artifact_too_large"


class FakeArtifactFetcher:
    def __init__(self, responses: Mapping[str, bytes]) -> None:
        self.responses = dict(responses)
        self.requests: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_bytes: int,
    ) -> bytes:
        self.requests.append(
            {
                "url": url,
                "headers": dict(headers),
                "timeout_seconds": timeout_seconds,
                "max_bytes": max_bytes,
            }
        )
        return self.responses[url]


def _envelope(
    *,
    content: bytes,
    artifact_id: str,
    download_url: str = "/artifacts/download/input.mp4",
) -> dict[str, Any]:
    return {
        "toolkit_id": "video-editing-toolkit",
        "capability": "video.asset_ingest.build_asset_index",
        "input": {
            "project_id": "proj_materialize",
            "artifact_ids": [artifact_id],
        },
        "artifact_refs": [
            {
                "artifact_id": artifact_id,
                "artifact_type": "source_video",
                "owner_tenant_id": "tenant_materialize",
                "created_by_run_id": "run_source",
                "mime_type": "video/mp4",
                "size_bytes": len(content),
                "checksum": f"sha256:{hashlib.sha256(content).hexdigest()}",
                "data_class": "sensitive",
                "retention_policy": "short_lived",
                "download_url": download_url,
            }
        ],
        "policy_context": {
            "tenant_id": "tenant_materialize",
            "user_id": "worker_materialize",
        },
    }
