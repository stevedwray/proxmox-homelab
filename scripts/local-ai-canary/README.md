# local-ai-canary

Standing regression check for the Laguna S 2.1 + Copilot + MCP pipeline
(`docs-rag-mcp`/`cve-mcp` + the reliability proxy). See `canary.py`'s
module docstring for what it checks and why. Requires
`ollama-reliability-proxy` running (see the sibling directory) for the
model-health check.

## One-time setup

```bash
python3 -m venv scripts/local-ai-canary/.venv
scripts/local-ai-canary/.venv/bin/pip install mcp httpx
```

## Run manually

```bash
scripts/local-ai-canary/.venv/bin/python scripts/local-ai-canary/canary.py
```

Exit code 0 = all checks passed, 1 = at least one failed (see the
`[FAIL] ...` line(s) for which).

## Install as a scheduled systemd user timer (every 6 hours)

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/git/proxmox-homelab/scripts/local-ai-canary/local-ai-canary.service \
    ~/.config/systemd/user/local-ai-canary.service
ln -sf ~/git/proxmox-homelab/scripts/local-ai-canary/local-ai-canary.timer \
    ~/.config/systemd/user/local-ai-canary.timer
systemctl --user daemon-reload
systemctl --user enable --now local-ai-canary.timer
```

Check results: `journalctl --user -u local-ai-canary -f` (a `oneshot`
service logs each run's PASS/FAIL lines; a failed run shows up as a
failed systemd unit, visible via `systemctl --user --failed`).
