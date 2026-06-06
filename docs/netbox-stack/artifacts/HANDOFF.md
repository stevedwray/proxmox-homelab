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

- Current context: active development is on `task/netbox-infra-knowledge-progress`.
  The Portainer socket-proxy canary is accepted closed (2026-06-06). Do not
  target `dev/pve-test` or `baseline/teardown-validated` for future sessions
  in this workflow — they are archival/promotion branches only.

- Recommended next session (Light): `Session 51 - Lock Data Model and Ownership Boundary`.

  Objective:

  - Document the ownership marker and object-class ownership matrix so the
    reconciler has explicit create/patch/delete rules.
  - Produce a short, reviewable `ownership` doc under `docs/netbox-stack/`
    (or update `current-state.md`) describing the decisions and exit criteria.

  In scope:

  - Analysis and documentation edits only.
  - No remote actions, no NetBox mutations, no playbook applies.

  Out of scope:

  - Portainer canary or any host-contacting validation runs (these are closed).
  - Pushing commits or opening PRs as part of this session (commit locally only).

  Required handback file for that session (create during the session):

  - `docs/netbox-stack/artifacts/SESSION-51-OWNERSHIP-LOCK-HANDBACK.md`

  Why this is next:

  - It removes ambiguity in object ownership and prevents repeated canary loops.
  - It is a small, document-driven Light session that reduces risk for later
    scoped apply work.

## Current Objective Boundary

Treat the next session (Session 51 - Lock Data Model and Ownership Boundary)
as a documentation and design-only session. The objective is to author and
review ownership decisions and the object-class ownership matrix; there must
be no live validation, deployment, or mutation activity as part of this
boundary.

In-scope (strict):

- Documentation and design work only (analysis, writing, and internal review)
  in `docs/netbox-stack/` such as creating an `ownership` doc or updating
  `current-state.md` with a clear ownership matrix and exit criteria.
- Producing an explicit ownership marker and object-class ownership matrix for
  the reconciler's create/patch/delete rules.

Out-of-scope (explicitly prohibited):

- No host-contacting validation or any check-mode runs that contact hosts.
- No Portainer canary or check-mode work.
- No NetBox mutations (no create/patch/delete operations against NetBox).
- No deploys, no PRs, and no pushes — changes should remain local and
  reviewable until the ownership session completes.

Acceptance criteria:

- A short, reviewable `ownership` document is produced under
  `docs/netbox-stack/` or `current-state.md` is updated to capture the
  ownership decisions and exit criteria.
- A handback file is created at
  `docs/netbox-stack/artifacts/SESSION-51-OWNERSHIP-LOCK-HANDBACK.md` that
  documents files reviewed, decisions made, validation performed (design-only),
  blockers, and the recommended next single session.

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
