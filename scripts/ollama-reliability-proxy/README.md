# ollama-reliability-proxy

A small local reverse proxy between VS Code Copilot Chat and Ollama on
`framework.gibbsgreatly.xyz:11434`, protecting against this project's own
documented, repeated Ollama corruption bugs (degenerate empty responses,
dense content degenerating into `?` garbage) that Copilot's own client
has zero protection against. See `proxy.py`'s module docstring for the
full design and the one known UX tradeoff (streaming responses arrive as
one chunk, not incrementally — see "Known limitation" there).

Stdlib-only — no pip install needed to run it.

## Run manually (foreground, for testing)

```bash
OLLAMA_UPSTREAM=http://framework.gibbsgreatly.xyz:11434 \
    python3 scripts/ollama-reliability-proxy/proxy.py
```

## Install as a systemd user service (survives logout/reboot)

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/git/proxmox-homelab/scripts/ollama-reliability-proxy/ollama-reliability-proxy.service \
    ~/.config/systemd/user/ollama-reliability-proxy.service
systemctl --user daemon-reload
systemctl --user enable --now ollama-reliability-proxy.service
loginctl enable-linger "$USER"   # so it also runs when you're not logged in interactively
```

Check it's up: `curl http://127.0.0.1:11435/v1/chat/completions -d '{...}'`
or `systemctl --user status ollama-reliability-proxy`. Logs:
`journalctl --user -u ollama-reliability-proxy -f`.

## Point Copilot at it

Change `~/.config/Code/User/chatLanguageModels.json`'s model `url` from
`http://framework.gibbsgreatly.xyz:11434/v1/chat/completions` to
`http://127.0.0.1:11435/v1/chat/completions`. Nothing else about that
config needs to change — same model id, same token limits.
