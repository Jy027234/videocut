"""Structured delivery adapter."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from video_editing_toolkit.resource_guard import CPU_LIGHT_LIMITS, ErrorCode
from video_editing_toolkit.storage import LocalArtifactStore

from .base import AdapterRequest, AdapterResult, AdapterStatus, BaseAdapter


GENERATE_VARIANTS = "video.delivery.generate_variants"
PACKAGE_ARTIFACTS = "video.delivery.package_artifacts"
CREATE_DELIVERY_MANIFEST = "video.delivery.create_delivery_manifest"


class DeliveryAdapter(BaseAdapter):
    adapter_name = "delivery"
    supported_capabilities = frozenset(
        {
            GENERATE_VARIANTS,
            PACKAGE_ARTIFACTS,
            CREATE_DELIVERY_MANIFEST,
        }
    )
    default_limits = CPU_LIGHT_LIMITS

    def invoke(self, request: AdapterRequest) -> AdapterResult:
        if request.context.capability == GENERATE_VARIANTS:
            return self._generate_variants(request)
        if request.context.capability == PACKAGE_ARTIFACTS:
            return self._package_artifacts(request)
        if request.context.capability == CREATE_DELIVERY_MANIFEST:
            return self._create_delivery_manifest(request)
        return AdapterResult.unsupported(request.context.capability, self.adapter_name)

    def generate_variants(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def package_artifacts(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def create_delivery_manifest(self, request: AdapterRequest) -> AdapterResult:
        return self.handle(request)

    def _generate_variants(self, request: AdapterRequest) -> AdapterResult:
        variants = _variant_plan(request.input)
        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "project_id": request.context.project_id,
                "version": _version(request),
                "variant_count": len(variants),
                "variants": variants,
                "input_artifact_refs": _public_artifact_refs(request.artifact_refs),
            },
            usage_metrics={
                "operation": "generate_variants",
                "variant_count": len(variants),
            },
        )

    def _package_artifacts(self, request: AdapterRequest) -> AdapterResult:
        artifact_store = self._artifact_store(request)
        if artifact_store is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="package_artifacts requires a configured artifact store.",
            )

        variants = _variant_plan(request.input)
        input_refs = _public_artifact_refs(request.artifact_refs)
        manifest = {
            "schema": "video_editing_toolkit.package_manifest.v0",
            "package_mode": "manifest-only",
            "package_note": "P0.5 does not create a zip archive; this artifact lists package inputs only.",
            "project_id": request.context.project_id,
            "version": _version(request),
            "variant_count": len(variants),
            "variants": variants,
            "input_artifact_refs": input_refs,
        }
        artifact_ref = artifact_store.put_bytes(
            content=_json_bytes(manifest),
            artifact_type="package_manifest",
            owner_tenant_id=request.context.tenant_id,
            created_by_run_id=request.context.run_id,
            filename="package_manifest.json",
            mime_type="application/json",
        )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "package_mode": "manifest-only",
                "package_manifest_artifact_ref": artifact_ref.to_public_dict(),
                "artifact_ref": artifact_ref.to_public_dict(),
                "variant_count": len(variants),
                "input_artifact_refs": input_refs,
            },
            artifact_refs=(artifact_ref,),
            usage_metrics={
                "operation": "package_artifacts",
                "output_bytes": artifact_ref.size_bytes,
            },
        )

    def _create_delivery_manifest(self, request: AdapterRequest) -> AdapterResult:
        artifact_store = self._artifact_store(request)
        if artifact_store is None:
            return AdapterResult(
                status=AdapterStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                error_message="create_delivery_manifest requires a configured artifact store.",
            )

        variants = _variant_plan(request.input)
        input_refs = _public_artifact_refs(request.artifact_refs)
        manifest = {
            "schema": "video_editing_toolkit.delivery_manifest.v0",
            "project_id": request.context.project_id,
            "version": _version(request),
            "variant_count": len(variants),
            "variants": variants,
            "input_artifact_refs": input_refs,
        }
        artifact_ref = artifact_store.put_bytes(
            content=_json_bytes(manifest),
            artifact_type="delivery_manifest",
            owner_tenant_id=request.context.tenant_id,
            created_by_run_id=request.context.run_id,
            filename="delivery_manifest.json",
            mime_type="application/json",
        )

        return AdapterResult(
            status=AdapterStatus.SUCCEEDED,
            output={
                "delivery_manifest_artifact_ref": artifact_ref.to_public_dict(),
                "artifact_ref": artifact_ref.to_public_dict(),
                "project_id": request.context.project_id,
                "version": manifest["version"],
                "variant_count": len(variants),
                "variants": variants,
                "input_artifact_refs": input_refs,
            },
            artifact_refs=(artifact_ref,),
            usage_metrics={
                "operation": "create_delivery_manifest",
                "output_bytes": artifact_ref.size_bytes,
            },
        )

    def _artifact_store(self, request: AdapterRequest) -> LocalArtifactStore | None:
        artifact_store = request.input.get("_artifact_store")
        if isinstance(artifact_store, LocalArtifactStore):
            return artifact_store
        return None


def _variant_plan(input_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_variants = input_payload.get("variants")
    if isinstance(raw_variants, list) and raw_variants:
        variants: list[dict[str, Any]] = []
        for index, raw_variant in enumerate(raw_variants, start=1):
            if isinstance(raw_variant, Mapping):
                variants.append(_variant_from_mapping(raw_variant, index))
            elif isinstance(raw_variant, str) and raw_variant:
                variants.append(_variant_from_name(raw_variant, index))
        if variants:
            return variants

    target = input_payload.get("target", input_payload.get("preset", "review"))
    if not isinstance(target, str) or not target:
        target = "review"
    return [_variant_from_name(target, 1)]


def _variant_from_mapping(raw_variant: Mapping[str, Any], index: int) -> dict[str, Any]:
    name = raw_variant.get("name", raw_variant.get("id", f"variant_{index}"))
    if not isinstance(name, str) or not name:
        name = f"variant_{index}"
    variant: dict[str, Any] = {
        "variant_id": _safe_identifier(name, index),
        "name": name,
        "delivery_target": _string_value(raw_variant.get("delivery_target"), "generic"),
    }
    for source_key, output_key in (
        ("format", "format"),
        ("container", "container"),
        ("resolution", "resolution"),
        ("codec", "codec"),
        ("audio_codec", "audio_codec"),
        ("bitrate", "bitrate"),
    ):
        value = raw_variant.get(source_key)
        if isinstance(value, (str, int, float, bool)) and value != "":
            variant[output_key] = value
    return variant


def _variant_from_name(name: str, index: int) -> dict[str, Any]:
    presets = {
        "review": {
            "delivery_target": "review",
            "format": "mp4",
            "resolution": "720p",
        },
        "web": {
            "delivery_target": "web",
            "format": "mp4",
            "resolution": "1080p",
        },
        "archive": {
            "delivery_target": "archive",
            "format": "source",
            "resolution": "source",
        },
    }
    variant = {
        "variant_id": _safe_identifier(name, index),
        "name": name,
    }
    variant.update(presets.get(name.lower(), {"delivery_target": name, "format": "mp4"}))
    return variant


def _public_artifact_refs(refs: Sequence[Any]) -> list[dict[str, Any]]:
    return [_public_artifact_ref(ref) for ref in refs]


def _public_artifact_ref(ref: Any) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in dict(getattr(ref, "metadata", {}) or {}).items()
        if not str(key).startswith("_")
    }
    return {
        "artifact_id": ref.ref,
        "artifact_type": ref.kind,
        "mime_type": ref.media_type,
        "size_bytes": ref.size_bytes,
        "checksum": ref.checksum,
        "data_class": metadata.get("data_class"),
        "retention_policy": metadata.get("retention_policy"),
    }


def _version(request: AdapterRequest) -> str:
    value = request.input.get("project_version", request.input.get("version", request.context.version))
    if isinstance(value, str) and value:
        return value
    return request.context.version


def _safe_identifier(value: str, index: int) -> str:
    safe = "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
    return safe or f"variant_{index}"


def _string_value(value: Any, default: str) -> str:
    if isinstance(value, str) and value:
        return value
    return default


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
