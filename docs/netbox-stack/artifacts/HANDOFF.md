# NetBox Copilot Handoff

Use this file to prepare the next GitHub Copilot session for `netbox-stack`.
Assume the model is `GPT-5 mini` only.

Do not ask Copilot to reconstruct the whole NetBox strategy from scattered
history. The current resume context lives in:

- [docs/netbox-stack/current-state.md](/home/steve/git/proxmox-homelab/docs/netbox-stack/current-state.md:1)
- [docs/netbox-stack/README.md](/home/steve/git/proxmox-homelab/docs/netbox-stack/README.md:1)

The recent `docs/docker-refactor/` loop worked well. Reuse that same working
style here:

- one bounded session at a time
- one copy/paste prompt
- one required tracked handback
- review between sessions before continuing

## Current Recommended Next Session

- Current context: active development is on
  `task/netbox-infra-knowledge-progress`. NetBox is frozen at the Session 56
  state.

- Do not start another NetBox implementation session as the next step. The
  missing broad Docker application services are blocked upstream: most managed
  infrastructure Docker containers do not have a reachable
  `docker-socket-proxy` listener after normal deploy/rebuild.

- Resume in `docs/docker-refactor/` instead. That work must make
  socket-proxy deployment part of the normal managed infrastructure Docker
  container deploy path and prove it through a `pve` teardown/rebuild test for
  infrastructure containers only.

## Current Objective Boundary

NetBox is paused. Do not mutate NetBox, do not run populate apply, and do not
keep adding NetBox-side planning docs to compensate for missing Docker runtime
inspection.

Resume NetBox only after Docker refactor validation proves that rebuilt
managed infrastructure Docker containers on `pve` have reachable
`docker-socket-proxy` listeners and `populate.py --plan` can see the expected
runtime services.

## Handoff Rules

- choose exactly one bounded session
- give Copilot one primary objective only
- prefer a short file list
- do not combine design review, broad refactor, and live rollout in one session
- require a new handback file under `docs/netbox-stack/artifacts/`
- require the handback to follow
  [HANDBACK-TEMPLATE.md](/home/steve/git/proxmox-homelab/docs/netbox-stack/artifacts/HANDBACK-TEMPLATE.md:1)
- when handing the prompt to an operator, deliver the final prompt in chat as a
  single copy/pasteable fenced code block

## Copy/Paste Prompt Skeleton

```text
Work in /home/steve/git/proxmox-homelab.

You are GitHub Copilot using GPT-5 mini only.

Before editing, read in order:
1. /home/steve/git/proxmox-homelab/docs/netbox-stack/current-state.md
2. /home/steve/git/proxmox-homelab/docs/netbox-stack/README.md
3. /home/steve/git/proxmox-homelab/docs/netbox-stack/artifacts/HANDOFF.md
4. /home/steve/git/proxmox-homelab/docs/netbox-stack/artifacts/HANDBACK-TEMPLATE.md
5. /home/steve/git/proxmox-homelab/AGENTS.md
6. <primary file 1>
7. <primary file 2>
8. <primary file 3 if needed>

Session:
- <Session number and title>

Objective:
- <one concrete objective only>

In scope:
- <small bounded list>

Out of scope:
- no broad redesign beyond this session
- no silent expansion into later sessions
- no production mutation unless this session explicitly requires it

Required output:
- implement only the scoped change
- keep changes reviewable and local where possible
- run the small validation relevant to this session
- create a new handback file:
  /home/steve/git/proxmox-homelab/docs/netbox-stack/artifacts/SESSION-XX-<short-topic>-HANDBACK.md
- fill it using:
  /home/steve/git/proxmox-homelab/docs/netbox-stack/artifacts/HANDBACK-TEMPLATE.md

Handback minimum content:
- files reviewed
- files changed
- commands run
- validation completed
- validation not completed
- concrete outcomes
- blockers
- recommended next single session
```

## Before Sending A Session To Copilot

Check these manually:

- the objective is small enough for one pass
- the file list is short
- the completion criteria are concrete
- the next handback filename is chosen before the session starts
- the requested validation is proportionate to the change
- the exact prompt text is ready to paste into chat as one fenced code block
