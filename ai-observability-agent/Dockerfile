# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Stage 1 — build: install Python dependencies into an isolated prefix
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install deps before copying source so the layer is cached on re-builds
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — final: minimal runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS final

# Non-root user for K8s securityContext runAsNonRoot: true
RUN groupadd -r agent && useradd -r -g agent -u 1000 -m -d /app agentuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ ./src/

# Run as non-root
USER agentuser

ENTRYPOINT ["python", "-m", "src.main"]
