# llama-swap (workspace)

A web control page for choosing which model and llama.cpp build Framework
serves on :8080. See [plan.md](plan.md).

Status: **live, 2026-10-07.** llama-swap manages :8080 (GLM loaded, boot
default GLM). The old hand-run GLM is gone, and `nathanw-llamacpp.service`
is disabled (unit kept).

## Log

- 2026-10-07: design changed to "control page only". Clients keep using
  `llama-server` on :8080 directly; llama-swap listens on :8099. Files:
  - `ansible/00-initial-setup/framework-desktop-llama-swap.yml`
  - `ansible/00-initial-setup/files/llama-swap/{config.yaml,llm-memgate}`
  - the chat guard in `framework-desktop-llamacpp-native.yml`
- 2026-10-07: phase 1 run (`TASK_APPROVAL=llama-swap-install`): ok=19
  changed=12 failed=0, cutover tasks skipped. Verified afterwards:
  - `llama-swap` is active on :8099 and returns 401 without the key; it
    lists the three models, none loaded.
  - GLM (pid 1621293) still serves :8080, `/health` ok.
  - Embeddings on :8085 are unchanged.
  - `nathanw-llamacpp` is still inactive but enabled (disabled at cutover).
- 2026-10-07: replaced llama-swap's API key (a browser basic-auth popup,
  which Bitwarden can't fill) with an Authentik login, in this order:
  1. Framework playbook (`TASK_APPROVAL=llm-control-login`, ok=21
     changed=7): loaded `llama-swap.nft` first, then removed `apiKeys` from
     the live config and the env file. Verified: :8099 times out from the
     LAN and answers locally.
  2. `reconcile-edge.py --apply` (full stacks dir, `llm-control-edge`):
     write_count 3, i.e. the `llm-control` app and provider created and
     linked to the embedded outpost. The only issue was the known
     Nextcloud EGR211 drift; its delete-report entries are never applied.
  3. `provision.sh --stack proxy-stack`: ok=107 failed=0.
  4. `configure-llm-control-dns-records.yml`: A record
     llm-control → 192.168.30.10, replicated to both Technitium nodes.

  Verified: `https://llm-control.lab.gibbsgreatly.xyz/ui/` returns 302 to
  Authentik, and Traefik's host reaches framework:8099 (200).
- 2026-10-07: phase 2 at the operator's request (a quiet time; GLM had 0/4
  slots busy and no connections).
  - Cutover (`TASK_APPROVAL=llama-swap-cutover`): `nathanw-llamacpp`
    stopped+disabled, the hand-run GLM stopped, :8080 freed.
  - Each model was loaded through llama-swap and tested with 17*23 → 391.
    In every switch the previous model was fully stopped first: the
    memgate saw about 122.7 GB free each time, and `dmesg` showed no OOM.

    | Model | Build | Load time |
    |---|---|---|
    | glm-5.3-flash | upstream | 48 s |
    | qwen3.8-flash-next | fork | 79 s |
    | qwen3.8-flash-next-upstream | upstream | 78 s |
  - GLM's `--chat-template-kwargs {"reasoning_effort":"high"}` argv is
    identical to the hand-run process. `/props`: alias glm-5.3-flash,
    n_ctx 131072, 4 slots.
  - Boot default: `hooks.on_startup.preload: [glm-5.3-flash]`. Finding:
    saving the config reloads llama-swap, and the preload then loads GLM,
    replacing whatever was loaded.
  - End state: GLM loaded via llama-swap. :8080/health is 200 from the
    LAN and through Traefik `llm.lab`.
