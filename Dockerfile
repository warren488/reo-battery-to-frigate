FROM python:3.12-slim

# Install FFmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Log lines appear in `docker compose logs` immediately instead of on
# Python's stdout-buffer schedule
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependency layer — only invalidated when pyproject.toml changes
COPY pyproject.toml .
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Project layer — changes on every source edit, deps above stay cached
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .

# Default watch dir and params-persistence dir (normally volume-mounted)
RUN mkdir -p /watch /data

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://localhost:{os.environ.get('WEB_PORT', '5000')}/api/config\", timeout=3)"

CMD ["reo-bridge"]
