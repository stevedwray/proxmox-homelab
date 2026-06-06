# NetBox Stack Current State

## Purpose

This note is the short resume point for the `netbox-stack` workstream.

Use it together with:

- `docs/netbox-stack/README.md`
- `docs/netbox-stack/artifacts/HANDOFF.md`

The goal is to let a fresh Copilot session resume cleanly without re-reading
the full artifacts history first.

## Current Position

The NetBox stack itself is in workable shape.

### Portainer Canary Closure (2026-06-06)

- Status: Portainer socket-proxy canary accepted closed.
- Summary: Portainer socket-proxy listener is live on the declared Portainer target. NetBox service ownership cleanup for Portainer-related services has been verified; `populate.py --plan` reports only non-destructive description/tag/format updates for the affected services. See `docs/netbox-stack/artifacts/SESSION-46-PORTAINER-FINAL-VERIFY-HANDBACK.md` and `docs/netbox-stack/artifacts/SESSION-47-PORTAINER-CANARY-CLOSURE-HANDBACK.md` for details.


What is already true:

- NetBox deployment is real and running.
- The external populate workflow exists and is usable.
- Proxmox and MikroTik discovery are established parts of the runtime model.
- Docker runtime scraping through `docker-socket-proxy` is now functionally
  proven.
- A disposable socket-proxy proof path exists.
- A real-stack canary was completed on `monitoring-stack`.
- NetBox successfully ingested socket-proxy-derived runtime services tagged
  with `runtime-source-socket-proxy`.

Important deployment boundary:

- The repo has a managed `docker_socket_proxy` Ansible role and Docker stack
  playbooks can opt into it.
- Normal platform stack metadata currently keeps that opt-in disabled
  (`enable_docker_socket_proxy: false`).
- The disposable `docker-socket-proxy-test` playbook is the only repo-declared
  deployment path that enables the proxy by default.
- `pve-test` verification has proven the disposable listener and NetBox
  declared-target mapping path.
- Treat production rollout state as unknown until it is verified live. The
  monitoring canary proves the method, not broad production deployment.

## The Main Open Question

The main remaining NetBox design question is not whether socket-proxy works.
It does.

The open question is how the NetBox populate process should decide which Docker
hosts to probe.

Right now:

- most Docker runtime targets are expected to come from Proxmox discovery
- but not every future Docker host will necessarily come from Proxmox
- the current code contains a narrow `populate.py` augmentation to bridge one
  discovery gap for the `monitoring-stack` canary

That augmentation works, but it should not be accepted blindly without a design
decision.

## Recommended Next Work

- Portainer socket-proxy canary: accepted closed (2026-06-06). No further
  Portainer canary/check-mode sessions are recommended; the closure is
  recorded in [docs/netbox-stack/artifacts/SESSION-46-PORTAINER-FINAL-VERIFY-HANDBACK.md](docs/netbox-stack/artifacts/SESSION-46-PORTAINER-FINAL-VERIFY-HANDBACK.md).

- Active branch: `task/netbox-infra-knowledge-progress`.

- Next practical task (Light): Lock the Data Model and Ownership Boundary.

  What to do in this Light session:

  1. Decide and document the ownership marker (NetBox tag) and the exact
    set of NetBox object classes the reconciler will manage (DCIM,
    virtualization, IPAM, services, tags).
  2. Create a short ownership matrix in `docs/netbox-stack/` that maps object
    classes to owning source(s) and explicit deletion rules.
  3. Add concise guidance for `docker_socket_proxy_targets` semantics:
    declared targets must map to existing NetBox VM/interface records;
    the reconciler must not create VM objects implicitly.
  4. Define exit criteria: ownership matrix documented, create/patch/delete
    rules explicit, and reviewers agree on boundaries. No live NetBox
    mutations during this session.

## What Not To Reopen First

Do not start by reopening:

- Portainer migration/export-import work
- broad NetBox auth/token redesign
- Docker socket-proxy transport proof
- disposable test-path setup

Those areas are either already proven or belong to separate workstreams.

## Copilot Session Style

The recent Docker refactor loop worked well:

- one bounded session at a time
- clear copy/paste prompt
- required tracked handback
- manager review between sessions

Use the same pattern here for NetBox resume work.

## Commit Message Notes

When this work is eventually committed, useful message material:

- clarify NetBox docker-socket-proxy state: transport proven, broad production
  rollout not assumed
- document that normal platform stacks still keep socket-proxy opt-in disabled
  unless explicitly enabled
- add `docker_socket_proxy_targets` as an explicit stack metadata hook for
  declared Docker host probe candidates
- keep target augmentation safe: map declared addresses only to existing
  NetBox VM/interface records; do not create VM objects implicitly
- add focused coverage for multiple declared socket-proxy candidates and
  stack-name skip behavior
- record Portainer canary prep: declared target, runbook, pve-test
  `populate.py --plan`, and enabled check-mode result
  `ok=29 changed=3 unreachable=0 failed=0 skipped=49 rescued=0 ignored=0`
