FROM python:3.12-slim

WORKDIR /app

# lxml needs libxml2 and libxslt at build time
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .
