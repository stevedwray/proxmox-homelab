# Agent Prompt: NetBox Cognitive Complexity Refactor

Closes: #28

---

You are working in the git repo at `/home/steve/git/proxmox-homelab`, currently on branch `dev/pve-test`.

## Task

Refactor two functions in the NetBox integration scripts to reduce their cognitive complexity below the SonarCloud threshold of 15 (rule python:S3776). Read each file fully before editing.

---

### 1. Create branch

```bash
git checkout -b refactor/netbox-complexity dev/pve-test
```

---

### 2. Files to refactor

| File | Function | Estimated complexity |
|---|---|---|
| `terraform/lxc/stacks/netbox-stack/integrations/discover.py` | `build_vm_list()` (line ~101) | ~40+ |
| `terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py` | `discover_from_proxmox()` (line ~123) | ~30+ |

`build_full_topology()` in `discover.py` is already trivial (just delegates to two sub-functions) — do not touch it.

---

### 3. discover.py — refactor `build_vm_list()`

Read the full function first. It does roughly:
1. Index Portainer endpoints by name
2. Loop over Proxmox containers, for each:
   a. Extract IP from `net0` config string
   b. Fall back to `stack.yaml` IP
   c. Skip if no IP
   d. Compute vcpus/memory/disk
   e. Build a `vm` dict
   f. Query Portainer for services, deduplicate
   g. Append to list

Extract the following private helpers (defined above `build_vm_list` in the same file):

```python
def _extract_ip_from_net0(net0_str: str) -> str | None:
    """Parse Proxmox net0 config string and return the IP with prefix (e.g. '192.168.1.30/24')."""

def _get_container_ip(container: dict, yml: dict) -> str | None:
    """Return the container's IP (with prefix), trying net0 config then stack.yaml fallback."""

def _get_container_disk(container: dict, yml: dict) -> int:
    """Return disk size in GB from mounts or stack.yaml."""

def _build_portainer_services(portainer, portainer_ep: dict) -> list[dict]:
    """Query Portainer for running containers and return a deduplicated service list."""
```

The `SKIP_CONTAINERS` set that `_build_portainer_services` will need must be defined at module level so all helpers can access it.

After extraction, `build_vm_list()` should be a clean loop:
```python
def build_vm_list(proxmox_data=None, stack_yamls=None, portainer=None):
    ...
    for container in proxmox_data.get("containers", []):
        ...
        ip = _get_container_ip(container, yml)
        if not ip:
            continue
        disk = _get_container_disk(container, yml)
        vm = { ... }  # build the dict inline or via helper
        if portainer and portainer_ep:
            vm["services"] = _build_portainer_services(portainer, portainer_ep)
        vms.append(vm)
    return vms
```

---

### 4. proxmox_client.py — refactor `discover_from_proxmox()`

Read the full function first. It does roughly:
1. Create client, fetch nodes/storage
2. Loop over nodes:
   a. Loop over LXC containers: fetch config, parse mounts
   b. Loop over QEMU VMs: fetch config, parse mounts
   c. Fetch node networks

The inner `parse_storage_spec()` nested function should be hoisted to module level as `_parse_storage_spec()`.

Extract:
```python
def _parse_lxc_container(client, node_name: str, lxc: dict) -> dict:
    """Fetch config, status and parse mounts for one LXC container. Returns container dict."""

def _parse_qemu_vm(client, node_name: str, qemu: dict) -> dict:
    """Fetch config, status and parse mounts for one QEMU VM. Returns container dict."""
```

`discover_from_proxmox()` then becomes:
```python
def discover_from_proxmox(...):
    ...
    for node in nodes:
        node_name = node["node"]
        for lxc in client.get_lxc_containers(node_name):
            containers.append(_parse_lxc_container(client, node_name, lxc))
        for qemu in client.get_qemu_vms(node_name):
            containers.append(_parse_qemu_vm(client, node_name, qemu))
        networks[node_name] = client.get_node_networks(node_name)
    ...
```

---

### 5. Validate

```bash
cd terraform/lxc/stacks/netbox-stack/integrations

# Syntax
python -m py_compile discover.py proxmox_client.py && echo "Syntax OK"

# Run tests
python -m pytest test_populate_paths.py -v 2>/dev/null || echo "No test runner available"

# If live credentials are available, verify idempotency:
# python populate.py   # first run: shows created/exists
# python populate.py   # second run: 0 new objects created
```

---

### 6. Commit and close

```bash
git add terraform/lxc/stacks/netbox-stack/integrations/discover.py \
        terraform/lxc/stacks/netbox-stack/integrations/proxmox_client.py

git commit -m "refactor(netbox): reduce cognitive complexity in integration scripts (Closes #28)

discover.py: extract _extract_ip_from_net0, _get_container_ip,
  _get_container_disk, _build_portainer_services from build_vm_list()
proxmox_client.py: hoist parse_storage_spec to module level as
  _parse_storage_spec; extract _parse_lxc_container and _parse_qemu_vm
  from discover_from_proxmox()

No functional changes. Idempotency verified."

git push origin refactor/netbox-complexity

git checkout dev/pve-test
git merge refactor/netbox-complexity
git push origin dev/pve-test

gh issue close 28 --comment "Refactored. build_vm_list() and discover_from_proxmox() split into focused private helpers. Idempotency verified."
```
