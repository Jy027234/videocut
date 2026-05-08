"""Signed artifact download URL helpers.

The token deliberately carries only caller-safe artifact metadata. It never
contains a local path, storage URI, or bucket key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


SIGNED_ARTIFACT_TOKEN_PARAM = "sat"
SIGNED_ARTIFACT_TOKEN_VERSION = "v1"
ARTIFACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA256_PATTERN = re.compile(r"^sha256:[a-fA-F0-9]{64}$")
SCOPE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


@dataclass(frozen=True)
class SignedArtifactAccess:
    artifact_id: str
    scope: str
    checksum: str
    expires_at: int


class SignedArtifactUrlError(ValueError):
    def __init__(self, error_code: str, error_message: str) -> None:
        super().__init__(error_message)
        self.error_code = error_code
        self.error_message = error_message


def create_signed_artifact_token(
    *,
    artifact_id: str,
    checksum: str,
    secret: str | bytes,
    expires_at: datetime | int | None = None,
    ttl_seconds: int | None = 60 * 60,
    scope: str = "read",
    now: datetime | int | None = None,
) -> str:
    """Create a compact HMAC token for read access to one artifact."""

    secret_bytes = _secret_bytes(secret)
    payload = {
        "artifact_id": _safe_artifact_id(artifact_id),
        "checksum": _normalize_checksum(checksum),
        "expires_at": _expires_timestamp(expires_at=expires_at, ttl_seconds=ttl_seconds, now=now),
        "scope": _safe_scope(scope),
    }
    encoded_payload = _b64encode(_canonical_json(payload))
    signing_input = f"{SIGNED_ARTIFACT_TOKEN_VERSION}.{encoded_payload}".encode("ascii")
    signature = _b64encode(hmac.new(secret_bytes, signing_input, hashlib.sha256).digest())
    return f"{SIGNED_ARTIFACT_TOKEN_VERSION}.{encoded_payload}.{signature}"


def verify_signed_artifact_token(
    token: str,
    *,
    secret: str | bytes,
    artifact_id: str | None = None,
    checksum: str | None = None,
    scope: str = "read",
    now: datetime | int | None = None,
) -> SignedArtifactAccess:
    """Verify a signed artifact token and return the caller-safe grant."""

    secret_bytes = _secret_bytes(secret)
    version, encoded_payload, encoded_signature = _split_token(token)
    if version != SIGNED_ARTIFACT_TOKEN_VERSION:
        raise SignedArtifactUrlError("artifact_signed_token_invalid", "Artifact signed token is invalid.")

    signing_input = f"{version}.{encoded_payload}".encode("ascii")
    expected_signature = _b64encode(hmac.new(secret_bytes, signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(encoded_signature, expected_signature):
        raise SignedArtifactUrlError("artifact_signed_token_invalid", "Artifact signed token is invalid.")

    payload = _decode_payload(encoded_payload)
    access = SignedArtifactAccess(
        artifact_id=_safe_artifact_id(_payload_string(payload, "artifact_id")),
        scope=_safe_scope(_payload_string(payload, "scope")),
        checksum=_normalize_checksum(_payload_string(payload, "checksum")),
        expires_at=_payload_int(payload, "expires_at"),
    )

    if _now_timestamp(now) >= access.expires_at:
        raise SignedArtifactUrlError("artifact_signed_token_expired", "Artifact signed token has expired.")
    if artifact_id is not None and access.artifact_id != _safe_artifact_id(artifact_id):
        raise SignedArtifactUrlError(
            "artifact_signed_token_artifact_mismatch",
            "Artifact signed token does not match this artifact.",
        )
    if checksum is not None and access.checksum.lower() != _normalize_checksum(checksum).lower():
        raise SignedArtifactUrlError(
            "artifact_signed_token_checksum_mismatch",
            "Artifact signed token does not match this artifact checksum.",
        )
    if access.scope != _safe_scope(scope):
        raise SignedArtifactUrlError(
            "artifact_signed_token_scope_denied",
            "Artifact signed token does not grant the requested scope.",
        )
    return access


def sign_download_url(
    download_url: str,
    *,
    artifact_id: str,
    checksum: str,
    secret: str | bytes,
    expires_at: datetime | int | None = None,
    ttl_seconds: int | None = 60 * 60,
    scope: str = "read",
    token_param: str = SIGNED_ARTIFACT_TOKEN_PARAM,
    now: datetime | int | None = None,
) -> str:
    """Append a signed artifact token to a relative or same-origin URL."""

    token = create_signed_artifact_token(
        artifact_id=artifact_id,
        checksum=checksum,
        secret=secret,
        expires_at=expires_at,
        ttl_seconds=ttl_seconds,
        scope=scope,
        now=now,
    )
    return append_signed_artifact_token(download_url, token, token_param=token_param)


def append_signed_artifact_token(
    download_url: str,
    token: str,
    *,
    token_param: str = SIGNED_ARTIFACT_TOKEN_PARAM,
) -> str:
    if not isinstance(download_url, str) or not download_url.strip():
        raise SignedArtifactUrlError("artifact_download_url_invalid", "Artifact download_url is invalid.")
    token_param = _safe_token_param(token_param)
    parsed = urllib.parse.urlsplit(download_url.strip())
    query_items = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if key != token_param
    ]
    query_items.append((token_param, token))
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query_items),
            parsed.fragment,
        )
    )


def extract_signed_artifact_token(
    download_url: str,
    *,
    token_param: str = SIGNED_ARTIFACT_TOKEN_PARAM,
) -> str | None:
    if not isinstance(download_url, str) or not download_url.strip():
        return None
    token_param = _safe_token_param(token_param)
    parsed = urllib.parse.urlsplit(download_url.strip())
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if key == token_param and value:
            return value
    return None


def _split_token(token: str) -> tuple[str, str, str]:
    if not isinstance(token, str):
        raise SignedArtifactUrlError("artifact_signed_token_invalid", "Artifact signed token is invalid.")
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise SignedArtifactUrlError("artifact_signed_token_invalid", "Artifact signed token is invalid.")
    return parts[0], parts[1], parts[2]


def _decode_payload(encoded_payload: str) -> dict[str, Any]:
    try:
        decoded = _b64decode(encoded_payload)
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
        raise SignedArtifactUrlError("artifact_signed_token_invalid", "Artifact signed token is invalid.") from exc
    if not isinstance(payload, dict):
        raise SignedArtifactUrlError("artifact_signed_token_invalid", "Artifact signed token is invalid.")
    return payload


def _payload_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SignedArtifactUrlError("artifact_signed_token_invalid", "Artifact signed token is invalid.")
    return value


def _payload_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SignedArtifactUrlError("artifact_signed_token_invalid", "Artifact signed token is invalid.")
    return value


def _safe_artifact_id(artifact_id: str) -> str:
    if not isinstance(artifact_id, str) or not ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
        raise SignedArtifactUrlError("artifact_id_invalid", "Artifact id is invalid.")
    return artifact_id


def _safe_scope(scope: str) -> str:
    if not isinstance(scope, str) or not SCOPE_PATTERN.fullmatch(scope):
        raise SignedArtifactUrlError("artifact_signed_scope_invalid", "Artifact signed token scope is invalid.")
    return scope


def _safe_token_param(token_param: str) -> str:
    if not isinstance(token_param, str) or not SCOPE_PATTERN.fullmatch(token_param):
        raise SignedArtifactUrlError("artifact_signed_token_param_invalid", "Artifact token parameter is invalid.")
    return token_param


def _normalize_checksum(checksum: str) -> str:
    if not isinstance(checksum, str):
        raise SignedArtifactUrlError("artifact_checksum_invalid", "Artifact checksum must be a sha256 digest.")
    normalized = checksum.strip().lower()
    if re.fullmatch(r"[a-f0-9]{64}", normalized):
        normalized = f"sha256:{normalized}"
    if not SHA256_PATTERN.fullmatch(normalized):
        raise SignedArtifactUrlError("artifact_checksum_invalid", "Artifact checksum must be a sha256 digest.")
    return normalized


def _expires_timestamp(
    *,
    expires_at: datetime | int | None,
    ttl_seconds: int | None,
    now: datetime | int | None,
) -> int:
    if expires_at is not None:
        return _timestamp(expires_at)
    if ttl_seconds is None or isinstance(ttl_seconds, bool) or ttl_seconds <= 0:
        raise SignedArtifactUrlError("artifact_signed_token_ttl_invalid", "Artifact signed token TTL is invalid.")
    return _now_timestamp(now) + ttl_seconds


def _now_timestamp(now: datetime | int | None) -> int:
    if now is None:
        return int(time.time())
    return _timestamp(now)


def _timestamp(value: datetime | int) -> int:
    if isinstance(value, bool):
        raise SignedArtifactUrlError("artifact_signed_token_time_invalid", "Artifact signed token time is invalid.")
    if isinstance(value, int):
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.astimezone(timezone.utc).timestamp())
    raise SignedArtifactUrlError("artifact_signed_token_time_invalid", "Artifact signed token time is invalid.")


def _secret_bytes(secret: str | bytes) -> bytes:
    if isinstance(secret, str) and secret:
        return secret.encode("utf-8")
    if isinstance(secret, bytes) and secret:
        return secret
    raise SignedArtifactUrlError("artifact_signed_token_secret_required", "Artifact signed token secret is required.")


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")
