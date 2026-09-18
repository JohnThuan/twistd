# syntax=docker/dockerfile:1

# --- builder: compile wheels (kociemba ships a C extension built via cffi) ---
FROM python:3.11-slim AS builder
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev libffi-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt requirements-dev.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-dev.txt

# --- base: runtime deps + app code, no compiler ---
FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-index --find-links /wheels -r requirements.txt
RUN useradd --create-home --uid 10001 app
COPY rubiserve ./rubiserve

# --- test: `docker build --target test -t rubiserve-test . && docker run --rm rubiserve-test` ---
FROM base AS test
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels \
    pip install --no-index --find-links /wheels -r requirements-dev.txt
COPY pyproject.toml ./
COPY tests ./tests
USER app
CMD ["pytest", "-q"]

# --- runtime (default target) ---
FROM base AS runtime
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "rubiserve.main:app", "--host", "0.0.0.0", "--port", "8000"]
