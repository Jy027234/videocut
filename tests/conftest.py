"""Shared P0 contract-test helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS_DIR = REPO_ROOT / "manifests"
SCHEMAS_DIR = REPO_ROOT / "schemas"
FIXTURES_DIR = REPO_ROOT / "fixtures"

FORBIDDEN_PUBLIC_KEYS = {
    "storage_uri",
    "local_path",
    "file_path",
    "filesystem_path",
    "worker_path",
    "internal_path",
    "raw_command",
    "raw_shell",
    "ffmpeg_command",
    "internal_worker_url",
    "worker_url",
    "token",
    "secret",
    "password",
    "api_key",
    "private_key",
    "client_secret",
    "authorization",
}

LOCAL_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?!/)[^\s\"']+"),
    re.compile(r"\\\\[^\\/\s\"']+[\\/][^\s\"']+"),
    re.compile(r"file://", re.IGNORECASE),
    re.compile(r"local-artifact://", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])/(Users|home|var|tmp|private|mnt)/[^\s\"']+"),
)

RAW_COMMAND_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])ffmpeg(?:\.exe)?\s+-", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])ffprobe(?:\.exe)?\s+-", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])powershell(?:\.exe)?\s+", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9_])cmd\.exe\s+", re.IGNORECASE),
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def json_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.json") if path.is_file())


def require_json_files(root: Path, reason: str) -> list[Path]:
    files = json_files(root)
    if not files:
        pytest.skip(reason)
    return files


def walk_json(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_json(child, f"{path}[{index}]")


def assert_no_public_path_or_command_leak(value: Any) -> None:
    for path, node in walk_json(value):
        if isinstance(node, dict):
            leaked_keys = FORBIDDEN_PUBLIC_KEYS.intersection(node)
            assert not leaked_keys, f"{path} exposes forbidden public keys: {sorted(leaked_keys)}"
        if isinstance(node, str):
            for pattern in LOCAL_PATH_PATTERNS:
                assert not pattern.search(node), f"{path} exposes a local path-like value: {node!r}"
            for pattern in RAW_COMMAND_PATTERNS:
                assert not pattern.search(node), f"{path} exposes a raw command: {node!r}"
