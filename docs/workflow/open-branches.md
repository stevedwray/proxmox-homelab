# Open branches

Unmerged work and what each branch still needs. Update this list whenever a
branch is merged or dropped. Long-lived branches that are kept on purpose are
listed in [branch-model.md](branch-model.md#long-lived-branches-kept-on-purpose).

## Current state (2026-10-10)

- `main` and `stable` hold the same tree: stable was promoted in #469
  (`8052c476`), so `main` is ahead only by that merge commit.
- No open PRs and no unmerged short-lived branches.
- No extra worktrees or stashes in the main checkout. The two bake-off clones
  (`../proxmox-homelab-agent-test`, `../proxmox-homelab-opencode`) were
  removed.

| Branch | Where | Last commit | What | Next |
|---|---|---|---|---|
| `prod/pve-infra` | local + remote, 2 commits not on stable | 2026-05-25 | "Promote validated pve infrastructure state" and planning docs for the baseline, credential and data refactors. | Kept (operator, 2026-10-10). |

## Loose ends

- **CT 170 on pve-test-vm.** The Stage 10 minecraft-stack exemplar run
  (`docs/stack-lifecycle-refactor/stage-10-minecraft-exemplar.md`) created it
  at 192.168.1.60. pve-test-vm is stopped, so the CT is probably still on its
  disk. If that VM is ever started, check `pct list` and destroy 170.
- **Issue #470.** Trivy found problems in the eval-runner Dockerfiles when
  #469 was promoted. This isn't a branch, but the promotion merged with these
  findings knowingly accepted.

## History

### Sweep (2026-10-10, morning)

- Merged to stable: #461–#465 (benchmark panel results, llama-swap catalogue,
  GLM-5.3-Flash eval doc, deep-research push logging, sweep record).
- Deleted 29 local and 20 remote branches already merged into stable, six
  local snapshots contained in other branches, and the
  `proxmox-homelab-eval-runner` worktree.

### Follow-up (2026-10-10, afternoon)

- Merged to stable: #435 (ARK update workaround, merged directly), #444 (stale
  `dns-stack` GVM IP mapping), #439 (catch-up plans and arr UI port lockdown),
  #466 (AzerothCore starter bags, Draenei vendor and weapon skills, previously
  local only), #467 (teardown fix `81f88809`, rescued from the local
  `baseline/teardown-validated` ref).
- Deployed #464 to ai-services-stack on pve-tiny, then promoted stable to
  `main` in #469.
- Deleted every merged branch, reset the local `baseline/teardown-validated`
  to origin, and unset the misleading upstreams on `archive/teardown-validated`
  and `archive/dev-pve-test`.
