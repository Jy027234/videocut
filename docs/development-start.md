# Development Start

Date: 2026-05-07

The P0 development scaffold is split by ownership:

```text
manifests/ and schemas/ -> toolkit-manifest-agent
src/video_editing_toolkit/runtime and storage -> local-runtime-gateway + artifact-store-agent
src/video_editing_toolkit/adapters and resource_guard -> adapter-worker-agent
tests/ and fixtures/ -> QA agents
```

Sub-agents must keep file ownership disjoint. The main orchestrator owns project root files, package metadata, and final integration.

