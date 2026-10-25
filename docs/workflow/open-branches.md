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

## Sweep (2026-10-24)

- **Merged to stable:** #511, the alerting work (`work/graylog-sender-ip-pentest-stream`), with a **merge
  commit**, not a squash, so the commit IDs survive. It carried the operator's `2fd7175d` (mcp-utility-stack back
  to pve), which `work/pve-tiny-evacuation` already holds. Simulated merges of the evacuation branch and of
  `work/mcp-utility-back-to-pve` into the new stable are **clean**.
- **Deleted (all fully merged into stable, none held by a worktree):** local
  `work/graylog-sender-ip-pentest-stream`, `work/gvm-dashboard-oom-range`, `work/mcp-utility-back-to-pve`,
  `work/omada-pr`, `work/portainer-2-39-8`, `work/pve-test-netbox`; remote
  `work/graylog-sender-ip-pentest-stream`, `work/gvm-dashboard-oom-range`, `work/portainer-2-39-8`,
  `work/pve-test-netbox`.
- **Left alone:** every branch held by a worktree (`task/autonomous-pentest-design`, `task/ctx-bug-test`,
  `work/gvm-nightly-credentialed`, `work/gvm-run-all-once`, `work/oci-pangolin-overrides`,
  `work/pve-tiny-evacuation`), and `origin/claude/qwen-laguna-model-testing-v42x6x` (merged, not created in this sweep).
- **Local only, not on GitHub:** `work/pve-tiny-evacuation` (14 commits ahead of stable, active, holds the
  evacuation plan and evidence) and `task/oci-security-prs-integration` (97 commits ahead). Push them when the
  owner is ready; until then a lost disk loses them.
- **Known conflict, not caused by the alerting merge:** `task/oci-security-prs-integration` conflicts with stable on
  `secrets/manifest.json` (it conflicted with the previous stable too). Resolve when that branch is next rebased or merged.
- **stable to main:** stable is 383 commits ahead of main. Not promoted; it needs an incremental pve deploy and smoke test first.

## Still open

| Branch | Where | Last commit | What | Next |
|---|---|---|---|---|
| `feat/azerothcore-starter-weapon-skills` | PR #466, 6 commits | 2026-09-29 | AzerothCore QoL: universal starter bags, Draenei heirloom vendor placement, starter weapon skills, each with docs. | Merges cleanly into stable; check it matches what runs. |
| `fix/teardown-skip-portainer-backup-when-stopped` | PR #467, 1 commit | 2026-10-10 | Skip the Portainer pre-destroy backup in `teardown-deploy-test.sh` when the LXC isn't running. | `bash -n`/shellcheck clean; not exercised live. |
| `feat/argon-icinga-observability` | local, unpushed | 2026-10-26 | Native Icinga HA pair, all six Stage 2 core-check groups, SmokePing probes and repaired web backend, DNS and direct Icinga Web are **deployed live from this unmerged branch**. The 2026-10-26 audit found 14/14 hosts and 31/31 services OK in current Redis state; the expanded SmokePing and Icinga Web smoke checks pass. | Operator to retry the SmokePing Authentik browser login. Stage 3 notifications await dedicated OpenBao values; OCI SSH awaits its separate key and pinned host key. Finish remaining gates, then validate and merge to stable. |
| `fix/ark-update-workaround` | local + remote | 2026-09-27 | Merged (#435); branch not yet deleted. | Delete local and remote. |
| `prod/pve-infra` | local + remote | 2026-05-25 | "Promote validated pve infrastructure state" and planning docs for the baseline, credential and data refactors; far behind stable. | Kept (operator, 2026-10-10). |

The local `baseline/teardown-validated` ref still carries `81f88809`
(now on PR #467); reset it to `origin/baseline/teardown-validated` once
#467 merges.
