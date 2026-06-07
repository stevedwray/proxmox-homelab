FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY client.py discover.py mikrotik_client.py proxmox_client.py populate.py /app/

RUN pip install --no-cache-dir pyyaml

ENTRYPOINT ["python3", "/app/populate.py"]
