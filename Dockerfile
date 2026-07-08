# Hugging Face Spaces — Agent Chat App (self-contained: bundles PostgreSQL)
#
# Single-stage build for reliability on HF Spaces.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/backend

WORKDIR /app/backend

# Install system deps: PostgreSQL (default version), curl, build-essential.
# python:3.12-slim is based on Debian Trixie which ships PostgreSQL 18.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      postgresql \
      postgresql-client \
      curl \
      build-essential \
      libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Symlink postgres binaries (version may vary across Debian releases).
RUN PG_BIN_DIR=$(ls -d /usr/lib/postgresql/*/bin | head -1) && \
    ln -sf "$PG_BIN_DIR/pg_ctl" /usr/local/bin/pg_ctl && \
    ln -sf "$PG_BIN_DIR/initdb" /usr/local/bin/initdb && \
    ln -sf "$PG_BIN_DIR/postgres" /usr/local/bin/postgres && \
    ln -sf "$PG_BIN_DIR/psql" /usr/local/bin/psql && \
    ln -sf "$PG_BIN_DIR/createdb" /usr/local/bin/createdb && \
    ln -sf "$PG_BIN_DIR/pg_isready" /usr/local/bin/pg_isready

# Install uv for fast Python dependency resolution.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

# Copy the project files.
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/cli ./cli
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini

# Install Python deps via uv (no dev deps).
RUN uv sync --no-dev

# Copy entrypoint as root and chmod BEFORE switching to non-root user
# (otherwise chmod fails with "Operation not permitted" on root-owned file).
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create the non-root HF Spaces user (UID 1000) — but DON'T switch to it.
# HF Spaces officially recommends UID 1000, but empirical testing on this
# account showed that non-root containers never bind to port 7860 (the
# Space stays stuck at APP_STARTING with zero stdout in the run logs).
# Running as root (matching the working OnyxAgent Space on the same account)
# is the pragmatic choice. We still create appuser so the dirs are owned
# correctly for any future switch to non-root.
RUN useradd -m -u 1000 appuser && \
    mkdir -p /home/appuser/pg /home/appuser/media /home/appuser/data /home/appuser/models_cache && \
    chown -R appuser:appuser /app /home/appuser /entrypoint.sh
ENV PATH="/app/backend/.venv/bin:$PATH"
ENV HOME=/root

EXPOSE 7860

# No HEALTHCHECK — HF Spaces determines readiness by checking if port 7860
# accepts TCP connections. A HEALTHCHECK that hits /api/v1/health can fail
# during the boot window (before FastAPI is up) and cause HF to mark the
# Space as unhealthy even though the app is still starting.

# Rely on the #!/bin/bash shebang (matches OnyxAgent's working setup).
ENTRYPOINT ["/entrypoint.sh"]
