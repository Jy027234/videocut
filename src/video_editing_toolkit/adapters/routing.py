"""Capability routing for P0 worker adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Type

from video_editing_toolkit.resource_guard import ResourceLimits

from .asset_index import AssetIndexAdapter
from .audio_quality import AudioQualityAdapter
from .base import BaseAdapter
from .delivery import DeliveryAdapter
from .ffmpeg import FFmpegAdapter
from .opencv import OpenCVAdapter
from .project_edit import ProjectEditAdapter
from .project_export import EXPORT_PROJECT_FORMAT, ProjectExportAdapter
from .qc import BUILD_QC_EVIDENCE_PACKET, GENERATE_QC_REPORT, QCAdapter
from .remotion import RemotionAdapter
from .scenedetect import PySceneDetectAdapter
from .tts import GENERATE_VOICEOVER, TTSAdapter
from .whisper import WhisperAdapter


@dataclass(frozen=True)
class CapabilityRoute:
    capability: str
    adapter_name: str
    adapter_class: Type[BaseAdapter]
    queue_topic: str
    resource_limits: ResourceLimits
    artifact_policy: str = "artifact_ref_only"


CAPABILITY_ROUTES: Mapping[str, CapabilityRoute] = {
    "video.asset_ingest.probe_media": CapabilityRoute(
        capability="video.asset_ingest.probe_media",
        adapter_name=FFmpegAdapter.adapter_name,
        adapter_class=FFmpegAdapter,
        queue_topic="video.asset.probe",
        resource_limits=FFmpegAdapter.default_limits,
    ),
    "video.asset_ingest.normalize_asset": CapabilityRoute(
        capability="video.asset_ingest.normalize_asset",
        adapter_name=FFmpegAdapter.adapter_name,
        adapter_class=FFmpegAdapter,
        queue_topic="video.asset.normalize",
        resource_limits=FFmpegAdapter.default_limits,
    ),
    "video.asset_ingest.extract_audio": CapabilityRoute(
        capability="video.asset_ingest.extract_audio",
        adapter_name=FFmpegAdapter.adapter_name,
        adapter_class=FFmpegAdapter,
        queue_topic="video.asset.normalize",
        resource_limits=FFmpegAdapter.default_limits,
    ),
    "video.asset_ingest.extract_frames": CapabilityRoute(
        capability="video.asset_ingest.extract_frames",
        adapter_name=FFmpegAdapter.adapter_name,
        adapter_class=FFmpegAdapter,
        queue_topic="video.asset.normalize",
        resource_limits=FFmpegAdapter.default_limits,
    ),
    "video.asset_ingest.build_asset_index": CapabilityRoute(
        capability="video.asset_ingest.build_asset_index",
        adapter_name=AssetIndexAdapter.adapter_name,
        adapter_class=AssetIndexAdapter,
        queue_topic="video.asset.index",
        resource_limits=AssetIndexAdapter.default_limits,
    ),
    "video.analysis.detect_scenes": CapabilityRoute(
        capability="video.analysis.detect_scenes",
        adapter_name=PySceneDetectAdapter.adapter_name,
        adapter_class=PySceneDetectAdapter,
        queue_topic="video.analysis.scenedetect",
        resource_limits=PySceneDetectAdapter.default_limits,
    ),
    "video.analysis.analyze_frames": CapabilityRoute(
        capability="video.analysis.analyze_frames",
        adapter_name=OpenCVAdapter.adapter_name,
        adapter_class=OpenCVAdapter,
        queue_topic="video.analysis.opencv",
        resource_limits=OpenCVAdapter.default_limits,
    ),
    "video.analysis.check_visual_quality": CapabilityRoute(
        capability="video.analysis.check_visual_quality",
        adapter_name=OpenCVAdapter.adapter_name,
        adapter_class=OpenCVAdapter,
        queue_topic="video.analysis.opencv",
        resource_limits=OpenCVAdapter.default_limits,
    ),
    "audio.speech.transcribe": CapabilityRoute(
        capability="audio.speech.transcribe",
        adapter_name=WhisperAdapter.adapter_name,
        adapter_class=WhisperAdapter,
        queue_topic="audio.speech.whisper",
        resource_limits=WhisperAdapter.default_limits,
    ),
    "audio.speech.align_subtitles": CapabilityRoute(
        capability="audio.speech.align_subtitles",
        adapter_name=WhisperAdapter.adapter_name,
        adapter_class=WhisperAdapter,
        queue_topic="audio.speech.whisper",
        resource_limits=WhisperAdapter.default_limits,
    ),
    "audio.speech.check_audio_quality": CapabilityRoute(
        capability="audio.speech.check_audio_quality",
        adapter_name=AudioQualityAdapter.adapter_name,
        adapter_class=AudioQualityAdapter,
        queue_topic="audio.speech.quality",
        resource_limits=AudioQualityAdapter.default_limits,
    ),
    "video.project_edit.create_project": CapabilityRoute(
        capability="video.project_edit.create_project",
        adapter_name=ProjectEditAdapter.adapter_name,
        adapter_class=ProjectEditAdapter,
        queue_topic="video.project_edit",
        resource_limits=ProjectEditAdapter.default_limits,
    ),
    "video.project_edit.inspect_assets": CapabilityRoute(
        capability="video.project_edit.inspect_assets",
        adapter_name=ProjectEditAdapter.adapter_name,
        adapter_class=ProjectEditAdapter,
        queue_topic="video.project_edit",
        resource_limits=ProjectEditAdapter.default_limits,
    ),
    "video.project_edit.generate_edit_plan": CapabilityRoute(
        capability="video.project_edit.generate_edit_plan",
        adapter_name=ProjectEditAdapter.adapter_name,
        adapter_class=ProjectEditAdapter,
        queue_topic="video.project_edit",
        resource_limits=ProjectEditAdapter.default_limits,
    ),
    "video.project_edit.apply_timeline_patch": CapabilityRoute(
        capability="video.project_edit.apply_timeline_patch",
        adapter_name=ProjectEditAdapter.adapter_name,
        adapter_class=ProjectEditAdapter,
        queue_topic="video.project_edit",
        resource_limits=ProjectEditAdapter.default_limits,
    ),
    "video.project_edit.render_preview": CapabilityRoute(
        capability="video.project_edit.render_preview",
        adapter_name=ProjectEditAdapter.adapter_name,
        adapter_class=ProjectEditAdapter,
        queue_topic="video.project_edit",
        resource_limits=ProjectEditAdapter.default_limits,
    ),
    "video.project_edit.compare_versions": CapabilityRoute(
        capability="video.project_edit.compare_versions",
        adapter_name=ProjectEditAdapter.adapter_name,
        adapter_class=ProjectEditAdapter,
        queue_topic="video.project_edit",
        resource_limits=ProjectEditAdapter.default_limits,
    ),
    "video.project_edit.rollback_version": CapabilityRoute(
        capability="video.project_edit.rollback_version",
        adapter_name=ProjectEditAdapter.adapter_name,
        adapter_class=ProjectEditAdapter,
        queue_topic="video.project_edit",
        resource_limits=ProjectEditAdapter.default_limits,
    ),
    "video.render.render_preview": CapabilityRoute(
        capability="video.render.render_preview",
        adapter_name=FFmpegAdapter.adapter_name,
        adapter_class=FFmpegAdapter,
        queue_topic="video.render.preview",
        resource_limits=FFmpegAdapter.default_limits,
    ),
    "video.render.render_final": CapabilityRoute(
        capability="video.render.render_final",
        adapter_name=FFmpegAdapter.adapter_name,
        adapter_class=FFmpegAdapter,
        queue_topic="video.render.final",
        resource_limits=FFmpegAdapter.default_limits,
    ),
    "video.delivery.generate_variants": CapabilityRoute(
        capability="video.delivery.generate_variants",
        adapter_name=DeliveryAdapter.adapter_name,
        adapter_class=DeliveryAdapter,
        queue_topic="video.delivery.package",
        resource_limits=DeliveryAdapter.default_limits,
    ),
    "video.delivery.package_artifacts": CapabilityRoute(
        capability="video.delivery.package_artifacts",
        adapter_name=DeliveryAdapter.adapter_name,
        adapter_class=DeliveryAdapter,
        queue_topic="video.delivery.package",
        resource_limits=DeliveryAdapter.default_limits,
    ),
    "video.delivery.create_delivery_manifest": CapabilityRoute(
        capability="video.delivery.create_delivery_manifest",
        adapter_name=DeliveryAdapter.adapter_name,
        adapter_class=DeliveryAdapter,
        queue_topic="video.delivery.package",
        resource_limits=DeliveryAdapter.default_limits,
    ),
}

P1_CAPABILITY_ROUTES: Mapping[str, CapabilityRoute] = {
    GENERATE_VOICEOVER: CapabilityRoute(
        capability=GENERATE_VOICEOVER,
        adapter_name=TTSAdapter.adapter_name,
        adapter_class=TTSAdapter,
        queue_topic="audio.tts.voiceover",
        resource_limits=TTSAdapter.default_limits,
    ),
    "video.template.validate_remotion_template": CapabilityRoute(
        capability="video.template.validate_remotion_template",
        adapter_name=RemotionAdapter.adapter_name,
        adapter_class=RemotionAdapter,
        queue_topic="video.template.remotion",
        resource_limits=RemotionAdapter.default_limits,
    ),
    "video.template.create_remotion_render_job": CapabilityRoute(
        capability="video.template.create_remotion_render_job",
        adapter_name=RemotionAdapter.adapter_name,
        adapter_class=RemotionAdapter,
        queue_topic="video.template.remotion",
        resource_limits=RemotionAdapter.default_limits,
    ),
    GENERATE_QC_REPORT: CapabilityRoute(
        capability=GENERATE_QC_REPORT,
        adapter_name=QCAdapter.adapter_name,
        adapter_class=QCAdapter,
        queue_topic="video.qc.report",
        resource_limits=QCAdapter.default_limits,
    ),
    BUILD_QC_EVIDENCE_PACKET: CapabilityRoute(
        capability=BUILD_QC_EVIDENCE_PACKET,
        adapter_name=QCAdapter.adapter_name,
        adapter_class=QCAdapter,
        queue_topic="video.qc.evidence",
        resource_limits=QCAdapter.default_limits,
    ),
    EXPORT_PROJECT_FORMAT: CapabilityRoute(
        capability=EXPORT_PROJECT_FORMAT,
        adapter_name=ProjectExportAdapter.adapter_name,
        adapter_class=ProjectExportAdapter,
        queue_topic="video.render.project_export",
        resource_limits=ProjectExportAdapter.default_limits,
    ),
}

ALL_CAPABILITY_ROUTES: Mapping[str, CapabilityRoute] = {
    **CAPABILITY_ROUTES,
    **P1_CAPABILITY_ROUTES,
}


def resolve_route(capability: str) -> CapabilityRoute:
    try:
        return CAPABILITY_ROUTES[capability]
    except KeyError as exc:
        raise ValueError(f"No adapter route registered for capability {capability}.") from exc


def build_adapter(capability: str) -> BaseAdapter:
    route = resolve_route(capability)
    return route.adapter_class()


def resolve_p1_experimental_route(capability: str) -> CapabilityRoute:
    """Resolve draft P1 routes through an explicit experimental entrypoint."""

    try:
        return P1_CAPABILITY_ROUTES[capability]
    except KeyError as exc:
        raise ValueError(f"No P1 experimental adapter route registered for capability {capability}.") from exc


def build_p1_experimental_adapter(capability: str) -> BaseAdapter:
    route = resolve_p1_experimental_route(capability)
    return route.adapter_class()
