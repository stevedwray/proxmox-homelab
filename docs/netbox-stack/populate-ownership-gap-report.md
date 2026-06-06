# Populate: Ownership Gap Report

Context
-------

Reviewed files:

- `docs/netbox-stack/ownership.md`
- `docs/netbox-stack/ownership-field-rules.md`
- `terraform/lxc/stacks/netbox-stack/integrations/populate.py`
- tests:
  - `terraform/lxc/stacks/netbox-stack/integrations/tests/test_augment.py`
  - `terraform/lxc/stacks/netbox-stack/integrations/tests/test_service_reparent.py`
  - `terraform/lxc/stacks/netbox-stack/integrations/test_populate_socket_proxy_targets.py`

Method
------

Static code review of `populate.py` (and `client.py`) to compare behavior
against the documented ownership and per-field rules in
`ownership.md` and `ownership-field-rules.md`.

Summary
-------

This report lists what the current populate implementation enforces, where
enforcement is partial, what is missing, observed risks/ambiguities, and a
concise set of recommended next code changes (practical, minimal, testable).

Rules already enforced in code
-----------------------------

- Tags: creation and canonical managed tag handling is implemented.
  - Code: `_ensure_tags`, `_managed_tag_refs`, used in `populate_foundation`.
  - Effect: ownership tag `managed-by-proxmox-homelab` and environment tags
    are created before object creation.

- Ownership detection before certain operations is enforced.
  - Code: `_tag_slugs()` is used in `_try_reparent_runtime_service` and
    `reconcile_service_env_tags` to verify presence of `MANAGED_TAG_SLUG`.

- Do-not-create-from-declared-targets rule for socket-proxy augmentation.
  - Code: `_augment_vms_with_declared_socket_proxy_targets` explicitly
    documents "This function will not create new NetBox VM objects" and
    implements mapping-only behavior.
  - Tests: `test_augment.py`, `test_populate_socket_proxy_targets.py` assert
    correct mapping and non-creation semantics.

- Conservative reparenting for runtime services.
  - Code: `_try_reparent_runtime_service` only reparents when an unambiguous
    single managed runtime match exists and when `REPARENT_RUNTIME_SOCKET_PROXY`
    is enabled.
  - Tests: `test_try_reparent_runtime_service_patches_unique_match`.

- Scoped deletion/cleaning only targets objects carrying the managed or
  environment tags.
  - Code: `clean()` uses `SHARED_CLEAN_FILTERS` / `_environment_filters`
    and checks tag existence before performing deletes.

Rules partially enforced (partial)
----------------------------------

- Patch/update field scoping is only partially enforced (partial).
  - Observation: `NetBoxClient.ensure()` computes `desired = lookup + defaults`
    and `_build_patch()` will generate a patch for any differing field in
    `desired`. There is no per-path whitelist of allowed patch fields.
  - Impact: callers often pass many defaults (e.g. `slug`, `platform`,
    `device_type`, `primary_ip4`) which can be used to patch fields the
    ownership doc treats as operator-owned unless the repo is the source.
  - Locations in code: `populate_foundation`, `populate_physical`,
    `populate_virtual`, `populate_ipam` call `nb.ensure()` with broad defaults.

- Tag preservation vs replacement (partial).
  - Observation: code frequently replaces the `tags` field (e.g. in
    `_try_reparent_runtime_service` and `reconcile_service_env_tags`) by
    providing a new `tags` payload to `nb.patch_object` or `nb.ensure`.
  - Impact: runtime-managed tags are preserved, but arbitrary operator tags
    (non-managed, non-runtime) will be lost during these updates.

- Interface reparenting protection (partial).
  - Observation: most interface `ensure` calls lookup by `device_id` and
    `name`, which avoids accidental reparent, but there is no centralized
    guard preventing other code paths from reparenting existing interfaces.

Rules not enforced / missing (explicit)
--------------------------------------

- No programmatic enforcement of per-field "never-change" lists (missing).
  - The ownership-field-rules document enumerates field-level never-change
    constraints (example: device `asset_tag`, VM `name` canonicalization,
    site canonical `slug`). There is no code-level whitelist/blacklist to
    prevent accidental patches to these fields.
  - Where to change: `NetBoxClient._build_patch()` (and `ensure()` callers)
    should accept an `allowed_patch_fields` set to constrain patches.

- No automatic preservation of operator-managed tags (missing).
  - When `nb.patch_object(..., {"tags": ...})` is called, existing
    non-managed tags are dropped. The code preserves managed/runtime tags but
    does not preserve other operator tags.

