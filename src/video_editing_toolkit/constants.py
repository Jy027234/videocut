"""Shared constants for toolkit ids, statuses, and data classes."""

P0_TOOLKIT_IDS = (
    "video.asset_ingest",
    "video.analysis",
    "audio.speech",
    "video.project_edit",
    "video.render",
    "video.delivery",
)

RUN_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")

DATA_CLASSES = ("public", "internal", "sensitive", "biometric", "voice")

