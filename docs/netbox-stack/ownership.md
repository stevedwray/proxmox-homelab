# NetBox Ownership Model

Purpose
-------

This document defines the ownership marker, the managed NetBox object classes,
and explicit create/patch/update/delete rules for the reconciler used by the
`netbox-stack` population workflow. It is strictly a documentation artifact —
no live NetBox changes or host-contacting validation are performed as part of
this document.

Ownership marker / tag strategy
--------------------------------

- Ownership marker: use the NetBox tag `managed-by-proxmox-homelab` on every
  object the reconciler creates or fully manages.
- Environment scoping: add an environment tag with the prefix
  `netbox-env-<env>` (e.g. `netbox-env-pve-test`) to separate objects created
  for different population environments.
- Creation rule: any object created by the reconciler must be tagged with the
  ownership marker (and the environment tag when applicable) at creation time.
- Ownership detection: the reconciler must verify presence of the ownership
  tag before performing any patch/update/delete on an existing object.

Managed NetBox object classes
------------------------------

Managed NetBox object classes (a non-exhaustive list aligned to the code):

- DCIM: sites, manufacturers, platforms, device-roles, device-types, devices,
  interfaces
- Virtualization: cluster-types, clusters, virtual-machines, virtualization
  interfaces
- IPAM: prefixes, VLANs, IP addresses, services
- Extras: tags (ownership tag must exist)

Owning source for each class
-----------------------------

- Sites, manufacturers, platforms, device-roles, device-types: repo-seeded
  definitions (the repo is the authoritative source).
- Devices, clusters, virtual-machines, virtualization interfaces: Proxmox
  discovery is the primary owner/source.
- Network items (prefixes, VLANs): network intent files in the repo are the
  authoritative seed; MikroTik discovery supplements runtime details.
- Services (ipam/services): runtime discovery (docker-socket-proxy or other
  runtime probes) — runtime sources own observed service objects and must tag
  them appropriately (see `runtime-source-*` tag semantics in code).

Create rules
------------

- The reconciler may create an object only when the owning source explicitly
  indicates the object should exist (e.g., Proxmox discovery reports a VM).
- Every created object MUST include the ownership marker `managed-by-proxmox-homelab`.
- Minimal initial payloads are preferred: create only required fields and
  ownership/environment tags; avoid populating optional business metadata.
- Do not create both a device/VM and its primary IP in the same implicit flow
  unless the IP is present in the owning source; prefer to create the device
  first, then ensure related interfaces/IPs deterministically.

Patch/update rules
------------------

- Only patch objects that carry the ownership marker. If the ownership tag is
  absent, the reconciler must not modify the object.
- Patch operations must be limited to a known safe set of fields per object
  class (for example: description, tags, parent references for services,
  interface enabled flags). Avoid overwriting rich business or operator-owned
  fields such as custom tenant metadata, contact lists, or rack elevations.
- When in doubt, prefer to `nb.ensure()`/idempotent upsert semantics that avoid
  destructive replacements.

Delete/removal rules
--------------------

- Only delete objects that are tagged with the ownership marker and where the
  owning source indicates the object was removed (explicit deletion signal).
- Never perform class-wide wipes as the normal reconciliation model — targeted
  deletions only.
- If a managed object is found without the ownership tag, do NOT delete it;
  instead surface it for operator review.

Explicit non-owned / out-of-scope objects
-----------------------------------------

- Racks, rack elevations, cables, power feeds, and circuits
- Tenants, contacts, and rich business metadata
- Firewall rules, DHCP configuration, and NAT rules
- Any object intentionally maintained by operators without the ownership tag

docker_socket_proxy_targets semantics
------------------------------------

- Stated rule: declared `docker_socket_proxy_targets` MUST map to existing
  NetBox VM or interface records by IP. The reconciler/populate augmentation
  may map declared addresses to existing inventory objects for reparenting
  runtime services, but it MUST NOT implicitly create VM objects from a
  declared `docker_socket_proxy_targets` address.
- Declared targets can be environment tokens (e.g. `${MONITORING_VM_IP}`) or
  literal IPs. The augmentation resolves tokens via environment variables and
  then attempts to find matching NetBox IP/interface records.
- If a declared target cannot be resolved to an existing NetBox VM/interface,
  the reconciler must log the mismatch and skip runtime reparenting for that
  target; it must not create a VM record to accommodate the target.

Notes and rationale
-------------------

- The `managed-by-proxmox-homelab` tag provides a simple and auditable
  ownership boundary. It allows coexistence with operator-managed objects in
  the same NetBox instance without accidental deletion or overwrite.
- The environment tag pattern `netbox-env-<env>` keeps separate population
  environments from interfering with each other in shared NetBox deployments.

Exit criteria
-------------

- A short `ownership` doc is present (this file) under `docs/netbox-stack/`.
- The ownership matrix clearly maps object classes to owning sources and
  includes create rules, patch/update rules, and delete/removal rules.
- Reviewers are able to answer: "If this object drifts, which source wins?"

If this doc needs refinement, iterate here and produce the session handback
`docs/netbox-stack/artifacts/SESSION-51-OWNERSHIP-LOCK-HANDBACK.md`.
