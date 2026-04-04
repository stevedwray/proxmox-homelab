"""Discover homelab topology from stack.yaml files and Portainer API."""

import glob
import json
import os
import urllib.request
import urllib.error

import yaml


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


def build_vm_list(stack_yamls=None, portainer=None):
    """Merge stack.yaml and Portainer data into a unified VM list.

    Each VM dict has: name, ip, status, vcpus, memory, disk, description,
    tags, services.
    """
    yamls = stack_yamls or {}

    # Index Portainer endpoints by name
    endpoints = {}
    if portainer:
        for ep in portainer.get_endpoints():
            ip = ep["URL"].replace("tcp://", "").split(":")[0]
            endpoints[ep["Name"]] = {
                "id": ep["Id"],
                "ip": ip,
                "status": "active" if ep["Status"] == 1 else "offline",
            }

    # Collect all VM names (union of both sources)
    all_names = sorted(set(list(yamls.keys()) + list(endpoints.keys())))

    vms = []
    for name in all_names:
        yml = yamls.get(name, {})
        ep = endpoints.get(name, {})

        # IP from yaml (strip /24) or Portainer
        ip_raw = yml.get("ip_address", "")
        if ip_raw:
            ip = ip_raw if "/" in ip_raw else f"{ip_raw}/24"
        elif ep.get("ip"):
            ip = f"{ep['ip']}/24"
        else:
            continue  # No IP, skip

        status = ep.get("status", "active") if ep else "active"

        vm = {
            "name": yml.get("hostname", name),
            "ip": ip,
            "status": status,
            "vcpus": yml.get("cores", 2),
            "memory": yml.get("memory", 2048),
            "disk": yml.get("rootfs_size", 8),
            "description": yml.get("#", f"LXC container: {name}"),
            "tags": yml.get("tags", [name.replace("-stack", ""), "docker"]),
            "services": [],
        }

        # Discover services from Portainer containers
        if portainer and ep:
            try:
                containers = portainer.get_containers(ep["id"])
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
    """Build the full topology dict from all available data sources."""
    stacks_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    stack_yamls = load_stack_yamls(stacks_dir)

    portainer = None
    if os.environ.get("PORTAINER_ADMIN_PASSWORD"):
        portainer = PortainerClient()

    vms = build_vm_list(stack_yamls, portainer)

    # The Portainer server itself isn't an agent endpoint.
    # Add it manually if not already present.
    portainer_ip = os.environ.get("PORTAINER_SERVER_IP", "192.168.1.4")
    if not any(v["ip"].startswith(portainer_ip) for v in vms):
        vms.append({
            "name": "portainer-server",
            "ip": f"{portainer_ip}/24",
            "status": "active",
            "vcpus": 2,
            "memory": 3072,
            "disk": 8,
            "description": "Central Portainer + NPM (VMID 101)",
            "tags": ["management", "docker"],
            "services": [
                {"name": "portainer", "port": 9443, "protocol": "tcp"},
                {"name": "npm-http", "port": 80, "protocol": "tcp"},
                {"name": "npm-https", "port": 443, "protocol": "tcp"},
            ],
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
