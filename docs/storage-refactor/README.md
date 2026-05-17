# Storage Refactor

## Purpose

Define and execute a proper refactor so that LXC storage selection is a pure
configuration concern rather than a code concern.

The end state is:

- stacks declare storage intent, not physical Proxmox pool names
- one environment-specific storage configuration maps that intent to real
  Proxmox storage backends
- Terraform consumes resolved storage values
- validation proves the configured backends exist and support the requested
  content types

This documentation is intended to live on `baseline/teardown-validated`, but it
should be authored on a short-lived branch and merged there through the normal
promotion workflow rather than edited directly on the baseline branch.

## Current State

`pve-test` currently has a deployed set of containers on the active storage
configuration. This is not a greenfield host.

At the time this plan was written:

- the internal SSD (`sda`) provides `local` and `local-lvm`
- the live `pve-test` deployment currently uses `infrastructure-containers`
- the repo still contains stack references to both `infrastructure-containers`
  and `storage-containers`, so the migration surface is broader than a single
  pool name
- the current `storage-template` directory pool is mounted at
  `/storage/template`
- the active `infrastructure-containers` and `storage-template` pools are backed
  by the external Samsung T7 USB drive (`sdb`)

This matters because the refactor must not pretend that storage can be changed
only in code while ignoring the currently deployed containers and host storage
layout.

## Why This Refactor Exists

Today, storage decisions leak through multiple layers:

- stack `stack.yaml` files hardcode pool names such as
  `infrastructure-containers`
- Terraform root defaults also carry environment policy
- the LXC module assumes a fixed storage layout for rootfs, Docker, and extra
  mounts
- template references encode both the template identity and the template
  storage backend in a single string

As a result, changing from one physical backend to another is a repo-wide
editing exercise instead of a controlled configuration change.

## Required Branching Model

This is infrastructure work. The implementation branch must follow the repo
branch model:

1. Author and review this documentation on a short-lived branch cut from the
   current baseline head.
2. Merge the approved planning docs to `baseline/teardown-validated`.
3. Start implementation from the refreshed `baseline/teardown-validated` on a
   short-lived `work/*` branch.
4. Validate the storage refactor through a full teardown + redeploy cycle on
   that `work/*` branch.
5. Merge back to `baseline/teardown-validated` only after the gate passes.

Recommended implementation branch name:

```bash
git checkout baseline/teardown-validated
git pull --ff-only origin baseline/teardown-validated
git checkout -b work/storage-refactor-01
```

## Scope

This refactor covers:

- LXC rootfs storage selection
- Docker data mount storage selection
- optional extra persistent mount storage selection
- template storage selection and template identity separation
- environment-level validation of required Proxmox storage backends

This refactor does not, by itself, require immediate migration of production or
test data between pools. It does require a cutover plan for `pve-test` because
the host currently has deployed LXCs on the existing storage model.

## Plan Documents

- [Execution Plan](plan.md)
