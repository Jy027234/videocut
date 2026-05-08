"""Caller-safe gates for deferred high-sensitivity capabilities.

This module is contract-only. It does not perform voice cloning, speaker
diarization, face recognition, person recognition, model preflight, or routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


CLONE_VOICE = "audio.tts.clone_voice"
DIARIZE_SPEAKERS = "audio.speech.diarize_speakers"
RECOGNIZE_FACES = "video.analysis.recognize_faces"
RECOGNIZE_PEOPLE = "video.analysis.recognize_people"

DEFERRED_HIGH_SENSITIVITY_CAPABILITIES = frozenset(
    {
        CLONE_VOICE,
        DIARIZE_SPEAKERS,
        RECOGNIZE_FACES,
        RECOGNIZE_PEOPLE,
    }
)

SENSITIVE_GATE_STATUSES = frozenset(
    {
        "deferred",
        "blocked",
        "approved_for_preflight_only",
    }
)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_REQUIRED_FIELDS = (
    "policy.high_sensitivity_contract_version",
    "policy.allow_high_sensitivity_preflight",
    "policy.retention_policy_id",
    "policy.audit_log_required",
    "approval_context.platform_approval_id",
    "approval_context.approved_by",
    "approval_context.approval_expires_at",
    "approval_context.subject_consent_evidence_ref",
    "approval_context.approved_capabilities",
)
_FIXED_RETENTION_NOTES = (
    "Do not persist biometric templates, voiceprints, speaker identities, or recognition matches.",
    "Preflight may validate policy shape only and must not inspect media content or extract identity signals.",
    "Execution remains disabled until a separate platform rollout explicitly registers an execution adapter.",
)
_FIXED_AUDIT_REQUIREMENTS = (
    "Record tenant, project, run, tool call, capability, policy version, approver, and consent evidence reference.",
    "Record gate status and missing field names without logging raw approval values or media identifiers.",
    "Record that execution_allowed=false for this contract gate.",
)


@dataclass(frozen=True)
class SensitiveCapabilityGateDecision:
    """Caller-safe decision for a deferred high-sensitivity capability."""

    capability: str
    status: str
    required_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]
    retention_notes: tuple[str, ...]
    audit_requirements: tuple[str, ...]
    execution_allowed: bool = False
    reason_code: str = "sensitive_capability.deferred"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "status": self.status,
            "required_fields": list(self.required_fields),
            "missing_fields": list(self.missing_fields),
            "retention_notes": list(self.retention_notes),
            "audit_requirements": list(self.audit_requirements),
            "execution_allowed": False,
            "reason_code": self.reason_code,
        }


class SensitiveCapabilityGate:
    """Lightweight adapter around the pure gate function."""

    def evaluate(
        self,
        *,
        policy: Mapping[str, Any] | None,
        approval_context: Mapping[str, Any] | None,
        capability: str,
    ) -> SensitiveCapabilityGateDecision:
        return evaluate_sensitive_capability_gate(
            policy=policy,
            approval_context=approval_context,
            capability=capability,
        )


def evaluate_sensitive_capability_gate(
    *,
    policy: Mapping[str, Any] | None,
    approval_context: Mapping[str, Any] | None,
    capability: str,
) -> SensitiveCapabilityGateDecision:
    """Evaluate a deferred high-sensitivity capability without enabling execution.

    Field values are never copied into the decision. The public result includes
    stable field names, fixed retention/audit text, and an execution_allowed flag
    that is always false.
    """

    safe_capability = capability if capability in DEFERRED_HIGH_SENSITIVITY_CAPABILITIES else "unknown"
    missing_fields = _missing_required_fields(
        policy=policy or {},
        approval_context=approval_context or {},
        capability=capability,
    )

    if capability not in DEFERRED_HIGH_SENSITIVITY_CAPABILITIES:
        return _decision(
            capability=safe_capability,
            status="blocked",
            missing_fields=missing_fields,
            reason_code="sensitive_capability.unsupported",
        )

    if _policy_blocks(policy or {}):
        return _decision(
            capability=capability,
            status="blocked",
            missing_fields=missing_fields,
            reason_code="sensitive_capability.blocked_by_policy",
        )

    if missing_fields:
        return _decision(
            capability=capability,
            status="deferred",
            missing_fields=missing_fields,
            reason_code="sensitive_capability.approval_incomplete",
        )

    return _decision(
        capability=capability,
        status="approved_for_preflight_only",
        missing_fields=(),
        reason_code="sensitive_capability.preflight_only",
    )


def _decision(
    *,
    capability: str,
    status: str,
    missing_fields: Sequence[str],
    reason_code: str,
) -> SensitiveCapabilityGateDecision:
    return SensitiveCapabilityGateDecision(
        capability=capability,
        status=status,
        required_fields=_REQUIRED_FIELDS,
        missing_fields=tuple(missing_fields),
        retention_notes=_FIXED_RETENTION_NOTES,
        audit_requirements=_FIXED_AUDIT_REQUIREMENTS,
        execution_allowed=False,
        reason_code=reason_code,
    )


def _missing_required_fields(
    *,
    policy: Mapping[str, Any],
    approval_context: Mapping[str, Any],
    capability: str,
) -> tuple[str, ...]:
    missing = []
    if not _present(policy.get("high_sensitivity_contract_version")):
        missing.append("policy.high_sensitivity_contract_version")
    if not _truthy(policy.get("allow_high_sensitivity_preflight")):
        missing.append("policy.allow_high_sensitivity_preflight")
    if not _present(policy.get("retention_policy_id")):
        missing.append("policy.retention_policy_id")
    if not _truthy(policy.get("audit_log_required")):
        missing.append("policy.audit_log_required")
    if not _present(approval_context.get("platform_approval_id")):
        missing.append("approval_context.platform_approval_id")
    if not _present(approval_context.get("approved_by")):
        missing.append("approval_context.approved_by")
    if not _present(approval_context.get("approval_expires_at")):
        missing.append("approval_context.approval_expires_at")
    if not _present(approval_context.get("subject_consent_evidence_ref")):
        missing.append("approval_context.subject_consent_evidence_ref")
    if not _capability_approved(approval_context.get("approved_capabilities"), capability):
        missing.append("approval_context.approved_capabilities")
    return tuple(missing)


def _policy_blocks(policy: Mapping[str, Any]) -> bool:
    if _truthy(policy.get("block_high_sensitivity_capabilities")):
        return True
    if policy.get("allow_high_sensitivity_preflight") is False:
        return True
    return False


def _capability_approved(value: Any, capability: str) -> bool:
    if isinstance(value, str):
        return value == capability or value == "*"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return capability in value or "*" in value
    return False


def _present(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return False
