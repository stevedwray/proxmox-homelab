# llama-swap on Framework: model control page

Status: **live 2026-10-07.** llama-swap manages :8080; GLM is loaded and is the boot default. Replaces the
2026-10-01 draft on `task/llama-swap-plan`, which put llama-swap in front of
the clients. This version doesn't.

## What it is

A web page for picking which model Framework serves, like Ollama but for any
llama.cpp build:

```
  you ──► https://llm-control.lab.gibbsgreatly.xyz/ui/   (Authentik login → llama-swap: list, load, logs)
                     │ starts one at a time, using the right build + flags
                     ▼
  clients ──► :8080  llama-server  (GLM on upstream, or Qwen on the fork, …)
```

- **llama-swap (v260)** runs as `llama-swap.service` on `:8099`. You reach it
  at `https://llm-control.lab.gibbsgreatly.xyz` and log in with the normal
  Authentik login, which a password manager can fill. llama-swap has no
  login of its own. A small nftables table on framework
  (`files/llama-swap/llama-swap.nft`, loaded by the unit) lets only Traefik
  (192.168.30.10) and framework itself reach :8099, so it can't be opened
  directly. The route is `llm-control` in
  `terraform/lxc/stacks/llm-gpu-stack/edge.yaml`; the DNS record comes from
  `configure-llm-control-dns-records.yml`.
- **Loading a model in the UI** stops whatever llama-swap is running, waits
  for the memory check (`llm-memgate`: MemAvailable ≥ model size + 4 GB), then
  starts that model's `llama-server` on the normal `0.0.0.0:8080` with the
  usual `--api-key-file`.
- **Clients don't change.** CyberSecEval, eval-runner, deep-research, Open
  WebUI, CVE enrichment, Traefik `llm.<domain>` and the metrics scrape all keep
  talking to `llama-server` on :8080 and get whatever is loaded. They can't
  switch models; only the control page does.
- **Saving the config reloads llama-swap and loads the boot default (GLM)**,
  so don't save it while another model is in use or a benchmark is running.
- **Models and builds** live in `/home/steve/llama-swap/config.yaml` (edit in
  VS Code; it reloads on save). Seed copy:
  `ansible/00-initial-setup/files/llama-swap/config.yaml`. The seed has three
  entries:
  - `glm-5.3-flash`: upstream build, same flags as the current hand-run
    process;
  - `qwen3.8-flash-next`: the Nathanw fork, same as `nathanw-llamacpp.service`;
  - `qwen3.8-flash-next-upstream`: upstream build, for comparison; may not load.

The UI doesn't edit commands or flags; that's the config file. llama-swap
doesn't build llama.cpp either.

## Phase 1: install, idle (non-disruptive)

```bash
TASK_APPROVAL=llama-swap-install ./with-secrets-prod ansible-playbook \
  -i ansible/inventory/inventory.yml \
  ansible/00-initial-setup/framework-desktop-llama-swap.yml
```

This installs the binary (sha256-pinned), `llm-memgate`, the seed config, the
env file and the unit, then starts llama-swap with nothing loaded. It does
not touch the hand-run GLM on :8080, `nathanw-llamacpp.service`, the
embeddings service on :8085, or Docker.

**Don't press "load" in phase 1.** GLM is already on :8080 outside llama-swap.
The memory check would refuse the load anyway (about 16 GB free), but only
after a 2-minute wait.

Check: the UI opens at `https://llm-control.lab.gibbsgreatly.xyz/ui/` and lists the three models. Nothing is
loaded.

## Phase 2: hand GLM over (a few minutes with no model on :8080)

Pick a time when no CyberSecEval, eval-runner or deep-research job is running.

1. ```bash
   TASK_APPROVAL=llama-swap-cutover ./with-secrets-prod ansible-playbook \
     -i ansible/inventory/inventory.yml \
     ansible/00-initial-setup/framework-desktop-llama-swap.yml \
     -e framework_llama_swap_cutover=true
   ```
   This stops the hand-run GLM and stops and disables
   `nathanw-llamacpp.service`. The unit file is kept.
2. In the UI, load `glm-5.3-flash`. Its log should show the `llm-memgate ...
   starting` line, and :8080 `/health` should return ok.
3. Optional, once happy: uncomment the `hooks: on_startup: preload` block in
   the live config, so GLM (or whichever model you choose) starts after a
   reboot.

Before relying on it, check these:
- **Switching works:** load Qwen from the UI. GLM stops before Qwen's memory
  check passes, and `dmesg` shows no OOM.
- **Fixed-port backend is handled:** llama-swap health-checks the backend on
  :8080 and can stop it again.
- **The upstream Qwen entry loads.** If it doesn't, delete it from the config.
- **The UI playground answers** (it may get a 401 from the backend key; that
  doesn't matter for clients).

## Guard on the old playbook

`framework-desktop-llamacpp-native.yml` now has
`framework_llamacpp_chat_enabled: false`. Re-running it no longer starts
`nathanw-llamacpp.service` on :8080, and with `true` it refuses while
llama-swap is active. Embeddings are managed as before.

## Rollback

```bash
TASK_APPROVAL=llama-swap-rollback ./with-secrets-prod ansible-playbook \
  -i ansible/inventory/inventory.yml \
  ansible/00-initial-setup/framework-desktop-llama-swap.yml \
  -e framework_llama_swap_enabled=false
TASK_APPROVAL=llama-swap-rollback ./with-secrets-prod ansible-playbook \
  -i ansible/inventory/inventory.yml \
  ansible/00-initial-setup/framework-desktop-llamacpp-native.yml \
  -e framework_llamacpp_chat_enabled=true
```

The first run stops llama-swap and whatever model it started. The second
brings back `nathanw-llamacpp.service` (Qwen, fork) on :8080.

## Not in scope

- Ollama/Laguna, LM Studio, ComfyUI.
- Building or updating llama.cpp.
- Removing `nathanw-llamacpp.service` or the dead llama.cpp playbooks. That
  happens after the evaluation, if it's adopted.
