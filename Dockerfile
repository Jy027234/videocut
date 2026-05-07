FROM python:3.13-slim AS toolkit

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIDEO_TOOLKIT_DATA_DIR=/workspace/.video-toolkit-data

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
COPY fixtures ./fixtures
COPY schemas ./schemas
COPY manifests ./manifests

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[dev]"

CMD ["pytest"]

FROM toolkit AS analysis

RUN python -m pip install -e ".[analysis]" \
    && python -m pip install --no-deps "scenedetect>=0.6.4"

ENV VIDEO_TOOLKIT_WORKER_PROFILE=analysis

CMD ["python", "-c", "import cv2; import scenedetect; print('analysis image ready')"]

FROM toolkit AS speech

RUN python -m pip install -e ".[speech]"

ENV VIDEO_TOOLKIT_WORKER_PROFILE=speech \
    WHISPER_CACHE_DIR=/workspace/.video-toolkit-data/whisper-cache \
    VET_WHISPER_MODEL_DIR=/workspace/.video-toolkit-data/whisper-cache

CMD ["python", "-c", "import os; print('speech profile ready; whisper cache:', os.environ.get('WHISPER_CACHE_DIR'))"]
