# ─────────────────────────────────────────────
# AgentOps Hub — Dockerfile
# ─────────────────────────────────────────────
# Multi-stage build:
#   Stage 1 (builder): install deps into a clean layer
#   Stage 2 (runtime): copy only what's needed → smaller final image
# ─────────────────────────────────────────────

# ── Stage 1: Builder ──────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps needed to compile some Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (Docker layer cache — only re-runs if these change)
COPY requirements.txt pyproject.toml ./

# Install into a prefix folder (not system Python)
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: Runtime ─────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY config/       ./config/
COPY rag/          ./rag/
COPY agents/       ./agents/
COPY tools/        ./tools/
COPY evals/        ./evals/
COPY observability/ ./observability/
COPY app/          ./app/
COPY pyproject.toml ./

# Create non-root user (security best practice)
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Traces output dir
RUN mkdir -p traces

# ── Health check ─────────────────────────────
# Pings Ollama every 30s; fails if Ollama isn't reachable
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://ollama:11434/api/tags || exit 1

# ── Entrypoint ───────────────────────────────
# Default: run the CLI. Override in compose for other entry points.
CMD ["python", "app/cli.py"]