- No conservative decay window for runtime service removal (missing).
  - `populate_ipam` currently deletes managed services that are not desired
    immediately: `nb.delete_object(NB_IPAM_SERVICES, existing_service)`.
  - Ownership-field-rules recommend mark-stale → decay → delete; code
    deletes directly during a populate run.

- No consistent recording of structured provenance/source metadata for
  runtime-created services (missing).
  - Current practice: service `description` includes `last-seen` text; a
    `runtime-source-...` tag is added, but there is no structured `source`
    payload or custom-field consistently written for later auditing.

Risky behavior and ambiguity (risks)
------------------------------------

- Tag-replacement risk: overwriting `tags` can remove operator-applied tags
  unexpectedly. Risk functions: `_try_reparent_runtime_service`,
  `reconcile_service_env_tags`, places where `nb.ensure(..., {"tags": ...})`
  is used.

- Over-eager patching: `nb.ensure()` will patch any field included in the
  supplied `defaults`. Without a whitelist, fields that should be operator-
  owned can be modified.

- Immediate hard-deletion of runtime services increases blast radius.

- Implicit assumptions about NetBox field shapes (tags as dicts vs strings)
  can lead to mismatches when merging/preserving tags.

Recommended next code change (practical, minimal, test-first)
-----------------------------------------------------------

Priority 1 — Small behavioral guard rails (low-risk, high-impact):

1) Add per-path allowed patch fields support to the client or call sites.
   - Change: extend `NetBoxClient.ensure()` and/or `_build_patch()` to accept
     an optional parameter `allowed_patch_fields: set[str]` that filters the
     computed `changes` to only those keys. Example change site:

   - Call-site example (device safe fields):

     allowed = {"description", "status", "tags", "platform", "device_type", "primary_ip4"}
     nb.ensure(NB_DCIM_DEVICES, {"name": dev_name}, defaults, allowed_patch_fields=allowed)

   - Rationale: this produces an explicit mapping between the document's
     allowed-patch list and runtime behavior (enforceable, testable).

2) Preserve operator tags when updating tags (merge instead of replace).
   - Change: add a helper `nb.merge_and_patch_tags(path, obj, desired_tag_refs)`
     or implement tag-merge in populate call sites before calling
     `nb.patch_object(...)`.
   - Behavior: compute union = (existing non-managed tags) ∪ (managed tags)
     and patch only if union changes. Keep runtime/managing tags removal logic
     unchanged for cleanup flows but default to merging for reconciliation.

Priority 2 — Safety & provenance (medium effort):

3) Replace immediate deletion of runtime services with mark-stale / decay.
   - Change: update `populate_ipam` to mark candidate service objects as
     `stale` (via a tag `managed-stale` or via description update) and only
     hard-delete in `clean()` (or after N reconciliation cycles). Add a
     small config toggle to control the decay window.

4) Record structured provenance for runtime-created services.
   - Change: include `runtime_source` metadata in either a custom field or
     a structured `description` with consistent parsing. This aids audits
     and reduces ambiguity when deciding whether an object came from a probe.

Priority 3 — Tests and automation (short list of unit tests to add):

- `test_allowed_patch_fields.py`: assert that calling `ensure()` with
  `allowed_patch_fields` does not modify fields outside the set.
- `test_tag_merge_preserves_operator_tags.py`: ensure tag merge preserves
  non-managed tags.
- `test_runtime_service_decay.py`: ensure services are marked stale first,
  then deleted only after the decay window or by the `clean()` path.

Where to implement (function map)
---------------------------------

- Client change: `terraform/lxc/stacks/netbox-stack/integrations/client.py`
  - `_build_patch()`, `ensure()` should accept and propagate
    `allowed_patch_fields`.

- Populate changes: `terraform/lxc/stacks/netbox-stack/integrations/populate.py`
  - Call sites: `populate_foundation`, `populate_physical`, `populate_virtual`,
    `populate_ipam`, `reconcile_service_env_tags`, `_try_reparent_runtime_service`
  - Add a small helper in `populate.py` to compute merged tag lists.

Validation checklist
--------------------

- Add unit tests named above and run the existing tests to ensure no regressions
  in augment/reparent behavior (`test_augment.py`, `test_service_reparent.py`,
  `test_populate_socket_proxy_targets.py`).

Appendix: short actionable roadmap (3 sprints)
---------------------------------------------

Sprint A (small): implement `allowed_patch_fields` + tag merge helper, add
tests for both.
Sprint B (medium): implement service decay mark + tests, add provenance
fields for runtime services.
Sprint C (cleanup): audit callers to remove unnecessary defaults in
`ensure()` so that `ensure()` only creates minimal create-only fields and
patching is done explicitly using `allowed_patch_fields`.

