# llama-swap (workspace)

A web control page for choosing which model and llama.cpp build Framework
serves on :8080. See [plan.md](plan.md).

Status: **adopted, 2026-10-09** (live since 2026-10-07). llama-swap
manages :8080: GLM is loaded and is the boot default. The old hand-run GLM
is gone, and `nathanw-llamacpp.service` is disabled; its removal is part of
phase 3.

**Phase 3, managed llama.cpp builds: live 2026-10-09** (see
[plan.md](plan.md)). llama-swap and the embeddings server run builds from
`/storage/llama-builds/<backend>/current`. To update, ask: "check for
updates", "build the newest fork as a candidate", "promote it", "roll it
back". The benchmark panel's Framework bar shows each backend's build and
how far behind it is.

**Done in the close-out (2026-10-09):**
- Reboot test: llama-swap, its nft table, the GLM preload and :8080 all
  came back by themselves. This happened after the GTT ceiling fix, #459.
- The live config's stale comments were refreshed. The only difference
  from the seed was comments; it was validated first, and the reload
  brought GLM back in about a minute. The backup is
  `config.yaml.bak-2026-10-09`.

## Log

- 2026-10-09, first update cycle (approvals `llama-builds-candidates`,
  `llama-builds-smoke`):
  - **Check:** the fork is 104 commits behind (`9e21f2e53`, mostly Vulkan
    FA NaN fixes and `qwen4exp` tuning); upstream is 205 behind
    (`de7fa0a3c`).
  - **Built:**
    - fork candidate 20261008-9e21f2e53 (5 min);
    - upstream candidate 20261008-de7fa0a3c (1 min);
    - the first upstream-hip build, 20261008-de7fa0a3c (about 1 min on
      32 cores: Clang 21 HIP for gfx1151, libggml-hip, rocblas/hipblas;
      105 MB).
  - **Smoke test:** the same request at temperature 0, low effort, 300
    max tokens, loaded through llama-swap:

    | Build | Gen tok/s | Notes |
    |---|---|---|
    | GLM, current upstream a4d880fd5 | 18.9 | |
    | GLM, upstream candidate de7fa0a3c | 18.6 | identical text |
    | GLM, upstream HIP de7fa0a3c | 16.1 | about 15% slower |
    | Qwen, fork candidate 9e21f2e53 | 25.8 | |

    There were no amdgpu errors, and it ended back on GLM current. Qwen
    on the current fork wasn't measured in the same run.
  - **Promoted upstream** (operator: yes): current is now 20261008-de7fa0a3c,
    with the old a4d880fd5 build kept as `previous`. GLM reloaded as
    b11514-de7fa0a3c: 18.5 tok/s, same answer, no amdgpu errors.
  - **Fork comparison** (operator asked for it): same request, builds
    alternated twice.
    - current b02cb35f2: 25.6 and 25.5 tok/s, 280 tokens;
    - candidate 9e21f2e53: 26.0 and 25.8 tok/s, 265 tokens.
    - Each build is deterministic. The two builds differ slightly in
      wording (the FA fixes), and both answers are coherent.
    - Recommended: promote. The operator agreed.
  - **Promoted the fork:** current is now 20261008-9e21f2e53, with
    b02cb35f2 kept as `previous`. The embeddings server restarted on it
    (b10814-9e21f2e53, 768-dim).
  - **All three backends are up to date** as of 2026-10-08 20:39 UTC.

- 2026-10-09, phase 3 rollout (approval `llama-builds-rollout`):
  - **Installed:** `framework-desktop-llama-builds.yml` (with-secrets-prod-tiny)
    installed the tool, config, clone and daily timer; the first status
    check published to cse-panel Redis.
    - **No MikroTik rule needed:** LAN → mgmt_seg :6379 is already
      allowed. The drafted rule play was dropped.
  - **Builds at today's exact commits:**
    - fork 20261008-b02cb35f2 (build 10710; 3 min, 79 MB);
    - upstream 20261008-a4d880fd5 (build 11309; about 3 min, 66 MB).
    - Both have RUNPATH `$ORIGIN`, with every lib resolved inside the
      build dir.
  - **llama-swap config** switched to the managed builds and validated
    (7 models). GLM restarted from `upstream/current` with the same
    `build_info` b11309-a4d880fd5.
  - **`framework-desktop-llamacpp-native.yml`:** embeddings now run from
    fork/current (b10710-b02cb35f2; the 768-dim probe passed), and
    `nathanw-llamacpp.service` was deleted.
  - **cse-panel-stack deployed.** The header shows "llama.cpp builds: fork
    20261008-b02cb35f2 (104 behind) · upstream 20261008-a4d880fd5 (205
    behind) · upstream-hip not built".
  - **Not yet done:**
    - the first HIP build;
    - updating fork or upstream to their newest commits (candidates
      first);
    - deleting `~/llama.cpp` and `~/llama.cpp-upstream` after a while.

- 2026-10-09: the operator adopted llama-swap. They want several llama.cpp
  backends kept side by side ("under heavy development; nathanw is good on
  this hardware") and a way to check for updates and update them, which
  is phase 3. Live config comments refreshed (approval
  `llama-swap-config-comments`). Framework's builds today, read-only:
  - `~/llama.cpp`: the Nathanw fork, branch `strix-halo-vulkan` @
    b02cb35 (2026-09-16);
  - `~/llama.cpp-upstream`: a worktree of the same clone, detached at
    upstream a4d880fd5. Its only remote is the fork; there's no
    ggml-org remote.
  - Both are Vulkan Release builds with `GGML_NATIVE`, built by hand on
    2026-09-30. Each build dir is about 0.5 GB; `bin/` is 81 MB.
  - `nathanw-llamacpp-embed.service` (nomic-embed, :8085) runs straight
    from `~/llama.cpp/build-vk/bin`.
  - Disk: `/` 22 GB free; `/storage` 1 TB free.

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
