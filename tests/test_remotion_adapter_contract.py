"""P1.1 Remotion template rendering adapter contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from video_editing_toolkit.adapters import (
    AdapterContext,
    AdapterRequest,
    AdapterStatus,
    RemotionAdapter,
    build_p1_experimental_adapter,
    resolve_p1_experimental_route,
    resolve_route,
)
from video_editing_toolkit.adapters.remotion import (
    CREATE_REMOTION_RENDER_JOB,
    REMOTION_RENDER_JOB_ARTIFACT_TYPE,
    VALIDATE_REMOTION_TEMPLATE,
)
from video_editing_toolkit.storage import LocalArtifactStore

from conftest import assert_no_public_path_or_command_leak


def test_remotion_template_validation_accepts_safe_manifest_and_props() -> None:
    result = RemotionAdapter().handle(
        _request(
            VALIDATE_REMOTION_TEMPLATE,
            input_payload=_valid_input_payload(),
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert result.output["valid"] is True
    assert result.output["dispatcher_required"] is False
    assert result.output["runtime_execution"] == "not_started"
    assert result.output["template_id"] == "brand-fastflash"
    assert result.output["composition"]["composition_id"] == "Main"
    assert result.output["composition"]["duration_frames"] == 150
    assert result.usage_metrics["node_invocations"] == 0
    assert result.usage_metrics["chromium_invocations"] == 0
    assert_no_public_path_or_command_leak(result.output)


def test_remotion_template_validation_rejects_invalid_template_shape() -> None:
    payload = _valid_input_payload()
    payload["template_manifest"]["raw_command"] = "npx remotion render ./src/index.ts Main out.mp4"

    result = RemotionAdapter().handle(
        _request(
            VALIDATE_REMOTION_TEMPLATE,
            input_payload=payload,
        )
    )

    assert result.status == AdapterStatus.FAILED
    assert result.error_code == "request.invalid"
    assert result.output["valid"] is False
    assert result.output["stable_error_code"] == "remotion.unsafe_payload"
    assert_no_public_path_or_command_leak(result.output)


def test_remotion_create_render_job_returns_dispatcher_required_safe_spec() -> None:
    result = RemotionAdapter().handle(
        _request(
            CREATE_REMOTION_RENDER_JOB,
            input_payload=_valid_input_payload(
                {
                    "render_settings": {"format": "webm"},
                    "template_artifact_ref": {
                        "artifact_id": "artifact_template_bundle",
                        "artifact_type": "remotion_template_bundle",
                        "mime_type": "application/zip",
                        "checksum": "sha256:" + "a" * 64,
                        "size_bytes": 2048,
                        "download_url": "https://artifacts.local/download/artifact_template_bundle",
                    },
                }
            ),
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    assert result.output["dispatcher_required"] is True
    assert result.output["chromium_required"] is True
    assert result.output["license_confirmation_required"] is True
    render_job = result.output["render_job"]
    assert render_job["status"] == "dispatcher_required"
    assert render_job["required_runtime"]["engine"] == "remotion"
    assert render_job["required_runtime"]["nodejs"] == "required_by_dispatcher"
    assert render_job["required_runtime"]["chromium"] == "required_by_dispatcher"
    assert render_job["sandbox"]["filesystem"] == "artifact_ref_only"
    assert render_job["sandbox"]["execution"] == "dispatcher_managed"
    assert render_job["render_settings"]["format"] == "webm"
    assert render_job["template"]["template_artifact_ref"]["artifact_id"] == "artifact_template_bundle"
    assert_no_public_path_or_command_leak(result.output)


def test_remotion_dispatcher_readiness_reports_ready_when_preflight_is_confirmed() -> None:
    result = RemotionAdapter().handle(
        _request(
            CREATE_REMOTION_RENDER_JOB,
            input_payload=_valid_input_payload(
                {
                    "dispatcher_capabilities": {
                        "nodejs": {"status": "ready"},
                        "chromium": True,
                        "remotion": "available",
                    },
                    "dispatcher_policy": {
                        "sandbox": {
                            "execution": "dispatcher_managed",
                            "filesystem": "artifact_ref_only",
                        },
                        "network": "deny_by_default",
                    },
                    "license_confirmation": {"confirmed": True},
                }
            ),
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    readiness = result.output["dispatcher_readiness"]
    assert readiness == result.output["render_job"]["dispatcher_readiness"]
    assert readiness["status"] == "ready"
    assert {check["name"]: check["status"] for check in readiness["checks"]} == {
        "nodejs": "ready",
        "chromium": "ready",
        "remotion": "ready",
        "license": "ready",
        "sandbox": "ready",
        "network": "ready",
    }
    assert result.usage_metrics["node_invocations"] == 0
    assert result.usage_metrics["chromium_invocations"] == 0
    assert_no_public_path_or_command_leak(result.output)


def test_remotion_dispatcher_readiness_reports_ready_from_preflight_attestation() -> None:
    result = RemotionAdapter().handle(
        _request(
            CREATE_REMOTION_RENDER_JOB,
            input_payload=_valid_input_payload(
                {
                    "dispatcher_preflight_attestation": _ready_dispatcher_attestation(),
                }
            ),
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    readiness = result.output["dispatcher_readiness"]
    assert readiness == result.output["render_job"]["dispatcher_readiness"]
    assert readiness["status"] == "ready"
    assert readiness["preflight_source"] == "dispatcher_attestation"
    assert {check["name"]: check["status"] for check in readiness["checks"]} == {
        "nodejs": "ready",
        "chromium": "ready",
        "remotion": "ready",
        "license": "ready",
        "sandbox": "ready",
        "network": "ready",
        "execution": "ready",
    }
    assert result.usage_metrics["node_invocations"] == 0
    assert result.usage_metrics["chromium_invocations"] == 0
    assert_no_public_path_or_command_leak(result.output)


def test_remotion_dispatcher_attestation_blocks_unavailable_runtime_or_license() -> None:
    attestation = _ready_dispatcher_attestation()
    attestation["runtime"]["remotion"] = "unavailable"
    attestation["license"]["confirmed"] = False

    result = RemotionAdapter().handle(
        _request(
            CREATE_REMOTION_RENDER_JOB,
            input_payload=_valid_input_payload(
                {
                    "dispatcher_preflight_attestation": attestation,
                }
            ),
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    readiness = result.output["dispatcher_readiness"]
    checks = {check["name"]: check for check in readiness["checks"]}
    assert readiness["status"] == "blocked"
    assert readiness["preflight_source"] == "dispatcher_attestation"
    assert checks["remotion"]["status"] == "blocked"
    assert checks["remotion"]["code"] == "attested_runtime_unavailable"
    assert checks["license"]["status"] == "blocked"
    assert checks["license"]["code"] == "attested_license_confirmation_required"
    assert_no_public_path_or_command_leak(result.output)


def test_remotion_dispatcher_readiness_blocks_without_license_confirmation() -> None:
    result = RemotionAdapter().handle(
        _request(
            CREATE_REMOTION_RENDER_JOB,
            input_payload=_valid_input_payload(
                {
                    "dispatcher_capabilities": {
                        "nodejs": True,
                        "chromium": True,
                        "remotion": True,
                    },
                    "dispatcher_policy": {
                        "sandbox": {
                            "execution": "dispatcher_managed",
                            "filesystem": "artifact_ref_only",
                        },
                        "egress": "deny_by_default",
                    },
                }
            ),
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    readiness = result.output["dispatcher_readiness"]
    checks = {check["name"]: check for check in readiness["checks"]}
    assert readiness["status"] == "blocked"
    assert checks["license"]["status"] == "blocked"
    assert checks["license"]["code"] == "license_confirmation_required"
    assert_no_public_path_or_command_leak(result.output)


def test_remotion_dispatcher_readiness_blocks_noncompliant_sandbox_policy() -> None:
    result = RemotionAdapter().handle(
        _request(
            CREATE_REMOTION_RENDER_JOB,
            input_payload=_valid_input_payload(
                {
                    "dispatcher_capabilities": {
                        "nodejs": True,
                        "chromium": True,
                        "remotion": True,
                    },
                    "dispatcher_policy": {
                        "sandbox": {
                            "execution": "caller_managed",
                            "filesystem": "artifact_ref_only",
                        },
                        "network": "deny_by_default",
                    },
                    "license_confirmation": True,
                }
            ),
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    readiness = result.output["dispatcher_readiness"]
    checks = {check["name"]: check for check in readiness["checks"]}
    assert readiness["status"] == "blocked"
    assert checks["sandbox"]["status"] == "blocked"
    assert checks["sandbox"]["code"] == "sandbox_policy_noncompliant"
    assert_no_public_path_or_command_leak(result.output)


def test_remotion_dispatcher_readiness_rejects_paths_and_commands_in_preflight_inputs() -> None:
    unsafe_cases = [
        {
            "dispatcher_capabilities": {
                "nodejs": "npx remotion render ./src/index.ts Main out.mp4",
            },
        },
        {
            "dispatcher_policy": {
                "sandbox": {
                    "execution": "dispatcher_managed",
                    "filesystem": "C:\\Users\\runner\\template",
                },
            },
        },
        {
            "dispatcher_preflight_attestation": _ready_dispatcher_attestation()
            | {
                "endpoint": "https://dispatcher.internal/render?token=secret-token",
            },
        },
    ]

    for unsafe_extra in unsafe_cases:
        result = RemotionAdapter().handle(
            _request(
                CREATE_REMOTION_RENDER_JOB,
                input_payload=_valid_input_payload(unsafe_extra),
            )
        )

        assert result.status == AdapterStatus.FAILED
        assert result.error_code == "request.invalid"
        assert result.output["stable_error_code"] == "remotion.unsafe_payload"
        assert_no_public_path_or_command_leak(result.output)


def test_remotion_create_render_job_materializes_artifact_when_store_is_available(
    tmp_path: Path,
) -> None:
    artifact_store = LocalArtifactStore(
        tmp_path / "artifacts",
        public_base_path="https://artifacts.local/download",
    )
    payload = _valid_input_payload({"_artifact_store": artifact_store})

    result = RemotionAdapter().handle(
        _request(
            CREATE_REMOTION_RENDER_JOB,
            input_payload=payload,
        )
    )

    assert result.status == AdapterStatus.SUCCEEDED
    refs = [ref for ref in result.artifact_refs if ref.artifact_type == REMOTION_RENDER_JOB_ARTIFACT_TYPE]
    assert len(refs) == 1
    assert result.output["render_job_artifact_ref"]["artifact_id"] == refs[0].artifact_id
    artifact_path = artifact_store.open_local_path(refs[0].artifact_id)
    assert artifact_path is not None
    assert artifact_path.name == "remotion_render_job.json"
    artifact_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact_payload["render_job"]["render_job_id"] == result.output["render_job_id"]
    assert artifact_payload["render_job"]["dispatcher_required"] is True
    assert_no_public_path_or_command_leak(result.output)
    assert_no_public_path_or_command_leak(artifact_payload)


def test_remotion_template_capabilities_resolve_through_p1_routing() -> None:
    validate_route = resolve_p1_experimental_route(VALIDATE_REMOTION_TEMPLATE)
    render_route = resolve_p1_experimental_route(CREATE_REMOTION_RENDER_JOB)

    assert validate_route.adapter_name == "remotion"
    assert render_route.adapter_name == "remotion"
    assert validate_route.queue_topic == "video.template.remotion"
    assert render_route.queue_topic == "video.template.remotion"
    assert isinstance(build_p1_experimental_adapter(VALIDATE_REMOTION_TEMPLATE), RemotionAdapter)
    assert isinstance(build_p1_experimental_adapter(CREATE_REMOTION_RENDER_JOB), RemotionAdapter)

    for capability in (VALIDATE_REMOTION_TEMPLATE, CREATE_REMOTION_RENDER_JOB):
        try:
            resolve_route(capability)
        except ValueError as exc:
            assert "No adapter route registered" in str(exc)
        else:
            raise AssertionError(f"{capability} should not resolve through the default P0 route table")


def _valid_input_payload(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "template_manifest": {
            "template_id": "brand-fastflash",
            "version": "1.0.0",
            "compositions": [
                {
                    "composition_id": "Main",
                    "duration_frames": 150,
                    "fps": 30,
                    "width": 1080,
                    "height": 1920,
                    "default_props": {"caption": "Launch"},
                    "props_schema": {
                        "type": "object",
                        "required": ["caption", "brand_color"],
                        "additionalProperties": False,
                        "properties": {
                            "caption": {"type": "string"},
                            "brand_color": {"type": "string"},
                            "cta_enabled": {"type": "boolean"},
                        },
                    },
                }
            ],
        },
        "composition_id": "Main",
        "props": {
            "brand_color": "#31A8FF",
            "cta_enabled": True,
        },
    }
    if extra:
        payload.update(extra)
    return payload


def _ready_dispatcher_attestation() -> dict[str, Any]:
    return {
        "schema": "video_editing_toolkit.remotion_dispatcher_preflight_attestation.v0",
        "runtime": {
            "nodejs": "ready",
            "chromium": "ready",
            "remotion": "ready",
        },
        "sandbox": {
            "execution": "dispatcher_managed",
            "filesystem": "artifact_ref_only",
        },
        "network": {
            "egress": "deny_by_default",
        },
        "license": {
            "confirmed": True,
            "license_id": "remotion_team_license",
        },
        "execution": {
            "mode": "dispatcher_only",
            "execution_enabled": False,
        },
    }


def _request(capability: str, *, input_payload: dict[str, Any]) -> AdapterRequest:
    return AdapterRequest(
        context=AdapterContext(
            tenant_id="tenant_remotion",
            project_id="proj_remotion",
            run_id="run_remotion_0001",
            tool_call_id="tool_call_remotion_0001",
            capability=capability,
        ),
        input=input_payload,
    )