End of report.
# Populate Ownership Gap Report (Session 53)

Summary
-------

This report compares `terraform/lxc/stacks/netbox-stack/integrations/populate.py`
against the documented ownership model in `docs/netbox-stack/ownership.md` and
the per-field rules in `docs/netbox-stack/ownership-field-rules.md`.

Files reviewed
- `terraform/lxc/stacks/netbox-stack/integrations/populate.py`
- `terraform/lxc/stacks/netbox-stack/integrations/client.py`
- `terraform/lxc/stacks/netbox-stack/integrations/tests/test_augment.py`
- `terraform/lxc/stacks/netbox-stack/integrations/tests/test_service_reparent.py`
- `terraform/lxc/stacks/netbox-stack/integrations/test_populate_socket_proxy_targets.py`
- `docs/netbox-stack/ownership.md`
- `docs/netbox-stack/ownership-field-rules.md`

Method
------

- Static read of the implementation and unit tests listed above.
- Cross-checked code locations and helper functions for ownership-tag logic
  and guarded delete/patch behavior.

Findings
--------

Enforced rules
--------------

- Ownership tag creation and existence checks:
  - `_ensure_tags()` creates tag objects (see `populate._ensure_tags`).
  - `MANAGED_TAG_NAME` / `MANAGED_TAG_SLUG` are used consistently when
    constructing `tags` payloads for created objects (see
    `populate._managed_tag_refs`).

- Deletions and cleanup are guarded by tags:
  - `clean()` uses `SHARED_CLEAN_FILTERS` and `_environment_filters` to only
    enumerate and delete objects matching `managed-by-proxmox-homelab` and the
    environment tag.
  - `populate_ipam()` deletes only IP objects that include the desired
    managed/env tags (it checks `desired_tags.issubset(_tag_slugs(...))`).

- Runtime-source tagging and conservative reparenting:
  - Services created from probes are tagged with `runtime-source-<source>`.
  - `_try_reparent_runtime_service()` only considers candidates that carry
    `MANAGED_TAG_SLUG` and `runtime-source-socket-proxy` and requires an
    unambiguous single match before calling `nb.patch_object` (tested by
    `test_try_reparent_runtime_service_patches_unique_match`).

- Augmentation for `docker_socket_proxy_targets`:
  - `_augment_vms_with_declared_socket_proxy_targets()` explicitly avoids
    creating new VM objects and maps declared addresses only to existing
    NetBox VM/interface records by querying IP objects and virtual interfaces
    (validated by `test_augment_portainer_mapping` and
    `TestPopulateSocketProxyTargets`).

Partially enforced rules
------------------------

- Field-level restrictions are generally respected by what the code *writes*
  (the code prefers minimal payloads: description, tags, small platform/role
  fields). Examples:
  - `populate_virtual()` writes `description`, `vcpus`, `memory`, `disk`,
    and `tags` but avoids rich business metadata.
  - `populate_network()` picks a canonical VLAN name rather than overwriting
    multiple discovered names.

  However, these protections are implemented by *omission* in payloads
  rather than by an explicit per-field whitelist enforcement at patch time.

- Deletion gating is strict, but create/patch semantics are asymmetrical: the
  code will create objects carrying the managed tag and will patch existing
  objects via `nb.ensure()` even when those existing objects did not
  originally carry the ownership tag (see "Not enforced" below). Thus,
  deletion is strictly gated, but the path that can lead an object to be
  tagged (and therefore later deletable) is only partially constrained.

Not enforced / Missing
----------------------

- Ownership check before patch/update (missing):
  - `NetBoxClient.ensure()` will patch any existing object that differs from
    the desired payload. `populate.py` calls `nb.ensure()` widely
    (e.g. `populate_foundation`, `populate_physical`, `populate_network`,
    `populate_virtual`, `populate_ipam`) without first verifying whether the
    live object already carries `managed-by-proxmox-homelab`. This means an
    existing operator-managed object that lacks the ownership tag can be
    modified and retagged by the reconciler during an `ensure()` run.

- Explicit never-change field guards (missing):
  - There is no central whitelist/denylist applied when building `changes`
    in `NetBoxClient._build_patch()` or in `populate.py` before calling
    `nb.patch_object()`; protection of "never-change" fields is implicit by
    not including them in the `defaults` payloads rather than enforced.

