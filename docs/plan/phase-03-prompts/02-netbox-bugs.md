# Agent Prompt: NetBox Bug Fixes

Closes: #48, #49

---

You are working in the git repo at `/home/steve/git/proxmox-homelab`, currently on branch `dev/pve-test`.

## Task

Fix two bugs in the NetBox population scripts, then commit and push per the instructions at the end.

---

### 1. Create branch

```bash
git checkout -b fix/netbox-bugs dev/pve-test
```

---

### 2. Issue #48 — MikroTik primary_ip4 set to WAN IP instead of LAN IP

File: `terraform/lxc/stacks/netbox-stack/integrations/populate.py`

**Root cause:** `populate_network()` sets `primary_ip4` using `if not router_device.get("primary_ip4")` — correct guard, but the loop iterates interfaces in discovery order. If a WAN interface appears before the LAN interface, the WAN IP wins.

**Fix:**

Add this helper near the top of the file (after imports, before the first function):
```python
_INTERNAL_PREFIXES = ("192.168.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
                      "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                      "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")

def _is_internal_ip(address: str) -> bool:
    """Return True if address is an RFC 1918 private IP."""
    host = address.split("/")[0]
    return host.startswith(_INTERNAL_PREFIXES)
```

In `populate_network()`, find the block that sets `primary_ip4` (near end of the function, inside the `for ip_def in network.get("ip_addresses", []):` loop). Change the condition from:
```python
        if not router_device.get("primary_ip4") and "." in address:
```
to:
```python
        if not router_device.get("primary_ip4") and _is_internal_ip(address):
```

---

### 3. Issue #49 — gluetun-6881 service registered twice

**Root cause:** gluetun exposes port 6881 on both TCP and UDP. `build_vm_list()` in `discover.py` deduplicates on `(name, port, protocol)` — so both `gluetun-6881/tcp` and `gluetun-6881/udp` survive as separate entries. Then `populate_ipam()` in `populate.py` calls `nb.ensure()` using only `name` and `parent_object_id` as the lookup key — the second call finds the first registered service and applies wrong data.

**Fix:**

File: `terraform/lxc/stacks/netbox-stack/integrations/populate.py`, inside `populate_ipam()`, in the `for svc_def in vm_def.get("services", []):` loop.

Change the `nb.ensure()` call to include `protocol` in the lookup key so TCP and UDP create separate, correctly-identified records:
```python
            nb.ensure(NB_IPAM_SERVICES, {
                "name": svc_def["name"],
                "parent_object_type": "virtualization.virtualmachine",
                "parent_object_id": vm["id"],
                "protocol": svc_def["protocol"],
            }, {
                "name": svc_def["name"],
                "parent_object_type": "virtualization.virtualmachine",
                "parent_object_id": vm["id"],
                "ports": [svc_def["port"]],
                "protocol": svc_def["protocol"],
            })
```

Also verify that `build_full_topology()` and `build_topology()` in `discover.py` do not have a dedup step that collapses entries on `(name, port)` without protocol — if so, remove or fix it to preserve the protocol dimension.

---

### 4. Validate

```bash
cd terraform/lxc/stacks/netbox-stack/integrations

# Syntax check
python -m py_compile populate.py discover.py && echo "Syntax OK"

# If live credentials are available, run to confirm no crash and check gluetun appears twice with correct protocols:
# python populate.py
```

---

### 5. Commit and close

```bash
git add terraform/lxc/stacks/netbox-stack/integrations/populate.py \
        terraform/lxc/stacks/netbox-stack/integrations/discover.py

git commit -m "fix(netbox): correct MikroTik primary_ip4 and gluetun service dedup

- primary_ip4 now only set for RFC 1918 addresses, preventing WAN IP
  winning when WAN interface appears before LAN in discovery (Closes #48)
- Service ensure lookup now includes protocol, so gluetun-6881/tcp and
  gluetun-6881/udp register correctly as distinct records (Closes #49)"

git push origin fix/netbox-bugs

git checkout dev/pve-test
git merge fix/netbox-bugs
git push origin dev/pve-test

gh issue close 48 --comment "Fixed — primary_ip4 gated on RFC 1918 check via _is_internal_ip() helper."
gh issue close 49 --comment "Fixed — protocol included in nb.ensure() lookup key so TCP and UDP register as distinct services."
```
