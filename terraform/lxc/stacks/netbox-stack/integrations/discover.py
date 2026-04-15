"""Discover homelab topology from Proxmox, Portainer, and Mikrotik."""

import glob
import json
import os
import urllib.request
import urllib.error

import yaml

from mikrotik_client import discover_from_mikrotik
from proxmox_client import discover_from_proxmox


FALLBACK_PORTAINER_SERVER_IP = "10.57.1.20"
FALLBACK_PORTAINER_URL = f"https://{FALLBACK_PORTAINER_SERVER_IP}:9443"


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


def _get_declared_portainer_ip(stack_yamls: dict) -> str | None:
    """Return the Portainer server IP declared in stack metadata, if any."""
    portainer_stack = stack_yamls.get("portainer-stack", {})
    ip_raw = portainer_stack.get("ip_address", "")
    if not ip_raw:
        return None
    return ip_raw.split("/", 1)[0]


def _resolve_portainer_endpoint(stack_yamls: dict) -> tuple[str, str]:
    """Resolve Portainer endpoint config from env vars, then declared metadata."""
    portainer_ip = (
        os.environ.get("PORTAINER_SERVER_IP")
        or _get_declared_portainer_ip(stack_yamls)
        or FALLBACK_PORTAINER_SERVER_IP
    )
    portainer_url = os.environ.get("PORTAINER_URL", f"https://{portainer_ip}:9443")
    return portainer_ip, portainer_url


# ---------------------------------------------------------------------------
# Portainer discovery
# ---------------------------------------------------------------------------

class PortainerClient:
    """Minimal Portainer API client."""

    def __init__(self, url=None, password=None):
        self.url = (url or os.environ.get("PORTAINER_URL") or FALLBACK_PORTAINER_URL).rstrip("/")
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


def _extract_ip_from_net0(net0_str: str) -> str | None:
    """Parse Proxmox net0 config string and return the IP with prefix."""
    for part in net0_str.split(","):
        if part.startswith("ip="):
            return part.split("=", 1)[1]
    return None


def _get_container_ip(container: dict, yml: dict) -> str | None:
    """Return the container's IP (with prefix), using Proxmox first."""
    config = container.get("config", {})
    net0 = config.get("net0")
    if net0:
        ip = _extract_ip_from_net0(net0)
        if ip:
            return ip

    ip_raw = yml.get("ip_address", "")
    if ip_raw:
        return ip_raw if "/" in ip_raw else f"{ip_raw}/24"
    return None


def _get_container_disk(container: dict, yml: dict) -> int:
    """Return disk size in GB from mounts or stack.yaml."""
    disk = yml.get("rootfs_size", 8)
    for mount in container.get("mounts", []):
        if mount.get("type") == "rootfs" and "size" in mount:
            # Parse "8G" to 8.
            return int(mount["size"].rstrip("GT"))
    return disk


def _build_portainer_services(portainer, portainer_ep: dict) -> list[dict]:
    """Query Portainer for running containers and return a deduplicated service list."""
    try:
        containers = portainer.get_containers(portainer_ep["id"])
    except Exception:
        containers = []

    services = []
    for c in containers:
        cname = c["Names"][0].lstrip("/")
        if cname in SKIP_CONTAINERS:
            continue
        for p in c.get("Ports", []):
            pub = p.get("PublicPort")
            if not pub:
                continue
            proto = p.get("Type", "tcp")
            svc_name = f"{cname}-{pub}" if pub != 9001 else cname
            services.append({
                "name": svc_name,
                "port": pub,
                "protocol": proto,
            })

    seen = set()
    deduped = []
    for svc in services:
        key = (svc["name"], svc["port"], svc["protocol"])
        if key not in seen:
            seen.add(key)
            deduped.append(svc)
    return deduped


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

        config = container.get("config", {})
        ip = _get_container_ip(container, yml)
        if not ip:
            # Skip containers without IPs
            continue

        vcpus = int(config.get("cores", yml.get("cores", 2)))
        memory = int(config.get("memory", yml.get("memory", 2048)))
        disk = _get_container_disk(container, yml)
        
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
            vm["services"] = _build_portainer_services(portainer, portainer_ep)

        vms.append(vm)

    return vms


def build_topology():
    """Build the full topology dict from all available data sources.
    
    Priority: Proxmox (authoritative) → stack.yaml (metadata) → Portainer (services).
    """
    stacks_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    stack_yamls = load_stack_yamls(stacks_dir)
    portainer_ip, portainer_url = _resolve_portainer_endpoint(stack_yamls)

    portainer = None
    if os.environ.get("PORTAINER_ADMIN_PASSWORD"):
        portainer = PortainerClient(url=portainer_url)

    # Query Proxmox for authoritative container/VM list
    proxmox_data = discover_from_proxmox()

    vms = build_vm_list(proxmox_data, stack_yamls, portainer)

    # The Portainer server itself isn't a Proxmox container (it runs on management-stack).
    # We already have management-stack from Proxmox, but ensure Portainer services are listed.
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


def build_network_topology():
    """Build router and network topology from Mikrotik.

    Returns a dict with router metadata, interfaces, VLANs, and IP addresses.
    If Mikrotik credentials are not configured, returns an empty topology.
    """
    if not (os.environ.get("MIKROTIK_USER") and os.environ.get("MIKROTIK_PASSWORD")):
        return {
            "router": None,
            "interfaces": [],
            "vlans": [],
            "ip_addresses": [],
        }

    data = discover_from_mikrotik()
    return {
        "router": data.get("router"),
        "interfaces": data.get("interfaces", []),
        "vlans": data.get("vlans", []),
        "ip_addresses": data.get("ip_addresses", []),
    }


def build_full_topology():
    """Build the full homelab topology payload.

    Returns:
    {
        "vms": [...],
        "network": {...}
    }
    """
    return {
        "vms": build_topology(),
        "network": build_network_topology(),
    }


if __name__ == "__main__":
    full = build_full_topology()
    vms = full["vms"]
    network = full["network"]
    print(f"Discovered {len(vms)} VMs:\n")
    for vm in vms:
        svcs = ", ".join(f"{s['name']}:{s['port']}" for s in vm["services"])
        tags = ", ".join(vm["tags"])
        print(f"  {vm['name']:20s} {vm['ip']:18s} {vm['status']:8s} "
              f"vcpus={vm['vcpus']} mem={vm['memory']}  [{tags}]")
        if svcs:
            print(f"    services: {svcs}")

    router = network.get("router")
    if router:
        print("\nNetwork Discovery:")
        print(f"  router: {router.get('identity', 'Mikrotik')} @ {router.get('host', '')}")
        print(f"  interfaces: {len(network.get('interfaces', []))}")
        print(f"  vlans: {len(network.get('vlans', []))}")
        print(f"  router IPs: {len(network.get('ip_addresses', []))}")
