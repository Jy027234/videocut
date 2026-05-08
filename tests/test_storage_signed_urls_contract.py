"""P0 local signed artifact URL contract tests."""

from __future__ import annotations

import hashlib

import pytest

from video_editing_toolkit.storage.signed_urls import (
    SignedArtifactUrlError,
    create_signed_artifact_token,
    extract_signed_artifact_token,
    sign_download_url,
    verify_signed_artifact_token,
)


def test_signed_artifact_token_round_trips_read_scope() -> None:
    checksum = f"sha256:{hashlib.sha256(b'video-bytes').hexdigest()}"
    token = create_signed_artifact_token(
        artifact_id="artifact_signed_001",
        checksum=checksum,
        secret="local-secret",
        expires_at=100,
        now=10,
    )

    access = verify_signed_artifact_token(
        token,
        secret="local-secret",
        artifact_id="artifact_signed_001",
        checksum=checksum,
        now=10,
    )

    assert access.artifact_id == "artifact_signed_001"
    assert access.scope == "read"
    assert access.checksum == checksum
    assert access.expires_at == 100


def test_signed_download_url_uses_query_token_without_storage_uri() -> None:
    checksum = f"sha256:{hashlib.sha256(b'video-bytes').hexdigest()}"
    signed_url = sign_download_url(
        "/artifacts/download/artifact_signed_001",
        artifact_id="artifact_signed_001",
        checksum=checksum,
        secret="local-secret",
        expires_at=100,
        now=10,
    )

    token = extract_signed_artifact_token(signed_url)

    assert signed_url.startswith("/artifacts/download/artifact_signed_001?sat=")
    assert "local-artifact://" not in signed_url
    assert token is not None
    assert verify_signed_artifact_token(
        token,
        secret="local-secret",
        artifact_id="artifact_signed_001",
        checksum=checksum,
        now=10,
    ).scope == "read"


def test_signed_artifact_token_rejects_expired_token() -> None:
    checksum = f"sha256:{hashlib.sha256(b'video-bytes').hexdigest()}"
    token = create_signed_artifact_token(
        artifact_id="artifact_expired_001",
        checksum=checksum,
        secret="local-secret",
        expires_at=100,
        now=10,
    )

    with pytest.raises(SignedArtifactUrlError) as exc_info:
        verify_signed_artifact_token(
            token,
            secret="local-secret",
            artifact_id="artifact_expired_001",
            checksum=checksum,
            now=100,
        )

    assert exc_info.value.error_code == "artifact_signed_token_expired"


def test_signed_artifact_token_rejects_tampered_signature() -> None:
    checksum = f"sha256:{hashlib.sha256(b'video-bytes').hexdigest()}"
    token = create_signed_artifact_token(
        artifact_id="artifact_tampered_001",
        checksum=checksum,
        secret="local-secret",
        expires_at=100,
        now=10,
    )
    tampered = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"

    with pytest.raises(SignedArtifactUrlError) as exc_info:
        verify_signed_artifact_token(
            tampered,
            secret="local-secret",
            artifact_id="artifact_tampered_001",
            checksum=checksum,
            now=10,
        )

    assert exc_info.value.error_code == "artifact_signed_token_invalid"
