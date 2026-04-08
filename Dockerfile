# Shadow APK Gateway — Multi-stage Docker build
FROM python:3.11-slim AS base

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jdk-headless \
    wget \
    unzip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install apktool
RUN wget -q https://raw.githubusercontent.com/iBotPeaches/Apktool/master/scripts/linux/apktool \
    -O /usr/local/bin/apktool && \
    wget -q https://bitbucket.org/iBotPeaches/apktool/downloads/apktool_2.9.3.jar \
    -O /usr/local/bin/apktool.jar && \
    chmod +x /usr/local/bin/apktool

WORKDIR /app

# Copy dependency info first for layer caching
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[all]" 2>/dev/null || pip install --no-cache-dir \
    pydantic>=2.0 \
    fastapi>=0.109 \
    uvicorn[standard] \
    httpx \
    click \
    rich \
    pyyaml \
    cryptography

# Copy application code
COPY . .

# Expose gateway port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/apps || exit 1

# Run the gateway
CMD ["uvicorn", "apps.gateway.src.main:app", "--host", "0.0.0.0", "--port", "8080"]
