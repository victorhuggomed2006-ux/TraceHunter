FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRACEHUNTER_HOST=0.0.0.0

# Pull in Debian security fixes (e.g. zlib1g) published after the base image was built.
RUN apt-get update \n    && apt-get upgrade -y --no-install-recommends \n    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY tracehunter ./tracehunter
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir ".[server]" \
    && pip uninstall -y pip setuptools wheel \
    && rm -rf /usr/local/lib/python3.13/ensurepip \
    && useradd --system --uid 10001 --no-create-home tracehunter \
    && mkdir /data && chown tracehunter /data

USER tracehunter
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/traces?limit=1')"]
CMD ["python", "-m", "tracehunter", "/data/tracehunter.db"]
