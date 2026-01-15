FROM python:3.12-alpine

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY server.py /app/server.py

# Data directory for iCloud cookies/session persistence
RUN mkdir -p /data/icloud
VOLUME ["/data"]

# Defaults; override via env or compose
ENV SCHEDULE_INTERVAL_MINUTES=5 \
    LOG_LEVEL=INFO

CMD ["python", "-u", "/app/server.py"]
