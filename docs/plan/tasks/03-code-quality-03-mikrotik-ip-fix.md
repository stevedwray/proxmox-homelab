# 03-code-quality-03 — MikroTik primary_ip4 bug fix (issue #48)

## Status

PENDING

## Phase

Phase 03 — Code Quality and Bug Fixes

## Prerequisites

- Phase 00 complete — branch is clean
- NetBox running at `192.168.1.30` (used for verification run)
- Python 3.12 available locally

## Objective

`populate.py` sets the MikroTik device's `primary_ip4` to `192.168.1.1` (the LAN IP) instead of the WAN IP after running, and issue #48 is closed.

## Scope

- `terraform/lxc/stacks/netbox-stack/integrations/populate.py`
- Add `_is_internal_ip()` helper and gate the `primary_ip4` assignment to the first RFC 1918 IP found

## Out of Scope

- `discover.py` or `proxmox_client.py` changes
- Other device types (only MikroTik is affected by this bug)
- Schema changes to NetBox

## Inputs

- `terraform/lxc/stacks/netbox-stack/integrations/populate.py` — read the full `populate_network()` function before editing
- `docs/plan/phase-03-code-quality.md` — Batch 3 for exact fix specification and the `INTERNAL_PREFIXES` tuple

## Expected Outputs

- `populate.py` — modified with `_is_internal_ip()` helper and guarded `primary_ip4` assignment

## Constraints and Conventions

- `primary_ip4` must be set to the **first** RFC 1918 address found, not the last
- Use `ip_str.startswith(INTERNAL_PREFIXES)` — do not import `ipaddress` module if not already used
- The fix must be idempotent: running populate.py twice must not create or update any objects on the second run
- Do not change the function signature of `populate_network()` or any other public function

## Acceptance Criteria

- [ ] `_is_internal_ip()` function exists in `populate.py`
- [ ] `primary_ip4` is only set when the IP is in an RFC 1918 range and has not been set yet
- [ ] Running `populate.py` against live NetBox results in MikroTik `primary_ip4 = 192.168.1.1`
- [ ] Running `populate.py` a second time produces 0 new objects (idempotency check)
- [ ] Issue #48 closed on GitHub

## Session Prompt

```
You are working in the proxmox-homelab repository at /home/steve/git/proxmox-homelab.

TASK: Fix a bug in populate.py that causes the MikroTik device's primary_ip4 to be set
to the WAN IP instead of the LAN IP.

BEFORE EDITING, READ THESE FILES:
  terraform/lxc/stacks/netbox-stack/integrations/populate.py
    Read the entire populate_network() function carefully
  docs/plan/phase-03-code-quality.md   (Batch 3 — root cause analysis and fix spec)

ROOT CAUSE:
  populate_network() iterates all MikroTik interfaces and sets primary_ip4 on every
  iteration that has an IP. The last interface processed wins — which happens to be the
  WAN-facing interface (121.99.xx.xx).

FIX:
  1. Add a module-level constant near the top of populate.py:
       INTERNAL_PREFIXES = ("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
                            "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                            "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")

  2. Add a helper function:
       def _is_internal_ip(ip_str: str) -> bool:
           """Return True if the IP address is in a known internal (RFC 1918) range."""
           return ip_str.startswith(INTERNAL_PREFIXES)

  3. In the loop that sets primary_ip4, gate the assignment:
       - Track a variable like primary_ip4 = None before the loop
       - In the loop, only set primary_ip4 if _is_internal_ip(ip_address) and primary_ip4 is None
       - This sets it to the FIRST internal IP found (not the last)

VERIFY:
  source .env
  cd terraform/lxc/stacks/netbox-stack/integrations
  python populate.py

  Then check in NetBox that MikroTik's primary_ip4 is now 192.168.1.1:
  curl -s -H "Authorization: Token ${NETBOX_SUPERUSER_API_TOKEN}" \
    "http://192.168.1.30/api/dcim/devices/?name=mikrotik" | jq '.[0].primary_ip4'

  Run populate.py a second time to verify idempotency (0 objects created):
  python populate.py
  # Should report: 0 created, 0 updated (or similar)

COMMIT:
  git add terraform/lxc/stacks/netbox-stack/integrations/populate.py
  git commit -m "fix(netbox): set MikroTik primary_ip4 to LAN IP not WAN IP (Closes #48)

Only set primary_ip4 for the first RFC 1918 address found.
Previously the last interface processed (WAN ip 121.99.x.x) won the assignment."

  git push origin dev/pve-test
  gh issue close 48 --comment "Fixed — primary_ip4 now set to first RFC 1918 IP (192.168.1.1)."

DONE WHEN: MikroTik primary_ip4 is 192.168.1.1 in NetBox and populate.py is idempotent.
```
