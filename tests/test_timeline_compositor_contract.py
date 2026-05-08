"""P0 timeline compositor contract tests."""

from __future__ import annotations

from video_editing_toolkit.project_edit.compositor import build_composition_plan


def test_compositor_flattens_multitrack_timeline_with_diagnostics() -> None:
    plan = build_composition_plan(
        {
            "tracks": {
                "v1": {
                    "kind": "video",
                    "clips": [
                        {
                            "clip_id": "clip_a",
                            "kind": "video",
                            "timeline_start_seconds": 0.0,
                            "duration_seconds": 4.0,
                            "source_in_seconds": 1.0,
                            "source_out_seconds": 5.0,
                            "asset_ref": {"artifact_id": "art_video_a"},
                            "effects": [
                                {
                                    "effect_id": "registered.brightness",
                                    "parameters": {"amount": 0.1},
                                }
                            ],
                        },
                        {
                            "clip_id": "clip_b",
                            "kind": "video",
                            "timeline_start_seconds": 3.5,
                            "duration_seconds": 2.5,
                            "source_in_seconds": 0.0,
                            "source_out_seconds": 2.5,
                            "asset_ref": {"artifact_id": "art_video_b"},
                        },
                    ],
                },
                "a1": {
                    "kind": "audio",
                    "clips": [
                        {
                            "clip_id": "music",
                            "kind": "audio",
                            "timeline_start_seconds": 0.0,
                            "duration_seconds": 8.0,
                            "source_in_seconds": 0.0,
                            "source_out_seconds": 8.0,
                            "asset_ref": {"artifact_id": "art_music"},
                        }
                    ],
                },
                "text1": {
                    "kind": "text",
                    "clips": [
                        {
                            "clip_id": "subtitle_tail",
                            "kind": "text",
                            "text": "CTA",
                            "timeline_start_seconds": 5.5,
                            "duration_seconds": 1.5,
                            "style": {"preset": "caption"},
                        }
                    ],
                },
            },
            "transitions": [
                {
                    "clip_id": "clip_b",
                    "transition_id": "registered.crossfade",
                    "duration_seconds": 0.5,
                }
            ],
        },
        render_config={"mode": "preview", "profile": "review", "max_duration_seconds": 5.0},
    )

    assert plan["schema"] == "video_editing_toolkit.composition_plan.v0"
    assert plan["summary"]["duration_seconds"] == 8.0
    assert plan["summary"]["render_duration_seconds"] == 5.0
    assert plan["summary"]["video_clip_count"] == 2
    assert plan["summary"]["audio_clip_count"] == 1
    assert plan["summary"]["text_clip_count"] == 1
    assert plan["video_layers"][0]["track_id"] == "v1"
    assert [clip["clip_id"] for clip in plan["video_layers"][0]["clips"]] == ["clip_a", "clip_b"]
    assert plan["audio_mix"]["strategy"] == "sum_tracks_then_limit"
    assert plan["text_overlays"][0]["clip_id"] == "subtitle_tail"
    assert plan["transitions"][0]["from_clip_id"] == "clip_a"
    assert plan["transitions"][0]["to_clip_id"] == "clip_b"
    assert plan["effects"][0]["effect_id"] == "registered.brightness"

    warning_codes = {warning["code"] for warning in plan["warnings"]}
    assert {
        "track_overlap",
        "text_out_of_video_bounds",
        "audio_video_duration_mismatch",
    }.issubset(warning_codes)
    assert plan["errors"] == []


def test_compositor_reports_negative_duration_without_throwing() -> None:
    plan = build_composition_plan(
        {
            "tracks": {
                "v1": {
                    "kind": "video",
                    "clips": [
                        {
                            "clip_id": "bad_clip",
                            "kind": "video",
                            "timeline_start_seconds": 1.0,
                            "duration_seconds": -2.0,
                        }
                    ],
                }
            },
            "transitions": [],
        }
    )

    assert plan["summary"]["error_count"] == 1
    assert plan["errors"][0]["code"] == "negative_duration"
    assert plan["errors"][0]["clip_id"] == "bad_clip"
