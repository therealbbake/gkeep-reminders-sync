FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application
COPY main.py /app/main.py

# Data directory for iCloud cookies/session persistence
RUN mkdir -p /data/icloud
VOLUME ["/data"]

# Defaults; override via env or compose
ENV SCHEDULE_INTERVAL_MINUTES=5 \
    LOG_LEVEL=INFO

CMD ["python", "-u", "/app/main.py"]