- Primary-ip and assigned-object reparenting gate (partial/missing):
  - The code sometimes patches `primary_ip4` (`populate_network()` and
    `populate_ipam()`) and assigns `assigned_object_type`/`assigned_object_id`
    when calling `nb.ensure()` for IPs. There is not an explicit check that
    the IP or the parent device already carried the managed tag before
    applying these patches.

Risks and ambiguities
---------------------

- Risk: accidental takeover of operator-managed objects — because `ensure()`
  will patch existing records, the reconciler can add the ownership tag to
  objects that were previously operator-maintained, making them eligible for
  later automated deletion.

- Ambiguity: repo-seeded vs discovered ownership boundaries are implicit
  in the code (the developer intent is visible in comments and which
  sections call `ensure()`), but there's no programmatic per-class policy
  table enforced in the code. This increases maintenance risk when new
  object classes are added or when expected ownership boundaries change.

- Race/window: concurrent runs that mutate tags could cause transient
  reparent/cleanup behavior if tagging and deletion are not coordinated.

- Augmentation subtlety: `_augment_vms_with_declared_socket_proxy_targets()`
  resolves `${TOKEN}` values and probes addresses. If a token resolves to an
  operator-managed IP that maps to a VM without the managed tag, the code
  will attach a managed vm_def and later create managed services for it —
  again creating a takeover path if not gated.

Recommended next code change
----------------------------

recommended next code change: introduce an ownership-aware ensure wrapper and
apply it to non-repo-seeded classes.

Concrete, minimal implementation sketch:

1. Add helper to `populate.py`:

   ```py
   def _ensure_respecting_ownership(nb, path, lookup, defaults=None, *, allow_repo_seed=False):
       """Ensure object exists; but do not patch an existing operator-owned object.

       - If object does not exist: create with provided defaults (and tags).
       - If object exists and carries MANAGED_TAG_SLUG, call `nb.ensure()`
         (preserve current behavior).
       - If object exists and does NOT carry MANAGED_TAG_SLUG:
           - If `allow_repo_seed` is True: treat as repo-seeded and allow patch.
           - Otherwise: skip patch and print a clear skip message.
       """
       results = nb.get(path, **lookup)
       if results.get('count', 0) == 0:
           return nb.ensure(path, lookup, defaults)
       obj = results['results'][0]
       if MANAGED_TAG_SLUG in _tag_slugs(obj) or allow_repo_seed:
           return nb.ensure(path, lookup, defaults)
       print(f"  skip (operator-owned): {path} → {obj.get('name')} (id={obj.get('id')})")
       return obj
   ```

2. Replace direct `nb.ensure(...)` calls in code paths that must not
   retag/operator-takeover (devices, VMs, interfaces, ip addresses, runtime
   services) with `_ensure_respecting_ownership(..., allow_repo_seed=False)`.
   Keep `allow_repo_seed=True` for explicitly repo-seeded classes:
   - `NB_DCIM_SITES`, `NB_DCIM_MANUFACTURERS`, `NB_DCIM_PLATFORMS`,
     `NB_DCIM_DEVICE_ROLES`, `NB_DCIM_DEVICE_TYPES`, `NB_VIRT_CLUSTER_TYPES`.

3. Add unit tests that assert the gating behavior:
   - New test that ensures existing object without managed tag is not patched
     (use MagicMock to observe that `nb.patch`/`nb.patch_object` was *not*
     called).
   - Tests for repo-seeded classes that validate patching is still allowed.

4. Optionally expose a similar parameter on `NetBoxClient.ensure()` so the
   ownership policy is implemented at the client level rather than sprinkling
   wrapper calls across `populate.py`.

Specific places to apply change (function names):

- `populate_foundation()` — allow repo-seed patching (allow_repo_seed=True)
- `populate_physical()` — use wrapper for device/interface ensures
- `populate_network()` — use wrapper for router/ VLAN/ IP ensure calls
- `populate_virtual()` — use wrapper for VM/interface ensures
- `populate_ipam()` — use wrapper for IP/service ensure calls when the
  target may already be operator-managed

Tests referenced
----------------

- `terraform/lxc/stacks/netbox-stack/integrations/tests/test_augment.py`
- `terraform/lxc/stacks/netbox-stack/integrations/tests/test_service_reparent.py`
- `terraform/lxc/stacks/netbox-stack/integrations/test_populate_socket_proxy_targets.py`

Appendix: quick evidence grep
-----------------------------

- Key ownership usages are in `populate._ensure_tags`, `_managed_tag_refs`,
  and the `clean()` and `reconcile_service_env_tags()` functions. The places
  where `nb.ensure()` is called broadly are where the ownership gating should
  be focused.

End of report.
