"""Discover homelab topology from Proxmox, stack.yaml files, and Portainer API."""

import glob
import json
import os
import urllib.request
import urllib.error

import yaml

from proxmox_client import discover_from_proxmox


# ---------------------------------------------------------------------------
# Stack YAML discovery
# ---------------------------------------------------------------------------

def load_stack_yamls(stacks_dir=None):
    """Read all stack.yaml files under the stacks directory.

    Returns dict keyed by stack name.
    """
    if stacks_dir is None:
        stacks_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    stacks_dir = os.path.realpath(stacks_dir)

    stacks = {}
    for path in sorted(glob.glob(os.path.join(stacks_dir, "*/stack.yaml"))):
        # Skip .hold directory
        if "/.hold/" in path:
            continue
        name = os.path.basename(os.path.dirname(path))
        with open(path, encoding="utf-8") as f:
            stacks[name] = yaml.safe_load(f)
    return stacks


# ---------------------------------------------------------------------------
# Portainer discovery
# ---------------------------------------------------------------------------

class PortainerClient:
    """Minimal Portainer API client."""

    def __init__(self, url=None, password=None):
        self.url = (url or os.environ.get("PORTAINER_URL", "https://192.168.1.4:9443")).rstrip("/")
        self._password = password or os.environ["PORTAINER_ADMIN_PASSWORD"]
        self._token = None

    def _auth(self):
        if self._token:
            return
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        data = json.dumps({"username": "admin", "password": self._password}).encode()
        req = urllib.request.Request(
            f"{self.url}/api/auth",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, context=ctx) as resp:
            self._token = json.loads(resp.read().decode())["jwt"]

    def _get(self, path):
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self._auth()
        req = urllib.request.Request(
            f"{self.url}{path}",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        with urllib.request.urlopen(req, context=ctx) as resp:
            return json.loads(resp.read().decode())

    def get_endpoints(self):
        """Return list of endpoint dicts (excluding 'local')."""
        endpoints = self._get("/api/endpoints")
        return [e for e in endpoints if e["URL"] != "unix:///var/run/docker.sock"]

    def get_containers(self, endpoint_id):
        """Return list of container dicts for an endpoint."""
        try:
            return self._get(f"/api/endpoints/{endpoint_id}/docker/containers/json")
        except urllib.error.HTTPError:
            return []


# ---------------------------------------------------------------------------
# Build unified VM list
# ---------------------------------------------------------------------------

SKIP_CONTAINERS = {"portainer-agent"}


def build_vm_list(proxmox_data=None, stack_yamls=None, portainer=None):
    """Merge Proxmox (primary), stack.yaml, and Portainer (services) data.
    
    Proxmox is the authoritative source for container/VM existence and config.
    stack.yaml and Portainer enrich with metadata and services.
    
    Returns list of VM dicts with: name, ip, status, vcpus, memory, disk,
    description, tags, services, mounts.
    """
    if proxmox_data is None:
        proxmox_data = {"containers": [], "storage": []}
    
    yamls = stack_yamls or {}

    # Index Portainer endpoints by name for service discovery
    portainer_endpoints = {}
    if portainer:
        for ep in portainer.get_endpoints():
            ip = ep["URL"].replace("tcp://", "").split(":")[0]
            portainer_endpoints[ep["Name"]] = {
                "id": ep["Id"],
                "ip": ip,
                "status": "active" if ep["Status"] == 1 else "offline",
            }

    vms = []
    
    # Process all containers/VMs from Proxmox (authoritative source)
    for container in proxmox_data.get("containers", []):
        pve_name = container["name"]
        yml = yamls.get(pve_name, {})
        portainer_ep = portainer_endpoints.get(pve_name, {})
        
        # Get IP from Proxmox config (eth0)
        ip = None
        config = container.get("config", {})
        if "net0" in config:
            # Format: name=eth0,bridge=vmbr0,ip=192.168.1.30/24,...
            net0_parts = config["net0"].split(",")
            for part in net0_parts:
                if part.startswith("ip="):
                    ip = part.split("=", 1)[1]
                    break
        
        if not ip:
            # Fallback to stack.yaml
            ip_raw = yml.get("ip_address", "")
            if ip_raw:
                ip = ip_raw if "/" in ip_raw else f"{ip_raw}/24"
        
        if not ip:
            # Skip containers without IPs
            continue

        # Get vCPU and memory from Proxmox config or stack.yaml
        vcpus = int(config.get("cores", yml.get("cores", 2)))
        memory = int(config.get("memory", yml.get("memory", 2048)))
        
        # Get disk size from rootfs
        disk = yml.get("rootfs_size", 8)
        for mount in container.get("mounts", []):
            if mount.get("type") == "rootfs" and "size" in mount:
                # Parse "8G" to 8
                disk = int(mount["size"].rstrip("GT"))
                break
        
        vm = {
            "name": pve_name,
            "ip": ip,
            "status": container.get("status", "unknown"),
            "vcpus": vcpus,
            "memory": memory,
            "disk": disk,
            "description": yml.get("#", f"Proxmox {container['type'].upper()} VMID {container['vmid']}"),
            "tags": yml.get("tags", [pve_name.replace("-stack", ""), container["type"]]),
            "services": [],
            "mounts": container.get("mounts", []),
            "vmid": container["vmid"],
            "vm_type": container["type"],
            "node": container["node"],
        }

        # Discover services from Portainer containers (if this stack has an agent endpoint)
        if portainer and portainer_ep:
            try:
                containers = portainer.get_containers(portainer_ep["id"])
            except Exception:
                containers = []
            
            for c in containers:
                cname = c["Names"][0].lstrip("/")
                if cname in SKIP_CONTAINERS:
                    continue
                # Extract public ports
                for p in c.get("Ports", []):
                    pub = p.get("PublicPort")
                    if pub:
                        proto = p.get("Type", "tcp")
                        svc_name = f"{cname}-{pub}" if pub != 9001 else cname
                        vm["services"].append({
                            "name": svc_name,
                            "port": pub,
                            "protocol": proto,
                        })
            
            # Deduplicate services by (name, port, protocol)
            seen = set()
            deduped = []
            for s in vm["services"]:
                key = (s["name"], s["port"], s["protocol"])
                if key not in seen:
                    seen.add(key)
                    deduped.append(s)
            vm["services"] = deduped

        vms.append(vm)

    return vms


def build_topology():
    """Build the full topology dict from all available data sources.
    
    Priority: Proxmox (authoritative) → stack.yaml (metadata) → Portainer (services).
    """
    stacks_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    stack_yamls = load_stack_yamls(stacks_dir)

    portainer = None
    if os.environ.get("PORTAINER_ADMIN_PASSWORD"):
        portainer = PortainerClient()

    # Query Proxmox for authoritative container/VM list
    proxmox_data = discover_from_proxmox()

    vms = build_vm_list(proxmox_data, stack_yamls, portainer)

    # The Portainer server itself isn't a Proxmox container (it runs on management-stack).
    # We already have management-stack from Proxmox, but ensure Portainer services are listed.
    portainer_ip = os.environ.get("PORTAINER_SERVER_IP", "192.168.1.4")
    portainer_vms = [v for v in vms if v["ip"].startswith(portainer_ip)]
    if not portainer_vms:
        # Only add if not already discovered from Proxmox
        vms.append({
            "name": "portainer-api",
            "ip": f"{portainer_ip}/24",
            "status": "active",
            "vcpus": 2,
            "memory": 3072,
            "disk": 8,
            "description": "Portainer API endpoint (external)",
            "tags": ["management", "external"],
            "services": [
                {"name": "portainer", "port": 9443, "protocol": "tcp"},
            ],
            "mounts": [],
            "vmid": None,
            "vm_type": "external",
            "node": "external",
        })

    return vms


if __name__ == "__main__":
    vms = build_topology()
    print(f"Discovered {len(vms)} VMs:\n")
    for vm in vms:
        svcs = ", ".join(f"{s['name']}:{s['port']}" for s in vm["services"])
        tags = ", ".join(vm["tags"])
        print(f"  {vm['name']:20s} {vm['ip']:18s} {vm['status']:8s} "
              f"vcpus={vm['vcpus']} mem={vm['memory']}  [{tags}]")
        if svcs:
            print(f"    services: {svcs}")
