# Stage 1: Build stage — installs gcc/python3-dev for compiling C extensions (scipy, scikit-learn)
FROM python:3.10-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install to user site-packages so they can be copied to the runtime stage cleanly
RUN pip install --user --no-cache-dir -r requirements.txt


# Stage 2: Runtime stage — no build tools, smaller image
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Ensure user-installed packages are on PATH
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application source and data
COPY src/ ./src/
COPY data/ ./data/

EXPOSE 8000

# ALB health check: ECS will mark this task unhealthy if /health stops returning 200
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
