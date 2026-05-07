"""In-memory project/version model for the P0 project edit core."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_timeline() -> dict[str, Any]:
    return {
        "tracks": {},
        "transitions": [],
    }


@dataclass(frozen=True)
class ProjectVersion:
    project_id: str
    version_id: str
    parent_version_id: str | None
    timeline: dict[str, Any]
    change_reason: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "version_id": self.version_id,
            "parent_version_id": self.parent_version_id,
            "timeline": deepcopy(self.timeline),
            "change_reason": self.change_reason,
            "created_at": self.created_at,
        }


class InMemoryProjectStore:
    """Thread-safe in-memory version store scoped to the current process."""

    def __init__(self) -> None:
        self._projects: dict[str, list[ProjectVersion]] = {}
        self._lock = Lock()

    def create_project(self, project_id: str, *, initial_timeline: dict[str, Any] | None = None) -> ProjectVersion:
        with self._lock:
            versions = self._projects.setdefault(project_id, [])
            if versions:
                return versions[-1]
            version = ProjectVersion(
                project_id=project_id,
                version_id="ver_0001",
                parent_version_id=None,
                timeline=deepcopy(initial_timeline) if initial_timeline is not None else empty_timeline(),
                change_reason="Create project.",
            )
            versions.append(version)
            return version

    def ensure_project(self, project_id: str) -> ProjectVersion:
        return self.create_project(project_id)

    def get_version(self, project_id: str, version_id: str) -> ProjectVersion | None:
        with self._lock:
            for version in self._projects.get(project_id, []):
                if version.version_id == version_id:
                    return version
        return None

    def latest_version(self, project_id: str) -> ProjectVersion | None:
        with self._lock:
            versions = self._projects.get(project_id, [])
            return versions[-1] if versions else None

    def add_version(
        self,
        project_id: str,
        *,
        parent_version_id: str,
        timeline: dict[str, Any],
        change_reason: str,
    ) -> ProjectVersion:
        with self._lock:
            versions = self._projects.setdefault(project_id, [])
            version = ProjectVersion(
                project_id=project_id,
                version_id=_next_version_id(versions),
                parent_version_id=parent_version_id,
                timeline=deepcopy(timeline),
                change_reason=change_reason,
            )
            versions.append(version)
            return version

    def list_versions(self, project_id: str) -> list[ProjectVersion]:
        with self._lock:
            return list(self._projects.get(project_id, []))


def _next_version_id(versions: list[ProjectVersion]) -> str:
    return f"ver_{len(versions) + 1:04d}"


_DEFAULT_STORE = InMemoryProjectStore()


def get_default_store() -> InMemoryProjectStore:
    return _DEFAULT_STORE
