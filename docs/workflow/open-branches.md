# Open branches

What is still unmerged after the branch sweep on 2026-10-10. Each item is
merged or dropped from its own work session; update this list when one is.

## The sweep (2026-10-10)

- **Merged to stable first:**
  - #461: benchmark panel results, delete, local time, saved settings.
  - #462: llama-swap catalogue and model-params phase A.
  - #463: the GLM-5.3-Flash evaluation doc.
  - #464: deep-research Nextcloud push logging, rescued from
    `task/llama-swap-plan`. Not deployed yet; it goes out with the next
    ai-services-stack deploy.
- **Deleted:**
  - 29 local and 20 remote branches already merged into stable;
  - 6 local snapshots wholly contained in other branches;
  - `task/glm-5.3-flash-eval`, `fix/deep-research-push-logging` and
    `task/llama-swap-plan` after #463/#464. The last one's only other
    commit was the superseded 2026-10-01 llama-swap front-proxy plan.
- **Worktrees:** `proxmox-homelab-eval-runner` (clean, its branch merged as
  #455) was removed, and the stale `/tmp` one was pruned.
- **Kept on purpose:** `stable`, `main`, `baseline/teardown-validated`,
  `dev/pve-test` and `archive/*`.

## Still open

| Branch | Where | Last commit | What | Next |
|---|---|---|---|---|
| `fix/uvm-stale-dns-stack-ip-mapping` | PR #444 | 2026-09-29 | Removes `192.168.20.13 → dns-stack` from GVM's `ip_to_stack.json`. Still needed: stable still has the mapping, so findings are attributed to a destroyed CT. | Merges cleanly into stable. |
| `task/catch-up-01-arr-lockdown` | PR #439 | 2026-09-28 | The catch-up plans (docs/catch-up), the status refresh, and the arr UI port lockdown (01). Contains the deleted `task/catch-up-plans` and `task/status-refresh-2026-09-28`. | Merges cleanly into stable. |
| `fix/ark-update-workaround` | PR #435 | 2026-09-27 | ARK update-check playbook (`update-ark-survival-ascended.yml`) and appmanifest cleanup on server stop. | Merges cleanly into stable; check it matches what runs. |
| `feat/azerothcore-starter-weapon-skills` | local only, 6 commits | 2026-09-29 | AzerothCore QoL: universal starter bags (`003-fix-starter-bag.sql`), Draenei heirloom vendor placement, starter weapon skills, each with docs. Contains the deleted `fix/azerothcore-starter-bags`, `fix/draenei-heirloom-vendor` and `preserve/gaming-stack-lab-starter-bags-orphan`. | Push, PR. Merges cleanly into stable. |
| `prod/pve-infra` | local + remote | 2026-05-25 | "Promote validated pve infrastructure state" and planning docs for the baseline, credential and data refactors; 1,867 commits behind stable. | Kept (operator, 2026-10-10). |
