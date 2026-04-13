# Session Prompt — Plan Revision (Follow-up)

You are working in the proxmox-homelab repository at `/home/steve/git/proxmox-homelab`.

## Status of this work

The plan revision is **complete**. All nine changes were executed and merged to
`dev/pve-test` in commit `03f40d3` on 2026-04-13. See
`docs/design/PlanRevisionBrief.md` for the full record of what was done and the
decisions made.

## One remaining action

Close three GitHub issues. Read `docs/design/PlanRevisionBrief.md` (Outstanding action
section) for the exact commands, confirm them with the user, then run them.

```bash
gh issue close 89 --comment "Phase 02 services verified healthy. No further action required."
gh issue close 104 --comment "Headscale cancelled — no remote access requirement (lab is managed only from inside the home network). See task 04-core-services-02 archived in done/."
gh issue close 111 --comment "Chainloop cancelled — no Docker Compose self-hosting path exists. Helm/Kubernetes only. Deferred indefinitely. See task 05-supply-chain-04 archived in done/ for full analysis and viable alternatives."
```

Show the commands, ask before running.

## What changed in this revision (summary for context)

- **SDN zones** — `pve-test.yaml` now has `mgmt_seg` (10.57.1.0/24), `edge_seg`
  (10.57.2.0/24), `build_seg` (10.57.0.0/24). Portainer, Harbor, and apt-cacher remain
  on vmbr0 with documented rationale.
- **Phase 04 IPs** — all service IPs moved to SDN zone addresses: Authentik 10.57.1.10,
  step-ca 10.57.1.11, Traefik 10.57.2.10, Monitoring 10.57.1.12.
- **Task files** — 04-03, 04-04, 04-05 fully rewritten with SDN prereq, full bring-up
  sequences, and network placement sections. Phase 05 tasks (01-03) updated similarly.
- **Archived** — Authentik (DONE), Headscale (CANCELLED), Chainloop (CANCELLED) moved
  to `docs/plan/tasks/done/`.
- **Deleted** — stale old-numbered task files (04-03 step-ca, 04-04 Traefik).
- **README** — services table, Phase 06 note, and open issues updated.
