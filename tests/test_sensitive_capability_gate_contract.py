"""High-sensitivity capability gate contract checks."""

from __future__ import annotations

import json

from conftest import assert_no_public_path_or_command_leak
from video_editing_toolkit.security import (
    DEFERRED_HIGH_SENSITIVITY_CAPABILITIES,
    SensitiveCapabilityGate,
    evaluate_sensitive_capability_gate,
)


def test_sensitive_capabilities_default_to_deferred_without_execution() -> None:
    for capability in DEFERRED_HIGH_SENSITIVITY_CAPABILITIES:
        decision = evaluate_sensitive_capability_gate(
            policy={},
            approval_context={},
            capability=capability,
        ).to_public_dict()

        assert decision["status"] == "deferred"
        assert decision["execution_allowed"] is False
        assert decision["missing_fields"]
        assert "policy.allow_high_sensitivity_preflight" in decision["required_fields"]
        assert_no_public_path_or_command_leak(decision)


def test_policy_can_block_sensitive_capability_before_approval_review() -> None:
    decision = evaluate_sensitive_capability_gate(
        policy={"block_high_sensitivity_capabilities": True},
        approval_context={},
        capability="video.analysis.recognize_faces",
    ).to_public_dict()

    assert decision["status"] == "blocked"
    assert decision["execution_allowed"] is False
    assert decision["reason_code"] == "sensitive_capability.blocked_by_policy"
    assert_no_public_path_or_command_leak(decision)


def test_complete_approval_fields_only_allow_preflight_not_execution() -> None:
    capability = "audio.speech.diarize_speakers"
    decision = evaluate_sensitive_capability_gate(
        policy=_complete_policy(),
        approval_context=_complete_approval_context(capability),
        capability=capability,
    ).to_public_dict()

    assert decision["status"] == "approved_for_preflight_only"
    assert decision["execution_allowed"] is False
    assert decision["missing_fields"] == []
    assert decision["reason_code"] == "sensitive_capability.preflight_only"
    assert_no_public_path_or_command_leak(decision)


def test_complete_approval_for_different_capability_stays_deferred() -> None:
    decision = evaluate_sensitive_capability_gate(
        policy=_complete_policy(),
        approval_context=_complete_approval_context("audio.tts.clone_voice"),
        capability="video.analysis.recognize_people",
    ).to_public_dict()

    assert decision["status"] == "deferred"
    assert decision["execution_allowed"] is False
    assert decision["missing_fields"] == ["approval_context.approved_capabilities"]
    assert_no_public_path_or_command_leak(decision)


def test_gate_output_does_not_echo_paths_tokens_or_approval_values() -> None:
    capability = "audio.tts.clone_voice"
    raw_path = r"D:\private\voiceprints\subject-a.wav"
    token = "provider-token-secret"
    approval_context = {
        **_complete_approval_context(capability),
        "subject_consent_evidence_ref": raw_path,
        "provider_token": token,
        "approval_notes": f"use fixture {raw_path} with token={token}",
    }

    decision = SensitiveCapabilityGate().evaluate(
        policy={**_complete_policy(), "internal_policy_path": raw_path},
        approval_context=approval_context,
        capability=capability,
    ).to_public_dict()
    rendered = json.dumps(decision, sort_keys=True)

    assert decision["status"] == "approved_for_preflight_only"
    assert decision["execution_allowed"] is False
    assert raw_path not in rendered
    assert token not in rendered
    assert "provider_token" not in rendered
    assert "internal_policy_path" not in rendered
    assert_no_public_path_or_command_leak(decision)


def test_unknown_capability_is_blocked_with_safe_name() -> None:
    decision = evaluate_sensitive_capability_gate(
        policy=_complete_policy(),
        approval_context=_complete_approval_context("*"),
        capability="video.analysis.identify_private_person",
    ).to_public_dict()

    assert decision["capability"] == "unknown"
    assert decision["status"] == "blocked"
    assert decision["execution_allowed"] is False
    assert decision["reason_code"] == "sensitive_capability.unsupported"
    assert_no_public_path_or_command_leak(decision)


def _complete_policy() -> dict[str, object]:
    return {
        "high_sensitivity_contract_version": "2026-05-08.p1",
        "allow_high_sensitivity_preflight": True,
        "retention_policy_id": "retain-none-for-identity-signals",
        "audit_log_required": True,
    }


def _complete_approval_context(capability: str) -> dict[str, object]:
    return {
        "platform_approval_id": "approval_123",
        "approved_by": "platform-security",
        "approval_expires_at": "2026-06-08T00:00:00Z",
        "subject_consent_evidence_ref": "consent_evidence_123",
        "approved_capabilities": [capability],
    }
