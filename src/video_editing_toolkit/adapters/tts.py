"""Structured MOSS-TTS-Nano voiceover adapter skeleton."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from video_editing_toolkit.resource_guard import CPU_HEAVY_LIMITS, ErrorCode
from video_editing_toolkit.security import CLONE_VOICE, evaluate_sensitive_capability_gate
from video_editing_toolkit.storage import ArtifactRef, LocalArtifactStore

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter, TOOLKIT_ID


GENERATE_VOICEOVER = "audio.tts.generate_voiceover"
VOICEOVER_MANIFEST_ARTIFACT_TYPE = "voiceover_manifest"
VOICEOVER_PLAN_SCHEMA = "video_editing_toolkit.voiceover_plan.v0"
VOICEOVER_MANIFEST_SCHEMA = "video_editing_toolkit.voiceover_manifest.v0"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_MODEL_PATH_ENV_VARS = (
    "VET_MOSS_TTS_NANO_MODEL_PATH",
    "VIDEO_TOOLKIT_MOSS_TTS_NANO_MODEL_PATH",
    "MOSS_TTS_NANO_MODEL_PATH",
)
_MODEL_ROOT_ENV_VARS = (
    "VET_MOSS_TTS_NANO_MODEL_ROOT",
    "VIDEO_TOOLKIT_MOSS_TTS_NANO_MODEL_ROOT",
    "MOSS_TTS_NANO_MODEL_ROOT",
)
_TTS_BUNDLE_ENV_VARS = (
    "VET_MOSS_TTS_NANO_TTS_BUNDLE",
    "VIDEO_TOOLKIT_MOSS_TTS_NANO_TTS_BUNDLE",
    "MOSS_TTS_NANO_TTS_BUNDLE",
)
_CODEC_BUNDLE_ENV_VARS = (
    "VET_MOSS_TTS_NANO_CODEC_BUNDLE",
    "VIDEO_TOOLKIT_MOSS_TTS_NANO_CODEC_BUNDLE",
    "MOSS_TTS_NANO_CODEC_BUNDLE",
)
_MODEL_PATH_INPUT_KEYS = (
    "model_path",
    "onnx_model_path",
    "moss_tts_nano_model_path",
)
_MODEL_ROOT_INPUT_KEYS = (
    "model_root",
    "model_bundle_root",
    "moss_tts_nano_model_root",
)
_TTS_BUNDLE_INPUT_KEYS = (
    "tts_bundle",
    "tts_bundle_path",
    "moss_tts_nano_tts_bundle",
)
_CODEC_BUNDLE_INPUT_KEYS = (
    "codec_bundle",
    "codec_bundle_path",
    "moss_tts_nano_codec_bundle",
)
_TTS_BUNDLE_DIRNAME = "MOSS-TTS-Nano-100M-ONNX"
_CODEC_BUNDLE_DIRNAME = "MOSS-Audio-Tokenizer-Nano-ONNX"
_TTS_BUNDLE_REQUIRED_FILES = (
    "moss_tts_prefill.onnx",
    "moss_tts_decode_step.onnx",
    "moss_tts_local_decoder.onnx",
    "moss_tts_local_cached_step.onnx",
    "moss_tts_local_fixed_sampled_frame.onnx",
    "moss_tts_global_shared.data",
    "moss_tts_local_shared.data",
    "tts_browser_onnx_meta.json",
    "tokenizer.model",
)
_CODEC_BUNDLE_REQUIRED_FILES = (
    "moss_audio_tokenizer_encode.onnx",
    "moss_audio_tokenizer_encode.data",
    "moss_audio_tokenizer_decode_full.onnx",
    "moss_audio_tokenizer_decode_step.onnx",
    "moss_audio_tokenizer_decode_shared.data",
    "codec_browser_onnx_meta.json",
)
_CLONE_KEY_PARTS = ("voice_clone", "voiceprint")
_LOCAL_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/](?!/)[^\s\"']+"),
    re.compile(r"\\\\[^\\/\s\"']+[\\/][^\s\"']+"),
    re.compile(r"file://[^\s\"']*", re.IGNORECASE),
    re.compile(r"local-artifact://[^\s\"']*", re.IGNORECASE),
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|client[_-]?secret)\s*[:=]\s*[^\s,;]+"
)
_SAFE_LABEL_PATTERN = re.compile(r"[^A-Za-z0-9_.:-]+")
_MAX_TEXT_PREVIEW_CHARS = 500


class TTSAdapter(BaseAdapter):
    """P1 local contract for MOSS-TTS-Nano ONNX CPU voiceover generation."""

    adapter_name = "moss_tts_nano"
    supported_capabilities = frozenset({GENERATE_VOICEOVER})
    default_limits = CPU_HEAVY_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability == GENERATE_VOICEOVER:
            return self._generate_voiceover(request)
        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def generate_voiceover(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def describe(self) -> Mapping[str, Any]:
        description = dict(super().describe())
        description["model_runtime"] = _model_runtime_public(
            configured=bool(_configured_model_path({})),
            reason_code="tts.model_configured" if _configured_model_path({}) else "tts.model_unconfigured",
        )
        description["safety"] = {
            "voice_clone_default": "disabled",
            "requires_consent_for_voice_clone": True,
        }
        return description

    def _generate_voiceover(self, request: AdapterRequest) -> AdapterResult:
        clone_requested = _voice_clone_requested(request.input)
        if clone_requested:
            gate = evaluate_sensitive_capability_gate(
                policy=_high_sensitivity_policy(request),
                approval_context=_approval_context(request),
                capability=CLONE_VOICE,
            ).to_public_dict()
            return AdapterResult(
                status=AdapterStatus.FAILED,
                output={
                    "schema": VOICEOVER_PLAN_SCHEMA,
                    "operation": "generate_voiceover",
                    "reason_code": "tts.voice_clone_deferred",
                    "requires_consent": True,
                    "deferred_capability": "audio.tts.clone_voice",
                    "required_context": ["consent_policy", "approval_context"],
                    "high_sensitivity_gate": gate,
                    "model_runtime": _model_runtime_public(
                        configured=bool(_configured_model_path(request.input)),
                        reason_code="tts.voice_clone_deferred",
                    ),
                },
                error_code=ErrorCode.INVALID_REQUEST,
                error_message=(
                    "voice clone requests are disabled in P1.1 and require a later explicit clone_voice capability."
                ),
            )

        if _preflight_only(request.input):
            preflight = build_runtime_preflight(request.input)
            return AdapterResult(
                status=AdapterStatus.SUCCEEDED,
                output={
                    "schema": VOICEOVER_PLAN_SCHEMA,
                    "operation": "generate_voiceover",
                    "synthesis_mode": "preflight_only",
                    "reason_code": preflight["reason_code"],
                    "runtime_preflight": preflight,
                    "model_runtime": _model_runtime_public(
                        configured=preflight["bundle_summary"]["configured"],
                        reason_code=preflight["reason_code"],
                    ),
                    "audio_artifact_ref": None,
                },
                usage_metrics={
                    "worker": "moss-tts-nano",
                    "operation": "preflight_only",
                    "preflight_status": preflight["status"],
                },
            )

        plan = build_voiceover_plan(request, clone_requested=clone_requested)
        if plan is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                output={
                    "schema": VOICEOVER_PLAN_SCHEMA,
                    "operation": "generate_voiceover",
                    "reason_code": "tts.text_required",
                },
                error_code=ErrorCode.INVALID_REQUEST,
                error_message="generate_voiceover requires text, script, or text segments.",
            )

        model_path = _configured_model_path(request.input)
        model_configured = bool(model_path)
        if _plan_only(request.input):
            return self._plan_only_result(
                request=request,
                plan=plan,
                model_configured=model_configured,
                clone_requested=clone_requested,
            )

        if not model_configured:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                output={
                    "schema": VOICEOVER_PLAN_SCHEMA,
                    "operation": "generate_voiceover",
                    "reason_code": "tts.model_unconfigured",
                    "plan_available": True,
                    "voiceover_plan": plan,
                    "model_runtime": _model_runtime_public(
                        configured=False,
                        reason_code="tts.model_unconfigured",
                    ),
                },
                usage_metrics=_usage_metrics(plan, operation="model_unconfigured"),
                error_code=ErrorCode.ADAPTER_UNAVAILABLE,
                error_message=(
                    "MOSS-TTS-Nano ONNX model path is not configured; use plan_only or configure a local model."
                ),
            )

        return AdapterResult(
            status=AdapterStatus.FAILED,
            output={
                "schema": VOICEOVER_PLAN_SCHEMA,
                "operation": "generate_voiceover",
                "reason_code": "tts.onnx_runtime_not_enabled",
                "plan_available": True,
                "voiceover_plan": plan,
                "model_runtime": _model_runtime_public(
                    configured=True,
                    reason_code="tts.onnx_runtime_not_enabled",
                ),
            },
            usage_metrics=_usage_metrics(plan, operation="onnx_runtime_not_enabled"),
            error_code=ErrorCode.ADAPTER_UNAVAILABLE,
            error_message=(
                "MOSS-TTS-Nano ONNX CPU execution is not enabled in this local P1 adapter skeleton."
            ),
        )

    def _plan_only_result(
        self,
        *,
        request: AdapterRequest,
        plan: Mapping[str, Any],
        model_configured: bool,
        clone_requested: bool,
    ) -> AdapterResult:
        manifest = build_voiceover_manifest_payload(
            request=request,
            plan=plan,
            model_configured=model_configured,
            clone_requested=clone_requested,
        )
        artifact_refs: tuple[ArtifactRef, ...] = ()
        output: dict[str, Any] = {
            "schema": VOICEOVER_PLAN_SCHEMA,
            "operation": "generate_voiceover",
            "synthesis_mode": "plan_only",
            "voiceover_plan": plan,
            "voiceover_manifest": manifest,
            "model_runtime": _model_runtime_public(
                configured=model_configured,
                reason_code="tts.plan_only",
            ),
            "audio_artifact_ref": None,
        }

        artifact_store = _artifact_store(request.input)
        if artifact_store is not None and _truthy(request.input.get("emit_manifest_artifact")):
            manifest_ref = artifact_store.put_bytes(
                content=voiceover_manifest_artifact_bytes(manifest),
                artifact_type=VOICEOVER_MANIFEST_ARTIFACT_TYPE,
                owner_tenant_id=request.context.tenant_id,
                created_by_run_id=request.context.run_id,
                filename="voiceover_manifest.json",
                mime_type="application/json",
            )
            artifact_refs = (manifest_ref,)
            output["voiceover_manifest_artifact_ref"] = manifest_ref.to_public_dict()

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output=output,
            artifact_refs=artifact_refs,
            usage_metrics=_usage_metrics(plan, operation="plan_only"),
        )


def build_voiceover_plan(
    request: AdapterRequest,
    *,
    clone_requested: bool = False,
) -> dict[str, Any] | None:
    segments = _normalize_segments(request.input)
    if not segments:
        return None

    total_duration = round(max(segment["end_seconds"] for segment in segments), 3)
    sample_rate_hz = _bounded_int(request.input.get("sample_rate_hz"), default=24000, minimum=8000, maximum=48000)
    audio_format = _audio_format(request.input.get("output_format", request.input.get("format")))
    voice_profile = _voice_profile(request.input, clone_requested=clone_requested)
    estimated_output_bytes = int(total_duration * sample_rate_hz * 2)

    return {
        "schema": VOICEOVER_PLAN_SCHEMA,
        "project_id": _safe_label(request.context.project_id, default="project_unset"),
        "run_id": _safe_label(request.context.run_id, default="run_unset"),
        "capability": GENERATE_VOICEOVER,
        "provider": "MOSS-TTS-Nano",
        "runtime": "onnx_cpu",
        "synthesis_mode": "plan_only",
        "voice_profile": voice_profile,
        "audio_format": audio_format,
        "sample_rate_hz": sample_rate_hz,
        "segment_count": len(segments),
        "total_duration_seconds": total_duration,
        "estimated_output_bytes": estimated_output_bytes,
        "segments": segments,
        "render_steps": (
            "normalize_script",
            "prepare_voice_profile",
            "synthesize_segments",
            "assemble_voiceover_track",
            "write_audio_artifact_ref",
        ),
    }


def build_voiceover_manifest_payload(
    *,
    request: AdapterRequest,
    plan: Mapping[str, Any],
    model_configured: bool,
    clone_requested: bool,
) -> dict[str, Any]:
    return {
        "schema": VOICEOVER_MANIFEST_SCHEMA,
        "toolkit_id": TOOLKIT_ID,
        "capability": GENERATE_VOICEOVER,
        "project_id": _safe_label(request.context.project_id, default="project_unset"),
        "run_id": _safe_label(request.context.run_id, default="run_unset"),
        "synthesis_mode": "plan_only",
        "voice_clone_requested": bool(clone_requested),
        "model_runtime": _model_runtime_public(
            configured=model_configured,
            reason_code="tts.plan_only",
        ),
        "voiceover_plan": dict(plan),
        "audio_artifact_ref": None,
    }


def voiceover_manifest_artifact_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def build_runtime_preflight(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    runtime_check = _onnxruntime_cpu_check()
    bundle_check = _bundle_preflight_check(input_payload)
    checks = [runtime_check, *bundle_check["checks"]]

    blocked = [check for check in checks if check["status"] == "blocked"]
    unknown = [check for check in checks if check["status"] == "unknown"]
    if blocked:
        status = "blocked"
        reason_code = blocked[0]["reason_code"]
    elif unknown:
        status = "unknown"
        reason_code = unknown[0]["reason_code"]
    else:
        status = "passed"
        reason_code = "tts.preflight_passed"

    return {
        "schema": "video_editing_toolkit.tts_runtime_preflight.v0",
        "provider": "MOSS-TTS-Nano",
        "backend": "onnx_cpu",
        "status": status,
        "reason_code": reason_code,
        "execution_enabled": False,
        "checks": checks,
        "bundle_summary": bundle_check["bundle_summary"],
    }


def _normalize_segments(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_segments = input_payload.get("segments")
    if isinstance(raw_segments, Sequence) and not isinstance(raw_segments, (str, bytes, bytearray)):
        return _segments_from_sequence(raw_segments)

    text = input_payload.get("text", input_payload.get("script"))
    if not isinstance(text, str) or not text.strip():
        return []

    start_seconds = _seconds(input_payload.get("start_seconds"), default=0.0)
    duration = _seconds(
        input_payload.get("duration_seconds"),
        default=_duration_hint_seconds(text),
        minimum=0.1,
    )
    return [
        {
            "segment_id": "seg_0001",
            "start_seconds": start_seconds,
            "end_seconds": round(start_seconds + duration, 3),
            "duration_seconds": round(duration, 3),
            "text_preview": _safe_text(text),
            "text_sha256": _text_hash(text),
        }
    ]


def _segments_from_sequence(raw_segments: Sequence[Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    cursor = 0.0
    for index, item in enumerate(raw_segments, start=1):
        if isinstance(item, str):
            text = item
            start = cursor
            duration = _duration_hint_seconds(text)
        elif isinstance(item, Mapping):
            text = item.get("text", item.get("script"))
            if not isinstance(text, str) or not text.strip():
                continue
            start = _seconds(
                item.get("start_seconds", item.get("start")),
                default=cursor,
            )
            end_hint = _seconds(item.get("end_seconds", item.get("end")), default=None)
            duration = _seconds(item.get("duration_seconds", item.get("duration")), default=None)
            if duration is None and end_hint is not None:
                duration = max(0.1, end_hint - start)
            if duration is None:
                duration = _duration_hint_seconds(text)
        else:
            continue

        duration = round(max(0.1, duration), 3)
        end = round(start + duration, 3)
        segments.append(
            {
                "segment_id": f"seg_{index:04d}",
                "start_seconds": round(start, 3),
                "end_seconds": end,
                "duration_seconds": duration,
                "text_preview": _safe_text(text),
                "text_sha256": _text_hash(text),
            }
        )
        cursor = end
    return segments


def _voice_profile(input_payload: Mapping[str, Any], *, clone_requested: bool) -> dict[str, Any]:
    voice = input_payload.get("voice")
    voice_payload = voice if isinstance(voice, Mapping) else {}
    language = _safe_label(
        input_payload.get("language", voice_payload.get("language")),
        default="zh-CN",
    )
    return {
        "voice_mode": "voice_clone_approved" if clone_requested else "preset",
        "language": language,
        "preset": _safe_label(
            input_payload.get("voice_preset", voice_payload.get("preset")),
            default="default_narrator",
        ),
        "style": _safe_label(input_payload.get("style", voice_payload.get("style")), default="neutral"),
        "pace": _safe_label(input_payload.get("pace", voice_payload.get("pace")), default="normal"),
        "pitch": _safe_label(input_payload.get("pitch", voice_payload.get("pitch")), default="normal"),
    }


def _voice_clone_requested(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in {"consent_policy", "approval_context", "policy_context"}:
                continue
            if normalized == "clone" and _truthy(child):
                return True
            if any(part in normalized for part in _CLONE_KEY_PARTS):
                return True
            if _voice_clone_requested(child):
                return True
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_voice_clone_requested(child) for child in value)
    return False


def _high_sensitivity_policy(request: AdapterRequest) -> dict[str, Any]:
    policy: dict[str, Any] = {}
    context_policy = request.context.policy_context
    if isinstance(context_policy, Mapping):
        policy.update(_mapping(context_policy.get("data_policy")))
        policy.update(_mapping(context_policy.get("high_sensitivity_policy")))
    policy.update(_mapping(request.input.get("policy")))
    policy.update(_mapping(request.input.get("high_sensitivity_policy")))
    return policy


def _approval_context(request: AdapterRequest) -> dict[str, Any]:
    approval: dict[str, Any] = {}
    context_policy = request.context.policy_context
    if isinstance(context_policy, Mapping):
        approval.update(_mapping(context_policy.get("approval_context")))
    approval.update(_mapping(request.input.get("approval_context")))
    return approval


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _plan_only(input_payload: Mapping[str, Any]) -> bool:
    mode = input_payload.get("synthesis_mode", input_payload.get("mode"))
    return mode == "plan_only" or _truthy(input_payload.get("dry_run"))


def _preflight_only(input_payload: Mapping[str, Any]) -> bool:
    mode = input_payload.get("synthesis_mode", input_payload.get("mode"))
    return mode == "preflight_only" or _truthy(input_payload.get("preflight_only"))


def _configured_model_path(input_payload: Mapping[str, Any]) -> str | None:
    for key in _MODEL_PATH_INPUT_KEYS:
        value = input_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for env_var in _MODEL_PATH_ENV_VARS:
        value = os.environ.get(env_var)
        if value:
            return value
    return None


def _configured_bundle_paths(input_payload: Mapping[str, Any]) -> dict[str, Path | None]:
    model_root = _configured_path_value(input_payload, _MODEL_ROOT_INPUT_KEYS, _MODEL_ROOT_ENV_VARS)
    tts_bundle = _configured_path_value(input_payload, _TTS_BUNDLE_INPUT_KEYS, _TTS_BUNDLE_ENV_VARS)
    codec_bundle = _configured_path_value(input_payload, _CODEC_BUNDLE_INPUT_KEYS, _CODEC_BUNDLE_ENV_VARS)

    root_path = Path(model_root) if model_root else None
    return {
        "model_root": root_path,
        "tts_bundle": Path(tts_bundle)
        if tts_bundle
        else (root_path / _TTS_BUNDLE_DIRNAME if root_path is not None else None),
        "codec_bundle": Path(codec_bundle)
        if codec_bundle
        else (root_path / _CODEC_BUNDLE_DIRNAME if root_path is not None else None),
    }


def _configured_path_value(
    input_payload: Mapping[str, Any],
    input_keys: Sequence[str],
    env_vars: Sequence[str],
) -> str | None:
    for key in input_keys:
        value = input_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for env_var in env_vars:
        value = os.environ.get(env_var)
        if value:
            return value
    return None


def _onnxruntime_cpu_check() -> dict[str, Any]:
    try:
        runtime = importlib.import_module("onnxruntime")
    except ImportError:
        return {
            "name": "onnxruntime_cpu",
            "status": "blocked",
            "reason_code": "tts.onnxruntime_missing",
            "details": {"importable": False, "cpu_execution_provider": False},
        }

    providers_getter = getattr(runtime, "get_available_providers", None)
    if not callable(providers_getter):
        return {
            "name": "onnxruntime_cpu",
            "status": "unknown",
            "reason_code": "tts.onnxruntime_provider_unknown",
            "details": {"importable": True, "cpu_execution_provider": "unknown"},
        }

    try:
        providers = providers_getter()
    except Exception:
        return {
            "name": "onnxruntime_cpu",
            "status": "unknown",
            "reason_code": "tts.onnxruntime_provider_unknown",
            "details": {"importable": True, "cpu_execution_provider": "unknown"},
        }

    cpu_available = "CPUExecutionProvider" in providers
    return {
        "name": "onnxruntime_cpu",
        "status": "passed" if cpu_available else "blocked",
        "reason_code": "tts.onnxruntime_cpu_available" if cpu_available else "tts.onnxruntime_cpu_provider_missing",
        "details": {
            "importable": True,
            "cpu_execution_provider": cpu_available,
            "provider_count": len(providers) if isinstance(providers, Sequence) else None,
        },
    }


def _bundle_preflight_check(input_payload: Mapping[str, Any]) -> dict[str, Any]:
    paths = _configured_bundle_paths(input_payload)
    tts_check = _required_files_check(
        bundle_name="tts_bundle",
        bundle_path=paths["tts_bundle"],
        required_files=_TTS_BUNDLE_REQUIRED_FILES,
    )
    codec_check = _required_files_check(
        bundle_name="codec_bundle",
        bundle_path=paths["codec_bundle"],
        required_files=_CODEC_BUNDLE_REQUIRED_FILES,
    )
    return {
        "checks": [tts_check, codec_check],
        "bundle_summary": {
            "configured": paths["tts_bundle"] is not None and paths["codec_bundle"] is not None,
            "model_root_configured": paths["model_root"] is not None,
            "tts_bundle": _bundle_public_summary(tts_check),
            "codec_bundle": _bundle_public_summary(codec_check),
        },
    }


def _required_files_check(
    *,
    bundle_name: str,
    bundle_path: Path | None,
    required_files: Sequence[str],
) -> dict[str, Any]:
    if bundle_path is None:
        return {
            "name": bundle_name,
            "status": "blocked",
            "reason_code": f"tts.{bundle_name}_unconfigured",
            "required_file_count": len(required_files),
            "present_file_count": 0,
            "missing_required_files": list(required_files),
        }

    present = [filename for filename in required_files if (bundle_path / filename).is_file()]
    missing = [filename for filename in required_files if filename not in present]
    return {
        "name": bundle_name,
        "status": "passed" if not missing else "blocked",
        "reason_code": f"tts.{bundle_name}_complete" if not missing else f"tts.{bundle_name}_incomplete",
        "required_file_count": len(required_files),
        "present_file_count": len(present),
        "missing_required_files": missing,
    }


def _bundle_public_summary(check: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "configured": not str(check.get("reason_code", "")).endswith("_unconfigured"),
        "complete": check.get("status") == "passed",
        "required_file_count": check.get("required_file_count", 0),
        "present_file_count": check.get("present_file_count", 0),
        "missing_required_files": list(check.get("missing_required_files", ())),
    }


def _model_runtime_public(*, configured: bool, reason_code: str) -> dict[str, Any]:
    return {
        "provider": "MOSS-TTS-Nano",
        "backend": "onnx_cpu",
        "model_configured": bool(configured),
        "downloads_disabled_by_default": True,
        "network_access": "disabled_by_contract",
        "execution_enabled": False,
        "reason_code": reason_code,
    }


def _artifact_store(input_payload: Mapping[str, Any]) -> LocalArtifactStore | None:
    artifact_store = input_payload.get("_artifact_store")
    if isinstance(artifact_store, LocalArtifactStore):
        return artifact_store
    return None


def _usage_metrics(plan: Mapping[str, Any], *, operation: str) -> dict[str, Any]:
    return {
        "worker": "moss-tts-nano",
        "operation": operation,
        "segment_count": int(plan.get("segment_count", 0) or 0),
        "estimated_output_bytes": int(plan.get("estimated_output_bytes", 0) or 0),
    }


def _audio_format(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.lower().lstrip(".")
        if normalized in {"wav", "mp3", "flac", "ogg", "m4a"}:
            return normalized
    return "wav"


def _duration_hint_seconds(text: str) -> float:
    cjk_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    words = len(re.findall(r"[A-Za-z0-9]+", text))
    punctuation_pause = min(4, sum(1 for char in text if char in ",.;:!?") * 0.12)
    estimated = (cjk_chars / 4.2) + (words / 2.8) + punctuation_pause
    return round(max(0.8, estimated), 3)


def _seconds(value: Any, *, default: float | None, minimum: float = 0.0) -> float | None:
    if value is None:
        return default
    if not isinstance(value, (int, float)):
        return default
    return round(max(minimum, float(value)), 3)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(minimum, min(maximum, int(value)))
    return default


def _safe_text(value: str) -> str:
    rendered = " ".join(value.strip().split())
    for pattern in _LOCAL_PATH_PATTERNS:
        rendered = pattern.sub("[redacted-path]", rendered)
    rendered = _SECRET_ASSIGNMENT_PATTERN.sub("[redacted-secret]", rendered)
    if len(rendered) > _MAX_TEXT_PREVIEW_CHARS:
        rendered = f"{rendered[:_MAX_TEXT_PREVIEW_CHARS].rstrip()}..."
    return rendered


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_label(value: Any, *, default: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return default
    rendered = _SAFE_LABEL_PATTERN.sub("_", value.strip())[:80].strip("._:-")
    return rendered or default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    return False
