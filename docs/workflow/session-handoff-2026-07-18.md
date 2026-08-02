# Session Handoff — 2026-07-18 — `pve-framework` reinstall through live AI stack

Status: **`llm-gpu-stack` and `comfyui-stack` are live and reachable through
the platform's normal HTTPS+auth pattern.** This was a single very long
session covering the actual reinstall of the Framework Desktop through a
fully working, Traefik/Authentik-fronted AI stack. This doc is the
continuity checkpoint — read this first, then
`docs/framework-integration/post-reinstall-plan.md` for the detailed
phase-by-phase trail (kept current throughout, not just at the end).

## What's live right now

| What | Where | Notes |
|---|---|---|
| `pve-framework` host | `192.168.1.8` / `pve-framework.gibbsgreatly.xyz` | Fresh Debian 13 + PVE 9.2.4, real hostname from install time |
| `llm-gpu-stack` (CT 50010) | `192.168.50.10:8080` (`ai_seg`) | `llama-router` (llama.cpp router mode), GPU passthrough confirmed working |
| `comfyui-stack` (CT 50011) | `192.168.50.11:8188` (`ai_seg`) | ComfyUI, GPU passthrough confirmed working |
| `llm.lab.gibbsgreatly.xyz` | via Traefik, `auth.mode: none` | Protected by its own `--api-key-file` instead (Decision 8) — key is real, in `secrets.common.enc.yaml` as `LLM_GPU_STACK_API_KEY`. Verified: unauth → 401 on `/v1/chat/completions`, `/v1/models` is deliberately public by llama.cpp's own design (not a bug) |
| `comfyui.lab.gibbsgreatly.xyz` | via Traefik, `auth.mode: forwardAuth` | Verified: unauth → 302 to Authentik login |
| `llm-gpu-stack-bg.lab.gibbsgreatly.xyz` / `comfyui-stack-bg.lab.gibbsgreatly.xyz` | direct A records → `192.168.50.10`/`.11` | Backend-direct names, matching the `-bg` convention used by every other service |

**Nothing has model weights staged yet.** Both services are up and correctly
secured but have nothing to actually generate with — `/storage/models/llm`
and `/storage/models/comfyui` on `pve-framework` are empty. This is the
next real step and needs your input (which models), not something to do
unilaterally.

## What changed, broadly (see git log on `work/framework-integration` for exact commits)

1. Reinstalled the box, hostname `pve-framework` from install time (was
   `fe-pve` during exploration — that name/IP `192.168.1.121` are gone).
2. Phase 0 (host bootstrap: repo fix, subscription-nag removal, Terraform
   token, GTT tuning, VLAN-aware bridge) and Phase 1 (network onboarding:
   `ai_seg` VLAN 50 SDN zone) — both done and live-verified against the
   real host, not just trusted from Ansible output.
3. **Storage restructured live** so growable data never shares space with
   Proxmox root — new `storage` LV (1TB, ISOs/templates/backups/models/
   artifacts) + resized `local-lvm` thin pool (700GB, container rootfs),
   `pve-root` untouched. Done while the thin pool was still at 0% usage —
   that window is now closed.
4. Both container templates staged (Ubuntu 26.04, custom Debian Docker
   template).
5. `llm-gpu-stack`/`comfyui-stack` deployed for real — first actual
   `terragrunt apply` against `pve-framework`, first real proof that
   `unprivileged: true` + GPU device passthrough works on this hardware.
6. Traefik routes + Authentik forward-auth (ComfyUI) / API-key auth
   (llama-server) wired up and verified end-to-end.

## Real bugs found and fixed along the way (all committed, all documented)

Roughly in the order hit — see [[reference_vzdump_unprivileged_permission]],
[[reference_ansible_extra_vars_global_scope]],
[[reference_proxmox_root_pam_only_fields]] for the standalone lessons:

