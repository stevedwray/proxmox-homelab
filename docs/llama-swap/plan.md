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

## Phase 3: managed llama.cpp builds (built 2026-10-09, branch `task/llama-builds`)

**Goal:** keep several llama.cpp backends, check them for updates, and
build, try, promote or roll back a new build without hand-editing paths
or systemd units.

**Layout:**
- **Sources:** one clone, `/storage/llama-builds/src`, with remotes `fork`
  (Nathanw1014/llama.cpp) and `upstream` (ggml-org/llama.cpp).
- **Backends:**
  - `fork` tracks `fork/strix-halo-vulkan`;
  - `upstream` tracks `upstream/master`.
- **Builds:** `/storage/llama-builds/<backend>/<date>-<sha>/` holds only
  `bin/` and the shared libs, about 81 MB each. They're built from a
  temporary worktree with the same CMake flags as today (Vulkan, Release,
  `GGML_NATIVE`). The last N builds per backend are kept.
- **Symlinks:** `/storage/llama-builds/<backend>/current` and
  `.../candidate`.
  - The llama-swap macros point at `.../<backend>/current/bin/llama-server`.
    Switching the link takes effect at the next model load (unload or
    load in llm-control), with no config save and no reload.
  - Extra llm-control entries run a model on `candidate` (e.g.
    "GLM-5.3-Flash · upstream candidate"). Benchmarks already record
    `build_info` from `/props`, so a candidate's runs are distinguishable
    from current's.

**The `llama-builds` tool on Framework:**

| Command | What it does |
|---|---|
| `llama-builds status` | per backend: current, candidate, the remote head, and how many commits behind |
| `llama-builds build <backend> [ref]` | fetch, build into a new dir, smoke-test (`--version`, load a tiny GGUF), set `candidate` |
| `llama-builds promote <backend>` | `current` := `candidate` (the old current stays for rollback) |
| `llama-builds rollback <backend>` | `current` := the previous build |
| `llama-builds prune <backend>` | keep the last N |

**Checking for updates:** a daily systemd timer
(`llama-builds-status.timer`) runs `llama-builds status --publish`. That
writes the status JSON to cse-panel's Redis (DB 1, key
`framework:llama-builds`, 3-day TTL); every build command publishes too.
panel-web's `/framework` returns it, and the Benchmark Control Panel's
Framework bar shows a second line, e.g. "llama.cpp builds: fork
20261009-b02cb35f2 (12 behind) · upstream … · checked …".
- The push goes framework (LAN) → cse-panel :6379 (mgmt_seg). The
  existing firewall policy already allows LAN to mgmt_seg; it was
  verified on 2026-10-09, when the first publish landed in Redis. A
  dedicated MikroTik rule was drafted, then dropped as redundant.
- The Redis password is in `/etc/llama-builds/redis-password`, readable
  only by steve, from OpenBao `services/cse-panel`. That's why
  `framework-desktop-llama-builds.yml` runs through `with-secrets-prod-tiny`.

**Retirement:**
- remove the `nathanw-llamacpp.service` unit (chat), which llama-swap
  replaced;
- point `nathanw-llamacpp-embed.service` at `fork/current`;
- delete the Docker-era playbooks that no longer describe anything that
  runs: `framework-desktop-llamacpp.yml` (HIP router container),
  `framework-desktop-llamacpp-nathanw.yml` ("NOT WIRED UP") and
  `framework-desktop-llamacpp-nathanw-vulkan.yml` (the old prebuilt
  container).

**Migration (no model downtime beyond one reload):**
1. Install the tool and the clone.
2. Import today's two builds as `fork/current` (b02cb35) and
   `upstream/current` (a4d880fd5) by copying their `bin/`.
3. Switch the llama-swap macros and the embed unit to the new paths
   (one reload).
4. Keep `~/llama.cpp*` until the new paths have run a while, then remove
   them.

**Decisions (operator, 2026-10-09):**
1. **Builds are started on request:** the operator asks, Claude runs
   `llama-builds` under the approval flow. There's no UI button or shell
   use.
2. **Update status appears in the benchmark panel header,** not Grafana.
3. **Backends:** the Nathanw fork (Vulkan), upstream (Vulkan) and upstream
   HIP/ROCm (gfx1151; the same flags as the old HIP container).
4. **The three Docker-era playbooks are deleted.**

**Build details:**
- Builds are self-contained: `CMAKE_BUILD_WITH_INSTALL_RPATH=ON` and
  `CMAKE_INSTALL_RPATH=$ORIGIN`. Today's hand builds have an absolute
  RUNPATH into `~/llama.cpp/build-vk/bin`, so they can't be copied; the
  migration rebuilds the same commits instead.
- Only the targets `llama-server` and `llama-bench` are built.
- Builds use Ninja, run at nice 10 with 24 jobs, and only one runs at a
  time (flock).
- A build only becomes `candidate`, or `current` if it's the backend's
  first build. llm-control has `*-candidate` and `*-hip` entries for GLM
  and Qwen.

## Rollback

- **A llama.cpp build:** `llama-builds rollback <backend>` points
  `current` back at the previous build. Reload the model in llm-control.
- **llama-swap itself:** run
  `framework-desktop-llama-swap.yml -e framework_llama_swap_enabled=false`.
  Since adoption (2026-10-09) the old `nathanw-llamacpp.service` chat unit
  is gone, so this leaves :8080 empty until a model is started by hand.
  The rollback to that unit, used during the evaluation, no longer
  exists.

## Not in scope

- Ollama/Laguna, LM Studio, ComfyUI.
- Building or updating llama.cpp.
- Removing `nathanw-llamacpp.service` and the dead llama.cpp playbooks
  was out of scope during the evaluation. It's done in phase 3 after
  adoption.
