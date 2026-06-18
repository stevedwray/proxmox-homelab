FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY client.py discover.py flows.py mikrotik_client.py proxmox_client.py populate.py /app/

RUN pip install --no-cache-dir --only-binary :all: pyyaml==6.0.2 \
    && useradd --system --no-create-home appuser

USER appuser

ENTRYPOINT ["python3", "/app/populate.py"]
