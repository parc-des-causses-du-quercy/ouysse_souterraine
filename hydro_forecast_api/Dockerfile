FROM python:3.11-slim

# Install system dependencies for eccodes (GRIB support) and curl (healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libeccodes-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Disable Python stdout buffering so logs appear in Docker/Portainer in real time
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ app/
COPY wsgi.py gunicorn.conf.py ./

# Create directories for runtime data
RUN mkdir -p /app/configs/points /app/states /app/backups /app/data

EXPOSE 5000

# Gunicorn with config file (filters health check noise from access logs)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]
