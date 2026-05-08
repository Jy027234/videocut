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
from .project_export import ProjectExportAdapter
from .qc import QCAdapter
from .remotion import RemotionAdapter
from .routing import (
    ALL_CAPABILITY_ROUTES,
    CAPABILITY_ROUTES,
    P1_CAPABILITY_ROUTES,
    CapabilityRoute,
    build_adapter,
    build_p1_experimental_adapter,
    resolve_p1_experimental_route,
    resolve_route,
)
from .scenedetect import PySceneDetectAdapter
from .tts import TTSAdapter
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
    "ProjectExportAdapter",
    "PySceneDetectAdapter",
    "QCAdapter",
    "RemotionAdapter",
    "TTSAdapter",
    "WhisperAdapter",
    "ALL_CAPABILITY_ROUTES",
    "P1_CAPABILITY_ROUTES",
    "build_adapter",
    "build_p1_experimental_adapter",
    "resolve_p1_experimental_route",
    "resolve_route",
]
