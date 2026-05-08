"""Dependency-free P0 project editing core."""

from .compositor import (
    COMPOSITION_PLAN_SCHEMA,
    build_composition_plan,
    composition_warning_messages,
)
from .core import (
    ProjectEditError,
    apply_timeline_patch,
    compare_versions,
    create_project,
    generate_edit_plan,
    inspect_assets,
    render_preview,
    rollback_version,
)
from .models import InMemoryProjectStore, ProjectVersion, get_default_store
from .validator import (
    ALLOWED_OPERATIONS,
    FORBIDDEN_PATCH_KEYS,
    TimelinePatchValidationError,
    validate_timeline_patch,
)

__all__ = [
    "ALLOWED_OPERATIONS",
    "COMPOSITION_PLAN_SCHEMA",
    "FORBIDDEN_PATCH_KEYS",
    "InMemoryProjectStore",
    "ProjectEditError",
    "ProjectVersion",
    "TimelinePatchValidationError",
    "apply_timeline_patch",
    "build_composition_plan",
    "compare_versions",
    "composition_warning_messages",
    "create_project",
    "generate_edit_plan",
    "get_default_store",
    "inspect_assets",
    "render_preview",
    "rollback_version",
    "validate_timeline_patch",
]
