# Shadow APK Gateway — Multi-stage Docker build
# Supports both static-only and full dynamic analysis modes

FROM python:3.11-slim AS base

LABEL maintainer="Shadow APK Gateway Team"
LABEL description="Universal APK-to-Gateway — Extract and serve Android app API endpoints"
LABEL version="1.0.0"

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jdk-headless \
    wget \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install apktool with pinned version
ARG APKTOOL_VERSION=2.9.3
RUN wget -q "https://bitbucket.org/iBotPeaches/apktool/downloads/apktool_${APKTOOL_VERSION}.jar" \
    -O /usr/local/bin/apktool.jar && \
    printf '#!/bin/bash\njava -jar /usr/local/bin/apktool.jar "$@"\n' > /usr/local/bin/apktool && \
    chmod +x /usr/local/bin/apktool

# Create non-root user for security
RUN groupadd -r gateway && useradd -r -g gateway -m -d /home/gateway gateway

WORKDIR /app

# Copy dependency info first for layer caching
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir \
    "pydantic>=2.0,<3.0" \
    "fastapi>=0.110.0" \
    "uvicorn[standard]>=0.27.0" \
    "httpx>=0.27.0" \
    "cryptography>=42.0" \
    "pyyaml>=6.0" \
    "click>=8.1" \
    "rich>=13.0" \
    "openapi-spec-validator>=0.7.0" \
    "python-multipart>=0.0.9"

# Copy application code
COPY . .

# Set ownership to non-root user
RUN chown -R gateway:gateway /app

# Switch to non-root user
USER gateway

# Create output directories
RUN mkdir -p /app/output /app/data

# Set PYTHONPATH
ENV PYTHONPATH=/app

# Expose gateway port
EXPOSE 8080

# Health check against the auth-exempt /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run the gateway
CMD ["uvicorn", "apps.gateway.src.main:app", "--host", "0.0.0.0", "--port", "8080"]
