# syntax=docker/dockerfile:1
FROM python:3.13-slim

# Install system dependencies: ffmpeg is required for audio processing
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Prevent Python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e "."

# Copy application code only (config is mounted as a volume at runtime)
COPY src/ src/

# Expose the web server port
EXPOSE 3000

# Runtime volumes (mounted via docker-compose):
# - /app/config  -> user-editable config (feeds.yaml, settings.yml)
# - /app/podcasts -> persistent download/processed audio state
VOLUME ["/app/config", "/app/podcasts"]

ENTRYPOINT ["python", "-u", "src/main.py"]
