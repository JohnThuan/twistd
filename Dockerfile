# syntax=docker/dockerfile:1

# Base image pinned by digest for reproducible builds; Dependabot bumps it.
ARG PYTHON_IMAGE=python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

# --- builder: compile wheels (kociemba ships a C extension built via cffi) ---
FROM ${PYTHON_IMAGE} AS builder
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev libffi-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt requirements-dev.txt constraints.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-dev.txt -c constraints.txt

# --- base: runtime deps + app code, no compiler ---
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt constraints.txt ./
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-index --find-links /wheels -r requirements.txt -c constraints.txt
RUN useradd --create-home --uid 10001 app
COPY twistd ./twistd
# Build the teaching methods' lookup tables once, at image build time (~25 s), so
# containers start in ~0.1 s. Owned by root: read-only to the app at runtime.
ENV TWISTD_TABLE_DIR=/app/tables
RUN python -c "from twistd.methods.registry import warmup; warmup()"

# --- test: `docker build --target test -t twistd-test . && docker run --rm twistd-test` ---
FROM base AS test
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-index --find-links /wheels -r requirements-dev.txt -c constraints.txt
COPY pyproject.toml ./
COPY tests ./tests
COPY scripts ./scripts
USER app
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

# --- runtime (default target) ---
FROM base AS runtime
# Nothing installs packages at runtime; drop the installers to shrink the attack surface.
RUN pip uninstall -y pip setuptools wheel 2>/dev/null || true
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# --no-access-log: the app logs its own structured line per solve, without client IPs.
# --limit-concurrency: hard cap on open connections/tasks before uvicorn returns 503.
CMD ["uvicorn", "twistd.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--no-server-header", "--no-access-log", "--limit-concurrency", "2048", \
     "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "20"]
