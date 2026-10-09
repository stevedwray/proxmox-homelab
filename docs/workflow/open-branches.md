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

## Follow-up (later on 2026-10-10)

- **Merged to stable:** #435 (`fix/ark-update-workaround`, merged
  directly), #444 (stale `dns-stack` GVM IP mapping) and #439 (catch-up
  plans + arr UI port lockdown).
- **Rescued:** `81f88809`, a teardown fix that existed only on the local,
  frozen `baseline/teardown-validated` ref, is now PR #467.
- **Pushed:** `feat/azerothcore-starter-weapon-skills` is now PR #466.
- **stable → main:** stable is about 340 commits ahead of main (last
  promotion #434, 2026-09-28). It waits on the pending ai-services-stack
  deploy (#464).

## Still open

| Branch | Where | Last commit | What | Next |
|---|---|---|---|---|
| `feat/azerothcore-starter-weapon-skills` | PR #466, 6 commits | 2026-09-29 | AzerothCore QoL: universal starter bags, Draenei heirloom vendor placement, starter weapon skills, each with docs. | Merges cleanly into stable; check it matches what runs. |
| `fix/teardown-skip-portainer-backup-when-stopped` | PR #467, 1 commit | 2026-10-10 | Skip the Portainer pre-destroy backup in `teardown-deploy-test.sh` when the LXC isn't running. | `bash -n`/shellcheck clean; not exercised live. |
| `fix/ark-update-workaround` | local + remote | 2026-09-27 | Merged (#435); branch not yet deleted. | Delete local and remote. |
| `prod/pve-infra` | local + remote | 2026-05-25 | "Promote validated pve infrastructure state" and planning docs for the baseline, credential and data refactors; far behind stable. | Kept (operator, 2026-10-10). |

The local `baseline/teardown-validated` ref still carries `81f88809`
(now on PR #467); reset it to `origin/baseline/teardown-validated` once
#467 merges.
