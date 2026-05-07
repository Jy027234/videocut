"""Worker adapter contract and P0 adapter registry."""

from .base import (
    CONTRACT_VERSION,
    TOOLKIT_ID,
    AdapterContext,
    AdapterError,
    AdapterRequest,
    AdapterResult,
    AdapterStatus,
    ArtifactRef,
    BaseAdapter,
    PlaceholderAdapter,
)
from .asset_index import AssetIndexAdapter
from .audio_quality import AudioQualityAdapter
from .delivery import DeliveryAdapter
from .ffmpeg import FFmpegAdapter
from .opencv import OpenCVAdapter
from .project_edit import ProjectEditAdapter
from .routing import CAPABILITY_ROUTES, CapabilityRoute, build_adapter, resolve_route
from .scenedetect import PySceneDetectAdapter
from .whisper import WhisperAdapter

__all__ = [
    "CAPABILITY_ROUTES",
    "CONTRACT_VERSION",
    "TOOLKIT_ID",
    "AdapterContext",
    "AdapterError",
    "AdapterRequest",
    "AdapterResult",
    "AdapterStatus",
    "AssetIndexAdapter",
    "AudioQualityAdapter",
    "ArtifactRef",
    "BaseAdapter",
    "CapabilityRoute",
    "DeliveryAdapter",
    "FFmpegAdapter",
    "OpenCVAdapter",
    "PlaceholderAdapter",
    "ProjectEditAdapter",
    "PySceneDetectAdapter",
    "WhisperAdapter",
    "build_adapter",
    "resolve_route",
]
