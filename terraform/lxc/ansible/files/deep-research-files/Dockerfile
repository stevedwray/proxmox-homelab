# deep-research-files -- shared reports viewer (Phase 1 of
# docs/reporting-platform/plan.md). Built locally on the host from
# source copied by the ansible controller, same pattern as
# deep-research's own image and mcp-utility-stack's cve-mcp-server/
# docs-rag-mcp.
# /home/app is where the compose service mounts the shared named volume
# read-only -- anything the image puts there gets shadowed by that mount
# at runtime (confirmed live 2026-09-22: serve.py copied to /home/app
# disappeared under the mount, "can't open file '/home/app/serve.py'"
# crash-looping). serve.py lives outside that path instead.
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 app
WORKDIR /opt/app

RUN pip install --no-cache-dir markdown==3.7

COPY serve.py ./serve.py

USER app

EXPOSE 8091

CMD ["python3", "/opt/app/serve.py"]
