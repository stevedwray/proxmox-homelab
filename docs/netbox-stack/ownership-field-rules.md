# NetBox Ownership: Field-level Rules

Purpose
-------

This document lists per-object-class field rules used by the `netbox-stack`
reconciler: which fields may be created, which fields may be patched/updated,
which fields must never be changed automatically (never-change), delete/
removal policy, and the authoritative source of truth for each managed class.

General rules
-------------

- Ownership marker: every reconciler-created object MUST carry the tag
  `managed-by-proxmox-homelab` (see `MANAGED_TAG_NAME` in code).
- All created objects must include the environment tag `netbox-env-<env>` when
  population is environment-scoped.
- The reconciler MUST verify the ownership tag before any patch/update/delete
  action.
- All entries below explicitly show: create, patch/update, never-change,
  delete/removal, and source of truth.

Tags
----

- Allowed create fields:
  - `name`, `slug`, (optional) `description`
  - `tags` list may include ownership tag and runtime markers
- Allowed patch/update fields:
  - `description`, `tags` (append/remove ownership or runtime tags)
  - small metadata corrections for tag spelling/slug normalization
- Fields that must never be changed automatically (never-change):
  - tag `slug` values that are operator-owned (unless the tag was created by
    the reconciler itself)
- Delete/removal policy:
  - Reconciler may delete tags it created when the owning source signals
    removal; do not delete operator-managed tags.
- Source of truth: repo-seeded lists and runtime discovery depending on tag
  origin (explicitly recorded with `source` metadata when possible).

Sites / Locations / Tenants
---------------------------

- Allowed create fields:
  - `name`, `slug`, `status`, `description`, parent site/location refs
- Allowed patch/update fields:
  - `description`, `status`, small parent/location reparenting when owned
- never-change:
  - canonical `slug` and operator-managed address fields
- delete/removal policy:
  - delete only when owning source (repo-seed or explicit environment intent)
    indicates the site/location has been removed
- Source of truth:
  - sites/locations from repo-seeded network intent or explicit environment
    mapping files (see `NETWORK_INTENT_FILES` in `populate.py`). Tenants are
    operator-controlled and are out-of-scope unless explicitly repo-seeded.

Devices (Physical) and Virtual Machines (VMs)
-------------------------------------------

- Allowed create fields:
  - `name`, `device_role`/`role`, `device_type`/`platform`, `status`,
    `site`, initial `interfaces` minimal list (name/type)
  - For VMs: `name` (shared-inventory form `name@node`), `cluster` if
    discovered, `status`
- Allowed patch/update fields:
  - `description`, `status`, `tags`, `platform`/`device_type` corrections,
    `primary_ip` assignment (only if ownership tag present)
  - `interfaces` list may be extended with discovered interfaces, but
    interface creation follows the Interfaces rules below
  - small name migrations only when `legacy_name_migration_enabled` context
    is set in population intent
- never-change:
  - `name` (except for explicit legacy-migration rules), `serial`,
    `asset_tag` and operator-owned custom fields
- delete/removal policy:
  - Delete only when ownership tag is present and owning discovery source
    explicitly reports removal (targeted delete). Never class-wide wipes.
- Source of truth:
  - Proxmox discovery for VMs and hypervisor-attached devices; repo-seeded
    definitions for explicit physical device modeling.

Interfaces (Device / VM interfaces)
----------------------------------

- Allowed create fields:
  - `device`/`virtual_machine` reference, `name`, `type`, `enabled` flag
  - minimal description and MAC when available from source discovery
- Allowed patch/update fields:
  - `description`, `enabled`, `mac_address` (only to correct missing/empty
    values if authoritative from source), `tags`
- never-change:
  - `device`/`virtual_machine` pointer reparenting unless explicitly allowed
    by owning-source reconciliation (do not reparent silently)
- delete/removal policy:
  - Remove interface only when owning source has removed it or the parent
    device was deleted by ownership policy
