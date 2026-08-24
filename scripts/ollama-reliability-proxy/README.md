# ollama-reliability-proxy

A small reverse proxy protecting against this project's own documented,
repeated Ollama corruption bugs (degenerate empty responses, dense
content degenerating into `?` garbage) that no Ollama client has any
protection against on its own. See `proxy.py`'s module docstring for the
full design and the one known UX tradeoff (streaming responses arrive as
one chunk, not incrementally — see "Known limitation" there).

Stdlib-only — no pip install needed.

## Deployment: centralized on `ai-services-stack` (as of 2026-08-25)

Runs as a Docker Compose service (`ollama-reliability-proxy`) on
`ai-services-stack` (`192.168.50.11`, `ai_seg`), deployed via
`deploy-ai-services-stack.yml` — not a per-workstation process. This
means every consumer of Ollama on that LXC gets the protection,
`OpenWebUI` included, not just an external client. See
`docs/coding-stack/plan.md` Phase 6 for the full history (it started as a
workstation-local process, then was deliberately centralized here).

- Internal (compose network): `http://ollama-reliability-proxy:11435` —
  this is what `OpenWebUI`'s `OLLAMA_BASE_URL` actually points at.
- External (e.g. VS Code Copilot on the operator's workstation):
  `http://192.168.50.11:11435` — needs the `lan -> ai_seg:11435`
  MikroTik rule documented in `terraform/lxc/stacks/ai-services-stack/STACK_CONTRACT.md`.

Refresh it the same way as the rest of `ai-services-stack`:
`./with-secrets-prod scripts/provision.sh --stack ai-services-stack`
(production mutation — needs `TASK_APPROVAL` + the usual approval flow,
see `CLAUDE.md`).

## Point Copilot at it

`~/.config/Code/User/chatLanguageModels.json`'s model `url` should be
`http://192.168.50.11:11435/v1/chat/completions`.

## Running it standalone (e.g. for local testing without touching prod)

```bash
OLLAMA_UPSTREAM=http://framework.gibbsgreatly.xyz:11434 \
    python3 scripts/ollama-reliability-proxy/proxy.py
```

Listens on `127.0.0.1:11435` by default (`PROXY_HOST`/`PROXY_PORT` env
vars to change). Useful for iterating on `proxy.py` itself before
redeploying the centralized version — not meant as an alternative
long-term deployment target.
