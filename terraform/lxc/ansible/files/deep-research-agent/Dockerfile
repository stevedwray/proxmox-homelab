# deep-research-agent -- built locally on the host from source copied by
# the ansible controller (same pattern as this LXC's cve-mcp-server /
# docs-rag-mcp services). See docs/deep-research/plan.md Phase 4.
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 app
WORKDIR /home/app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

USER app

# config/session/workspace state lands under ~/.deep-research-agent
# (src/config.py resolves this from $HOME, no code change needed) --
# owned by 'app', never /root. Named volume mounts here in compose.
ENV HOME=/home/app

EXPOSE 8090

# --host/--port/--public-url are set via the compose service's `command:`
# override, not baked in here, so this image stays reusable if the
# published port or public hostname ever changes.
CMD ["python", "src/app.py", "--web", "--host", "0.0.0.0", "--port", "8090", "--auto-approve"]
