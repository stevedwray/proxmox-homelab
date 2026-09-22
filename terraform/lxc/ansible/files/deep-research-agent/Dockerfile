# deep-research-agent -- built locally on the host from source copied by
# the ansible controller (same pattern as this LXC's cve-mcp-server /
# docs-rag-mcp services). See docs/deep-research/plan.md Phase 4.
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 app
WORKDIR /home/app

COPY pyproject.toml README.md ./
COPY src ./src

# config/session/workspace state lands under ~/.deep-research-agent
# (src/config.py resolves this from $HOME, no code change needed) --
# owned by 'app', never /root. Pre-created here (not left to the app's
# own os.makedirs on first run) so the compose-level named volume
# mounted at this exact path inherits correct ownership on first mount,
# same trick this repo's own volume comments already describe. Real bug
# found and fixed 2026-09-22: the volume used to mount at /home/app
# itself (the whole home dir, not just this subdir), which meant every
# image rebuild's fresh COPY src ./src was silently shadowed at runtime
# by whatever was already sitting in that persistent volume from the
# very first deploy -- every code change since Stage B's initial deploy
# was being ignored. Narrowing the mount to just this state directory
# is the actual fix; see docs/deep-research/current-state.md.
RUN pip install --no-cache-dir . \
    && mkdir -p /home/app/.deep-research-agent \
    && chown app:app /home/app/.deep-research-agent

USER app

ENV HOME=/home/app

EXPOSE 8090

# --host/--port/--public-url are set via the compose service's `command:`
# override, not baked in here, so this image stays reusable if the
# published port or public hostname ever changes.
CMD ["python", "src/app.py", "--web", "--host", "0.0.0.0", "--port", "8090", "--auto-approve"]