- Source of truth:
  - Proxmox discovery and runtime introspection where applicable.

IP Addresses
------------

- Allowed create fields:
  - `address`, `status`, `description`, `assigned_object` reference (when
    known), `tags`
- Allowed patch/update fields:
  - `description`, `status`, `tags`, `dns_name` and `assigned_object` when
    the owning source provides a stable mapping (e.g., Proxmox reports a
    VM's IP)
- never-change:
  - `address` value itself must never be modified by the reconciler; a
    new IP object must be created if the owning source indicates a different
    address mapping
- delete/removal policy:
  - Delete only when the owning source signals removal or when an IP is
    clearly ephemeral and was created by a runtime flow the reconciler owns
- Source of truth:
  - Network intent files for prefixes; Proxmox discovery for VM-assigned
    addresses; runtime discovery for ephemeral addresses.

Services (ipam/services)
------------------------

- Allowed create fields:
  - `name`, `port`, `protocol`, `parent` (IP address), `description`, `tags`
  - For runtime-derived services: include `source` metadata and `runtime` tag
- Allowed patch/update fields:
  - `description`, `tags`, `port` when service probe semantics indicate
    a stable correction (append-only where possible)
- never-change:
  - `parent` pointer (IP address) should not be reparented automatically
    except when the owning source provides a clear authoritative mapping
- delete/removal policy:
  - Runtime services created from probes may be removed when the probe no
    longer sees the service; reconciler must follow a conservative decay or
    operator verification step before hard deletion
- Source of truth:
  - Runtime discovery (docker-socket-proxy and other probe tooling) for
    observed services; repo-seeded service intent only when present.

docker_socket_proxy_targets-derived runtime services
----------------------------------------------------

- Context: `docker_socket_proxy_targets` entries augment population by
  declaring candidate Docker hosts to probe. See `populate.py` augmentation
  and `docker_socket_proxy_targets` semantics in `docs/netbox-stack/current-state.md`.
- Allowed create fields:
  - `name`, `port`, `protocol`, `parent` (IP address), `description`,
    `tags` including `runtime-source-socket-proxy`
  - When creating a service from socket-proxy discovery, include a `source`
    payload noting the `docker_socket_proxy_targets` origin and the probe
    timestamp
- Allowed patch/update fields:
  - `description`, `tags`, `port` corrections, and `parent` assignment only
    when the target IP maps to an existing NetBox VM/interface record
    (explicit reparenting allowed to existing objects but do not create VMs)
  - The reconciler may add `runtime` or `last_seen` tags/fields to track
    probe freshness
- never-change:
  - Do NOT implicitly create VM objects from `docker_socket_proxy_targets`.
  - Do NOT overwrite operator-owned service metadata (for example, long
    human-maintained descriptions or SLAs) without explicit operator opt-in.
- delete/removal policy:
  - If a declared `docker_socket_proxy_targets` entry is removed from the
    stack-declared sources, reconciler should remove only the runtime service
    objects it created after a conservative decay period (or mark them as
    stale) rather than immediate hard-deletion.
  - If a probe no longer observes a service, follow decay → mark stale →
    delete (with operator review window configurable in code)
- Source of truth:
  - The declared `docker_socket_proxy_targets` mapping (stack metadata) plus
    successful probe evidence that ties runtime service to an existing
    NetBox VM/interface by IP. The reconciler MUST NOT treat an unresolved
    declared target as a signal to create VM inventory.

Appendix: example safe-patch field lists
---------------------------------------

- Device patch/update safe fields: `description`, `status`, `tags`,
  `platform`/`device_type` corrections, `primary_ip`
- Interface patch/update safe fields: `description`, `enabled`, `mac_address`,
  `tags`
- IP address patch/update safe fields: `description`, `status`, `dns_name`,
  `tags`, `assigned_object` (only when confirmed)

If a field is not listed above for a given object class, treat it as
operator-owned and do not change it automatically.

End.
