"""P0 local resumable artifact upload contract tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from video_editing_toolkit.storage.artifacts import LocalArtifactStore
from video_editing_toolkit.storage.resumable import LocalResumableUploadStore, ResumableUploadError

from conftest import assert_no_public_path_or_command_leak


def test_resumable_upload_appends_chunks_and_completes_artifact(tmp_path: Path) -> None:
    content = b"chunk-one/chunk-two"
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    upload_store = LocalResumableUploadStore(tmp_path / "sessions", artifact_store=artifact_store)
    manifest = upload_store.create_session(
        artifact_id="artifact_resumable_video",
        artifact_type="source_video",
        owner_tenant_id="tenant_resumable",
        created_by_run_id="run_resumable",
        filename="source.mp4",
        total_size_bytes=len(content),
        expected_checksum=f"sha256:{hashlib.sha256(content).hexdigest()}",
        mime_type="video/mp4",
    )

    session_id = str(manifest["session_id"])
    first = upload_store.append_chunk(session_id, offset=0, content=content[:9])
    second = upload_store.append_chunk(session_id, offset=9, content=content[9:])
    ref = upload_store.complete(session_id)
    completed = upload_store.load_manifest(session_id)

    assert first["received_bytes"] == 9
    assert second["received_bytes"] == len(content)
    assert second["chunk_count"] == 2
    assert completed["completed"] is True
    assert completed["final_checksum"] == f"sha256:{hashlib.sha256(content).hexdigest()}"
    assert completed["artifact_ref"]["artifact_id"] == "artifact_resumable_video"
    assert "storage_uri" not in completed["artifact_ref"]
    assert "local_path" not in completed["artifact_ref"]
    assert_no_public_path_or_command_leak(completed)
    assert ref.checksum == f"sha256:{hashlib.sha256(content).hexdigest()}"
    local_path = artifact_store.open_local_path("artifact_resumable_video")
    assert local_path is not None
    assert local_path.read_bytes() == content


def test_resumable_upload_rejects_wrong_chunk_offset(tmp_path: Path) -> None:
    upload_store = LocalResumableUploadStore(
        tmp_path / "sessions",
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
    )
    session = upload_store.create_session(
        artifact_id="artifact_offset_video",
        artifact_type="source_video",
        owner_tenant_id="tenant_resumable",
        created_by_run_id="run_resumable",
        filename="source.mp4",
    )

    with pytest.raises(ResumableUploadError) as exc_info:
        upload_store.append_chunk(str(session["session_id"]), offset=1, content=b"bad")

    assert exc_info.value.error_code == "resumable_offset_mismatch"
    assert exc_info.value.session_id == session["session_id"]


def test_resumable_upload_rejects_completion_checksum_mismatch(tmp_path: Path) -> None:
    artifact_store = LocalArtifactStore(tmp_path / "artifacts")
    upload_store = LocalResumableUploadStore(tmp_path / "sessions", artifact_store=artifact_store)
    session = upload_store.create_session(
        artifact_id="artifact_checksum_video",
        artifact_type="source_video",
        owner_tenant_id="tenant_resumable",
        created_by_run_id="run_resumable",
        filename="source.mp4",
        expected_checksum=f"sha256:{hashlib.sha256(b'expected').hexdigest()}",
    )
    upload_store.append_chunk(str(session["session_id"]), offset=0, content=b"actual")

    with pytest.raises(ResumableUploadError) as exc_info:
        upload_store.complete(str(session["session_id"]))

    assert exc_info.value.error_code == "resumable_checksum_mismatch"
    assert artifact_store.open_local_path("artifact_checksum_video") is None
