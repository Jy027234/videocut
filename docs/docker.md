# Docker development environment

This project includes a local Docker environment with Python 3.13, ffmpeg,
ffprobe, and the package installed with its development dependencies.

The default Docker path is intentionally light. It is the P0 local worker
environment for queue/status, artifact store, timeline validation, and FFmpeg
adapter checks. Heavy analysis and speech dependencies are kept behind explicit
Compose profiles and dedicated build targets so they do not become part of every
local test run.

## Build the image

```powershell
docker compose build
```

## Run the default test command

```powershell
docker compose run --rm toolkit
```

The default command is `pytest`.

The default worker image includes `ffmpeg` and `ffprobe`, so the FFmpeg
normalize/render checks generate real MP4 artifacts for `normalized_video`,
`preview_video`, and `final_render`. Host environments without those binaries
should still run the missing-dependency cases and skip the real-output positive
cases.

To pass an explicit command to the same worker image:

```powershell
docker compose run --rm toolkit pytest tests
docker compose run --rm toolkit pytest tests/test_ffmpeg_render_outputs.py
docker compose run --rm toolkit python -m video_editing_toolkit.demo
```

## Check ffmpeg and ffprobe

```powershell
docker compose run --rm toolkit ffmpeg -version
docker compose run --rm toolkit ffprobe -version
```

## Run the demo entry point

```powershell
docker compose run --rm toolkit video-toolkit-demo
```

## Worker profile boundary

`toolkit` is the default worker service. It should stay small and predictable:

- Python 3.13 slim base image
- project package installed in editable mode with development dependencies
- `ffmpeg` and `ffprobe`
- mounted project workspace at `/workspace`
- mounted artifact/data volume at `/workspace/.video-toolkit-data`

Do not add PySceneDetect, OpenCV, Whisper, model weights, GPU runtimes, or other
large media-analysis dependencies to the default image unless the default worker
contract explicitly changes.

`analysis` is an opt-in Compose profile with a dedicated image built from the
`analysis` Dockerfile target. It inherits the default toolkit image, then
installs the `analysis` optional dependency group with OpenCV headless support.
The target then installs PySceneDetect without dependency resolution because the
current package metadata pulls `opencv-python`; the runtime dependencies are
declared in the `analysis` extra so the image keeps the headless OpenCV build:

```powershell
docker compose --profile analysis build analysis
docker compose --profile analysis run --rm analysis
```

Keep this profile locally deployable and independently buildable. Whisper,
GPU/runtime-specific packages, model downloads, and model weight volumes should
still be split into separate images or profiles once their runtime contracts are
clear, instead of being folded into either `toolkit` or the base `analysis`
image.

`speech` is an opt-in Compose profile with a dedicated `speech` Dockerfile
target. It is intentionally a lightweight runtime shell for speech/Whisper work:
it installs only the local package plus the small `speech` optional dependency
group, sets `VIDEO_TOOLKIT_WORKER_PROFILE=speech`, and mounts a dedicated
Whisper cache volume at `/workspace/.video-toolkit-data/whisper-cache`.

The profile does not install `openai-whisper`, Torch, CUDA runtimes, or model
weights by default. Those dependencies are large, runtime-specific, and can
trigger implicit model downloads when used incorrectly. Keep installation and
model selection explicit in local experiments or future derived images:

```powershell
docker compose --profile speech build speech
docker compose --profile speech run --rm speech
```

The cache path is exposed through canonical `VET_WHISPER_MODEL_DIR` and the
compatibility alias `WHISPER_CACHE_DIR` so the adapter, future wrappers, and
manual commands can reuse mounted model files without baking weights into the
image. Model execution still requires `VET_ALLOW_WHISPER=1`; runtime downloads
still require `VET_ALLOW_WHISPER_DOWNLOAD=1`.

`tts` is an optional dependency group for future MOSS-TTS-Nano ONNX CPU work.
It is not installed in the default image and the adapter does not download
models or synthesize audio by default. P1.2 only supports preflight checks for
`onnxruntime` CPU provider availability and a mounted local bundle layout:

```text
MOSS-TTS-Nano-100M-ONNX/
MOSS-Audio-Tokenizer-Nano-ONNX/
```

Point preflight at the parent directory with `VET_MOSS_TTS_NANO_MODEL_ROOT`, or
use explicit `VET_MOSS_TTS_NANO_TTS_BUNDLE` and
`VET_MOSS_TTS_NANO_CODEC_BUNDLE` paths. These paths stay adapter-private and
must not be returned to agents or Platform Core callers.

## Mounted paths

Compose mounts the project directory at `/workspace` and a Docker volume at
`/workspace/.video-toolkit-data`. The `VIDEO_TOOLKIT_DATA_DIR` environment
variable points to that data directory inside the container.

The host working tree is bind-mounted, so local edits are visible inside worker
containers without rebuilding. Rebuild when Dockerfile, package metadata, or
container-level dependencies change.

## Validation

Check that Compose can render the default configuration:

```powershell
docker compose config
```

Check the optional analysis profile configuration:

```powershell
docker compose --profile analysis config
```

Check the optional speech profile configuration:

```powershell
docker compose --profile speech config
```