1. **`build-debian-13-template.yml` hardcoded `mode: "0700"`** on the
   vzdump target directory — broke unprivileged-container template
   packaging (`lxc-usernsexec`-wrapped `tar` can't write into a 0700
   root-owned dir it doesn't own). Fixed to `0755`.
2. **Ansible `-e` extra-vars are global across every play in a file** —
   `-e ansible_user=root` and later `-e target_hosts=all` both leaked
   from an intentional first-play use into later plays that dynamically
   register a different host via `add_host`. Fixed by using `-u root`
   instead of `-e ansible_user=root`, and the literal host IP instead of
   `all` for `target_hosts`. Documented directly in the playbook header.
3. **Proxmox hardcodes `device_passthrough` and bind-type `mount_point`
   blocks to `root@pam`-only auth**, rejecting the Administrator-role API
   token with a 403 regardless of RBAC. Same restriction class this repo
   already had a precedent for (`keyctl`, `configure-keyctl.yml`).
   Removed both from the Terraform-managed resource; added
   `configure-device-passthrough.yml` to apply them out-of-band via
   direct root SSH `pct set`.
4. **`comfyui_stack`'s `git clone` failed** — bind-mounted `models`/
   `output` subdirectories had already created `/opt/ComfyUI` as
   non-empty before the role ran. Fixed via clone-to-scratch + `rsync`
   merge — which had its **own** bug: an unanchored `--exclude=models`
   also matched ComfyUI's internal `comfy/ldm/models/` package, breaking
   the service until anchored to `--exclude=/models`.
5. **Technitium's `zones/records/add` API** gives a misleading "No such
   zone was found: `<domain>`" error if you pass an explicit `zone=`
   param, even when it's correct — it wants zone auto-resolved from
   `domain` alone.
6. **`LAB_IP_AUTHENTIK` (`192.168.20.110`) is stale/wrong** — the real
   address Traefik/proxy-stack actually uses is `authentik-int.lab.gibbsgreatly.xyz`
   → `192.168.20.10`. Found because the first Authentik reconciliation
   attempt (below) silently succeeded against the *wrong*, apparently
   orphaned Authentik instance at `.110` (a separate live instance that
   responds plausibly to outpost auth checks but isn't the one anything
   real uses) before being redone against the correct `.10` address. **Not
   yet fixed at the source** — see Open Items below. Not caused by this
   session's work, just newly discovered by it.
7. **Authentik's `reconcile-authentik-edge.py` writes succeed but the
   embedded outpost doesn't serve the new config instantly** — expect a
   short propagation delay (a few minutes) before a newly-reconciled
   `forwardAuth` route actually redirects to login instead of 404ing.

## Open items / next steps

- **Model weights**: nothing staged. Needs your call on which models —
  see `docs/framework/model-quality-and-vuln-bench-2026-07-17.md` and
  `docs/framework/comfyui-image-video-gen-findings.md` for what was
  already evaluated in the bake-off (Qwen2.5-Coder-32B recommended for
  `llm-gpu-stack`; Z-Image Turbo + Wan 2.2 for `comfyui-stack`). Land
  them in `/storage/models/llm/` and `/storage/models/comfyui/` on
  `pve-framework`.
- **`LAB_IP_AUTHENTIK` env var is wrong** (`.110` instead of the real
  `.10`). Have not investigated how many other things might be silently
  relying on the wrong value, or why it diverged from the real
  `authentik-int` DNS record. Worth a dedicated look before trusting any
  other automation that reads this var.
- **NetBox registration** — explicitly deferred by the operator this
  session ("don't worry about netbox, we just want to do the functional
  stuff"). Still genuinely not done if it's wanted later.
- **`llm-gpu-stack`'s memory ceiling** (16GB) is still the original
  conservative placeholder from before any real model was loaded —
  revisit once a real target model is chosen, same empirical `anon`-usage
  discipline as `comfyui-stack`'s 40GB figure.
- **Dual-workload gateway** (`docs/framework/dual-workload-gateway-design.md`)
  — design only, not built. Its stated prerequisite (both stacks existing
  as real systemd services) is now true.
- No full teardown-cycle validation has been done for any of this
  session's work — per `docs/framework-integration/plan.md` Phase 4 /
  Decision 2, this reinstall+rebuild *is* that validation event for
  `pve-framework`'s own automation, but nothing has exercised a *second*
  full cycle yet.

## Where to look for more detail

- `docs/framework-integration/post-reinstall-plan.md` — the detailed,
  continuously-updated runbook this session followed; has the full
  phase-by-phase trail with exact commands and findings.
- `docs/framework-integration/decisions.md` — Decision 3's addendum has
  the full storage-restructure story; Decision 8 covers the Authentik/
  API-key auth-model reasoning per service.
- `docs/framework-integration/current-state.md` — as-found facts about
  the box as of this session.
- Memory (`/home/steve/.claude/projects/-home-steve-git-proxmox-homelab/memory/`):
  `project_framework_integration_status.md` is the pointer/index memory
  for this whole effort, kept current throughout.
