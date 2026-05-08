"""P1.8 local artifact lifecycle cleanup contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.storage import LocalArtifactStore


def _put_artifact(
    store: LocalArtifactStore,
    *,
    artifact_id: str,
    ttl_seconds: int | None,
    retention_policy: str = "short_lived",
) -> None:
    store.put_bytes(
        content=b"artifact-bytes",
        artifact_id=artifact_id,
        artifact_type="analysis_json",
        owner_tenant_id="tenant_test",
        created_by_run_id="run_test",
        filename="result.json",
        mime_type="application/json",
        retention_policy=retention_policy,
        ttl_seconds=ttl_seconds,
        access_policy={"scope": "read"},
    )


def test_cleanup_keeps_unexpired_artifacts(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    _put_artifact(store, artifact_id="artifact_active", ttl_seconds=60 * 60)

    summary = store.cleanup_expired(now=datetime.now(timezone.utc))

    assert summary.deleted_count == 0
    assert summary.skipped_count == 1
    assert summary.skipped_artifact_ids == ("artifact_active",)
    assert store.open_local_path("artifact_active") is not None
    assert_no_public_path_or_command_leak(summary.to_public_dict())


def test_cleanup_deletes_expired_artifacts_by_expires_at(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    _put_artifact(store, artifact_id="artifact_expired", ttl_seconds=-1)

    summary = store.cleanup_expired(now=datetime.now(timezone.utc))

    assert summary.deleted_count == 1
    assert summary.deleted_artifact_ids == ("artifact_expired",)
    assert store.open_local_path("artifact_expired") is None
    assert_no_public_path_or_command_leak(summary.to_public_dict())


def test_cleanup_deletes_artifacts_by_retention_policy_age(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    _put_artifact(
        store,
        artifact_id="artifact_retention_expired",
        ttl_seconds=None,
        retention_policy="ephemeral",
    )

    summary = store.cleanup_expired(now=datetime.now(timezone.utc))

    assert summary.deleted_count == 1
    assert summary.deleted_artifact_ids == ("artifact_retention_expired",)
    assert store.open_local_path("artifact_retention_expired") is None


def test_cleanup_handles_invalid_artifact_id_safely(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    (tmp_path / "artifacts" / "bad artifact id").mkdir(parents=True)
    (tmp_path / "artifacts" / "bad artifact id" / "file.bin").write_bytes(b"unsafe")

    summary = store.cleanup_expired(now=datetime.now(timezone.utc))

    assert summary.deleted_count == 0
    assert summary.invalid_artifact_ids == ("<invalid>",)
    assert (tmp_path / "artifacts" / "bad artifact id").exists()
    assert_no_public_path_or_command_leak(summary.to_public_dict())


def test_metadata_summaries_are_caller_safe(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts", public_base_path="https://artifacts.local/download")
    _put_artifact(store, artifact_id="artifact_summary", ttl_seconds=60 * 60)

    summaries = store.list_metadata_summary_dicts()

    assert len(summaries) == 1
    assert summaries[0]["artifact_id"] == "artifact_summary"
    assert summaries[0]["artifact_type"] == "analysis_json"
    assert summaries[0]["retention_policy"] == "short_lived"
    assert "storage_uri" not in summaries[0]
    assert "local_path" not in summaries[0]
    assert "download_url" not in summaries[0]
    assert_no_public_path_or_command_leak(summaries)
