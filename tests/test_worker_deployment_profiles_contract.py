"""P1.8 Docker worker deployment profile contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
ARTIFACT_CACHE_MOUNT = "artifact-cache:/workspace/.video-toolkit-data/artifact-cache"

EXPECTED_PROFILE_CONTRACTS = {
    "cpu_light": {
        "build_target": "toolkit",
        "allowed_resource_classes": "cpu_light",
        "max_job_input_bytes": "536870912",
        "max_run_timeout_seconds": "120",
        "max_artifact_bytes": "536870912",
        "cpus": "1.0",
        "memory": "1g",
    },
    "cpu_heavy": {
        "build_target": "toolkit",
        "allowed_resource_classes": "cpu_heavy",
        "max_job_input_bytes": "4294967296",
        "max_run_timeout_seconds": "900",
        "max_artifact_bytes": "4294967296",
        "cpus": "2.0",
        "memory": "4g",
    },
    "analysis": {
        "build_target": "analysis",
        "allowed_resource_classes": "cpu_heavy",
        "max_job_input_bytes": "4294967296",
        "max_run_timeout_seconds": "900",
        "max_artifact_bytes": "4294967296",
        "cpus": "2.0",
        "memory": "4g",
    },
    "speech": {
        "build_target": "speech",
        "allowed_resource_classes": "gpu_optional",
        "max_job_input_bytes": "2147483648",
        "max_run_timeout_seconds": "1800",
        "max_artifact_bytes": "536870912",
        "cpus": "2.0",
        "memory": "8g",
    },
    "render": {
        "build_target": "toolkit",
        "allowed_resource_classes": "cpu_heavy",
        "max_job_input_bytes": "4294967296",
        "max_run_timeout_seconds": "900",
        "max_artifact_bytes": "4294967296",
        "cpus": "2.0",
        "memory": "4g",
    },
}


def _load_compose() -> dict[str, Any]:
    loaded = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _environment(service: Mapping[str, Any]) -> dict[str, str]:
    environment = service.get("environment")
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    if isinstance(environment, list):
        result: dict[str, str] = {}
        for item in environment:
            key, _, value = str(item).partition("=")
            result[key] = value
        return result
    return {}


def _resource_limits(service: Mapping[str, Any]) -> dict[str, str]:
    deploy = service.get("deploy")
    assert isinstance(deploy, dict)
    resources = deploy.get("resources")
    assert isinstance(resources, dict)
    limits = resources.get("limits")
    assert isinstance(limits, dict)
    return {str(key): str(value) for key, value in limits.items()}


def test_worker_profiles_are_explicit_and_default_toolkit_stays_cpu_light() -> None:
    compose = _load_compose()
    services = compose["services"]

    assert set(EXPECTED_PROFILE_CONTRACTS).issubset(services)

    toolkit = services["toolkit"]
    assert "profiles" not in toolkit
    assert toolkit["image"] == "video-editing-toolkit:dev"
    assert toolkit["build"] == {"context": "."}
    assert ARTIFACT_CACHE_MOUNT in toolkit["volumes"]

    toolkit_env = _environment(toolkit)
    assert toolkit_env["VIDEO_TOOLKIT_WORKER_PROFILE"] == "cpu_light"
    assert toolkit_env["VIDEO_TOOLKIT_ALLOWED_RESOURCE_CLASSES"] == "cpu_light"
    assert toolkit_env["VIDEO_TOOLKIT_MAX_JOB_INPUT_BYTES"] == "536870912"
    assert toolkit_env["VIDEO_TOOLKIT_MAX_RUN_TIMEOUT_SECONDS"] == "120"
    assert toolkit_env["VIDEO_TOOLKIT_MAX_ARTIFACT_BYTES"] == "536870912"
    assert "VET_ALLOW_WHISPER" not in toolkit_env
    assert "VET_ALLOW_WHISPER_DOWNLOAD" not in toolkit_env


def test_worker_profiles_define_resource_env_and_artifact_cache_boundaries() -> None:
    compose = _load_compose()
    services = compose["services"]
    volumes = compose["volumes"]

    assert volumes["artifact-cache"]["name"] == "video-toolkit-artifact-cache"

    for profile_name, expected in EXPECTED_PROFILE_CONTRACTS.items():
        service = services[profile_name]
        env = _environment(service)
        limits = _resource_limits(service)

        assert service["profiles"] == [profile_name]
        assert service["build"]["target"] == expected["build_target"]
        assert ARTIFACT_CACHE_MOUNT in service["volumes"]
        assert env["VIDEO_TOOLKIT_DATA_DIR"] == "/workspace/.video-toolkit-data"
        assert (
            env["VIDEO_TOOLKIT_ARTIFACT_CACHE_DIR"]
            == "/workspace/.video-toolkit-data/artifact-cache"
        )
        assert env["VIDEO_TOOLKIT_WORKER_PROFILE"] == profile_name
        assert (
            env["VIDEO_TOOLKIT_ALLOWED_RESOURCE_CLASSES"]
            == expected["allowed_resource_classes"]
        )
        assert env["VIDEO_TOOLKIT_MAX_JOB_INPUT_BYTES"] == expected["max_job_input_bytes"]
        assert (
            env["VIDEO_TOOLKIT_MAX_RUN_TIMEOUT_SECONDS"]
            == expected["max_run_timeout_seconds"]
        )
        assert env["VIDEO_TOOLKIT_MAX_ARTIFACT_BYTES"] == expected["max_artifact_bytes"]
        assert env["VIDEO_TOOLKIT_MAX_ATTEMPTS"] == "1"
        assert limits["cpus"] == expected["cpus"]
        assert limits["memory"] == expected["memory"]


def test_speech_profile_keeps_model_execution_and_downloads_explicit() -> None:
    speech = _load_compose()["services"]["speech"]
    env = _environment(speech)

    assert "whisper-cache:/workspace/.video-toolkit-data/whisper-cache" in speech["volumes"]
    assert env["VET_WHISPER_MODEL_DIR"] == "/workspace/.video-toolkit-data/whisper-cache"
    assert env["WHISPER_CACHE_DIR"] == "/workspace/.video-toolkit-data/whisper-cache"
    assert env["VET_ALLOW_WHISPER"] == "0"
    assert env["VET_ALLOW_WHISPER_DOWNLOAD"] == "0"
    assert "VET_WHISPER_MODEL" not in env
    assert "VET_WHISPER_MODEL_PATH" not in env


def test_compose_profiles_do_not_embed_secret_defaults_or_platform_core_work() -> None:
    compose = _load_compose()
    services = compose["services"]
    forbidden_secret_names = (
        "authorization",
        "token",
        "secret",
        "password",
        "api_key",
        "private_key",
        "client_secret",
    )

    for service_name in ("toolkit", *EXPECTED_PROFILE_CONTRACTS):
        service = services[service_name]
        rendered_service = repr(service).lower()
        assert "platform-core" not in rendered_service
        assert "platform_core" not in rendered_service

        for key, value in _environment(service).items():
            normalized_key = key.lower()
            normalized_value = value.lower()
            assert not any(secret in normalized_key for secret in forbidden_secret_names)
            assert not any(secret in normalized_value for secret in forbidden_secret_names)
            assert not normalized_value.startswith("${")
