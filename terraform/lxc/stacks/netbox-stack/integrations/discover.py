"""Discover homelab topology from Proxmox and Mikrotik."""

import glob
import json
import os
import re
import socket
import subprocess
import urllib.parse
import urllib.request
import urllib.error

import yaml

from mikrotik_client import discover_from_mikrotik
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


def _get_declared_portainer_ip(stack_yamls: dict) -> str | None:
    """Return the Portainer server IP declared in stack metadata, if any."""
    portainer_stack = stack_yamls.get("portainer-stack", {})
    ip_raw = portainer_stack.get("ip_address", "")
    if not ip_raw:
        return None
    return ip_raw.split("/", 1)[0]


def _resolved_env_value(name: str) -> str | None:
    """Return env value unless it is empty or still an unresolved ${...} template."""
    raw = os.environ.get(name)
    if not raw:
        return None
    value = raw.strip()
    if not value or (value.startswith("${") and value.endswith("}")):
        return None
    return value


def _resolve_portainer_endpoint(stack_yamls: dict) -> tuple[str | None, str | None]:
    """Resolve Portainer endpoint config from env vars, then declared metadata.

    Returns (ip, url) or (None, None) when no Portainer endpoint is configured.
    """
    portainer_ip = (
        _resolved_env_value("PORTAINER_SERVER_IP")
        or _resolved_env_value("LAB_IP_PORTAINER")
        or _get_declared_portainer_ip(stack_yamls)
    )

    if not portainer_ip:
        # Portainer is optional; return a null result instead of raising so callers
        # can decide whether to use Portainer enrichment or not.
        return None, None

    portainer_url = _resolved_env_value("PORTAINER_URL") or f"https://{portainer_ip}:9443"
    return portainer_ip, portainer_url


# ---------------------------------------------------------------------------
# Portainer discovery
# ---------------------------------------------------------------------------

class PortainerClient:
    """Minimal Portainer API client."""

    def __init__(self, url=None, password=None, api_key=None):
        resolved_url = url or _resolved_env_value("PORTAINER_URL")
        if not resolved_url:
            resolved_ip = _resolved_env_value("PORTAINER_SERVER_IP") or _resolved_env_value("LAB_IP_PORTAINER")
            if not resolved_ip:
                raise ValueError(
                    "Portainer URL is unresolved; set PORTAINER_URL, PORTAINER_SERVER_IP, or LAB_IP_PORTAINER"
                )
            resolved_url = f"https://{resolved_ip}:9443"

        self.url = resolved_url.rstrip("/")
        self._api_key = api_key
        self._password = password or (None if api_key else os.environ["PORTAINER_ADMIN_PASSWORD"])
        self._token = None

    def _ssl_ctx(self):
        import ssl
        # TODO: replace with verified TLS once Portainer is fronted by a
        # step-ca or LE cert. Until then, cert verification is disabled because
        # the Portainer endpoint uses a self-signed cert on the internal network.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _auth(self):
        if self._token:
            return
        data = json.dumps({"username": "admin", "password": self._password}).encode()
        req = urllib.request.Request(
            f"{self.url}/api/auth",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, context=self._ssl_ctx()) as resp:
            self._token = json.loads(resp.read().decode())["jwt"]

    def _get(self, path):
        if self._api_key:
            headers = {"X-API-Key": self._api_key}
        else:
            self._auth()
            headers = {"Authorization": f"Bearer {self._token}"}
        req = urllib.request.Request(f"{self.url}{path}", headers=headers)
        with urllib.request.urlopen(req, context=self._ssl_ctx()) as resp:
            return json.loads(resp.read().decode())

    def get_endpoints(self):
        """Return list of all Portainer endpoint dicts."""
        return self._get("/api/endpoints")

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


def _detect_topology_environment() -> str | None:
    """Return the selected topology environment from current env vars."""
    for name in ("NETBOX_NETWORK_ENV", "PVE_ENV", "TF_VAR_proxmox_node"):
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip()
    return None


def _preferred_proxmox_host_interface() -> str:
    """Return the preferred hypervisor interface name for host IP selection."""
    raw = os.environ.get("NETBOX_PROXMOX_HOST_INTERFACE")
    return raw.strip() if raw and raw.strip() else "vmbr0"


def _network_entry_cidr(entry: dict) -> str | None:
    """Return one CIDR string from a Proxmox node-network entry, if present."""
    cidr = entry.get("cidr")
    if isinstance(cidr, str) and cidr.strip():
        return cidr.strip()

    address = entry.get("address")
    netmask = entry.get("netmask")
    if isinstance(address, str) and address.strip() and netmask not in (None, ""):
        return f"{address.strip()}/{netmask}"
    return None


def _select_proxmox_host_address(
    proxmox_data: dict,
    target_node: str | None = None,
    preferred_iface: str | None = None,
) -> tuple[str | None, str | None]:
    """Select the inspected Proxmox host address from discovered node networks."""
    preferred_iface = preferred_iface or _preferred_proxmox_host_interface()
    networks_by_node = proxmox_data.get("networks", {}) if isinstance(proxmox_data, dict) else {}
    nodes = list(networks_by_node)
    if not target_node:
        if len(nodes) == 1:
            target_node = nodes[0]
        else:
            target_node = _detect_topology_environment()

    if not target_node:
        return None, preferred_iface

    node_networks = networks_by_node.get(target_node, [])
    if not isinstance(node_networks, list):
        return None, preferred_iface

    preferred = None
    fallback = None
    for entry in node_networks:
        if not isinstance(entry, dict):
            continue
        cidr = _network_entry_cidr(entry)
        if not cidr:
            continue
        iface = entry.get("iface")
        if iface == preferred_iface:
            preferred = (cidr, iface)
            break
        if fallback is None:
            fallback = (cidr, iface)

    if preferred:
        return preferred
    if fallback:
        return fallback
    return None, preferred_iface


def build_proxmox_context(proxmox_data=None):
    """Build source-node metadata for the currently inspected Proxmox environment."""
    if proxmox_data is None:
        proxmox_data = discover_from_proxmox()

    target_node = _detect_topology_environment()
    host_address, host_interface = _select_proxmox_host_address(
        proxmox_data,
        target_node=target_node,
    )

    return {
        "target_node": target_node,
        "host_address": host_address,
        "host_interface": host_interface,
    }


def _extract_ip_from_net0(net0_str: str) -> str | None:
    """Parse Proxmox net0 config string and return the IP with prefix."""
    for part in net0_str.split(","):
        if part.startswith("ip="):
            return part.split("=", 1)[1]
    return None


def _get_container_ip(container: dict) -> str | None:
    """Return the container's IP (with prefix) from Proxmox config only."""
    config = container.get("config", {})
    net0 = config.get("net0")
    if net0:
        ip = _extract_ip_from_net0(net0)
        if ip:
            return ip
    return None


def _get_container_disk(container: dict) -> int:
    """Return disk size in GB from live mount metadata only."""
    for mount in container.get("mounts", []):
        if mount.get("type") == "rootfs" and "size" in mount:
            # Parse "8G" to 8.
            return int(mount["size"].rstrip("GT"))
    return 0


def _get_container_tags(container: dict) -> list[str]:
    """Return tags from Proxmox config only."""
    raw = container.get("config", {}).get("tags")
    if not isinstance(raw, str) or not raw.strip():
        return []
    return [tag for tag in re.split(r"[;,]", raw) if tag]


def _int_config_value(config: dict, key: str) -> int:
    """Return an integer config value or 0 when absent."""
    raw = config.get(key)
    if raw in (None, ""):
        return 0
    return int(raw)


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
                "source": "portainer",
            })

    seen = set()
    deduped = []
    for svc in services:
        key = (svc["name"], svc["port"], svc["protocol"])
        if key not in seen:
            seen.add(key)
            deduped.append(svc)
    return deduped


def _build_socket_proxy_services(proxy_url: str, container: dict, guest_scoped: bool = False) -> list[dict]:
    """Query a docker-socket-proxy HTTP API and return services for a guest.

    Implementation:
    - call `GET /containers/json?all=1` to list containers
    - for each container summary, call `GET /containers/{id}/json` to obtain
      `NetworkSettings` and `Ports` details
    - treat a container as belonging to `container` when either:
      - one of the container's network `IPAddress` values equals the guest IP
      - OR one of the container `Names` contains the Proxmox guest name (fallback)
    - convert published port mappings into the same service dict shape used by
      other inspectors: `{name, port, protocol}`.
    """
    if not proxy_url:
        return []

    guest_ip = _get_container_ip(container)
    if guest_ip and "/" in guest_ip:
        guest_ip = guest_ip.split("/", 1)[0]

    base = proxy_url.rstrip("/")
    services = []
    seen = set()

    try:
        # TODO: when DOCKER_SOCKET_PROXY_URL_TEMPLATE is upgraded to https://,
        # pass an ssl context here that verifies against the step-ca or LE cert.
        # Currently HTTP only; context= omitted so urllib uses no TLS at all.
        list_req = urllib.request.Request(f"{base}/containers/json?all=1")
        with urllib.request.urlopen(list_req) as resp:
            summaries = json.loads(resp.read().decode())
    except Exception:
        return []

    if not isinstance(summaries, list):
        return []

    for summary in summaries:
        cid = summary.get("Id") or summary.get("ID") or summary.get("Id")
        if not cid:
            continue

        try:
            req = urllib.request.Request(f"{base}/containers/{cid}/json")
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
        except Exception:
            # skip containers we can't inspect
            continue

        # Determine canonical container name
        cname = (data.get("Name") or "").lstrip("/")
        if not cname:
            # try the Names list from summary or inspect
            names = data.get("Names") or summary.get("Names") or []
            if names:
                cname = names[0].lstrip("/")
            else:
                cname = cid

        # Determine whether this container maps to the Proxmox guest. When the
        # proxy endpoint is guest-scoped (resolved from a per-guest template),
        # treat all returned containers as belonging to the guest and skip
        # any name/IP matching. For single-endpoint proxies, fall back to the
        # Docker-inspect IP match and a conservative name substring fallback.
        matches = False
        if guest_scoped:
            matches = True
        else:
            if guest_ip:
                network_settings = data.get("NetworkSettings") or {}
                networks = network_settings.get("Networks") or {}
                if isinstance(networks, dict):
                    for net in networks.values():
                        if not isinstance(net, dict):
                            continue
                        c_ip = net.get("IPAddress")
                        if c_ip == guest_ip:
                            matches = True
                            break

            # Fallback: check whether the Proxmox guest name appears in container names
            if not matches:
                pve_name = container.get("name")
                if pve_name:
                    names = data.get("Names") or summary.get("Names") or []
                    for nn in names:
                        if pve_name and pve_name in nn:
                            matches = True
                            break

        if not matches:
            continue

        # Extract Ports mapping from inspect response
        network = data.get("NetworkSettings") or {}
        ports_map = network.get("Ports") or {}

        for port_key, mappings in (ports_map or {}).items():
            m = re.match(r"(?P<port>\d+)/(tcp|udp)$", port_key)
            if not m:
                continue
            proto = port_key.split("/", 1)[1]
            if not mappings:
                # Not published to the host
                continue
            for mapping in mappings:
                host_port_raw = mapping.get("HostPort")
                if not host_port_raw:
                    continue
                try:
                    host_port = int(host_port_raw)
                except Exception:
                    continue
                key = (cname, host_port, proto)
                if key in seen:
                    continue
                seen.add(key)
                svc_name = f"{cname}-{host_port}" if host_port != 9001 else cname
                services.append({
                    "name": svc_name,
                    "port": host_port,
                    "protocol": proto,
                    "source": "socket-proxy",
                })

    return services


class RuntimeInspector:
    """Seam for runtime service inspection transport.

    Priority order:
    1. Portainer API (token-authenticated)
    2. Per-guest docker-socket-proxy template (DOCKER_SOCKET_PROXY_URL_TEMPLATE)
    3. Single-endpoint socket proxy fallback (DOCKER_SOCKET_PROXY_URL, legacy)

    SSH-based guest inspection has been removed. All discovery goes through
    authenticated or network-scoped API endpoints only.
    """

    def __init__(self, portainer=None, socket_proxy_url=None, socket_proxy_url_template=None):
        self.portainer = portainer
        # allow explicit construction or env-driven configuration
        # single-endpoint fallback (legacy)
        self.socket_proxy_url = socket_proxy_url or _resolved_env_value("DOCKER_SOCKET_PROXY_URL")
        # preferred per-guest template: e.g. http://{guest_ip}:2375
        self.socket_proxy_url_template = socket_proxy_url_template or _resolved_env_value(
            "DOCKER_SOCKET_PROXY_URL_TEMPLATE"
        )

    def inspect(self, container: dict, portainer_ep: dict | None = None) -> list[dict]:
        """Return a list of observed services for `container`.

        If a Portainer client was provided and `portainer_ep` is a truthy
        endpoint mapping, Portainer will be used. Otherwise the configured
        runtime probe callable is invoked.
        """
        if self.portainer and portainer_ep:
            return _build_portainer_services(self.portainer, portainer_ep)

        # Next preference: docker socket proxy (read-only Docker API).
        # Preferred: per-guest URL template with `{guest_ip}` placeholder.
        # Note: this template is expected to be provided via environment by
        # the populate job (e.g. /etc/netbox-populate/env when provisioned) or
        # by CI via GitHub Actions secrets. It is intentionally optional and
        # should remain unset on real stacks until the disposable proof and
        # rollout gates have been satisfied.
        template = self.socket_proxy_url_template or _resolved_env_value(
            "DOCKER_SOCKET_PROXY_URL_TEMPLATE"
        )
        if template:
            guest_ip = _get_container_ip(container)
            if guest_ip and "/" in guest_ip:
                guest_ip = guest_ip.split("/", 1)[0]
            if guest_ip:
                try:
                    proxy_url = template.format(guest_ip=guest_ip)
                except Exception:
                    proxy_url = None
                if proxy_url:
                    try:
                        services = _build_socket_proxy_services(proxy_url, container, guest_scoped=True)
                        if services:
                            return services
                    except Exception as exc:
                        print(
                            f"  warn: socket-proxy inspection failed for {container.get('name', 'unknown')} via template {template}: {exc}"
                        )

        # Fallback: single configured proxy endpoint (legacy)
        proxy_url = self.socket_proxy_url or _resolved_env_value("DOCKER_SOCKET_PROXY_URL")
        if proxy_url:
            try:
                services = _build_socket_proxy_services(proxy_url, container, guest_scoped=False)
                if services:
                    return services
            except Exception as exc:
                print(f"  warn: socket-proxy inspection failed for {container.get('name', 'unknown')}: {exc}")

        return []


def _resolve_portainer_server_ip(portainer_url: str) -> str:
    """Resolve the IP of the Portainer server from its URL."""
    try:
        hostname = urllib.parse.urlparse(portainer_url).hostname
        return socket.gethostbyname(hostname) if hostname else ""
    except Exception:
        return ""


def build_vm_list(proxmox_data=None, stack_yamls=None, portainer=None, runtime_inspector=None, portainer_url=None):
    """Merge Proxmox inventory with runtime-discovered service data.

    Proxmox is the authoritative source for container/VM existence and config.
    Services come from runtime inspection through Portainer or direct guest checks.

    Returns list of VM dicts with: name, ip, status, vcpus, memory, disk,
    description, tags, services, mounts.
    """
    if proxmox_data is None:
        proxmox_data = {"containers": [], "storage": []}

    # Normalize the runtime inspection seam. If the caller passed a simple
    # callable (legacy tests/code), keep it as-is. Otherwise instantiate the
    # explicit `RuntimeInspector` which encapsulates transport-specific
    # behavior (Portainer vs guest SSH probe).
    runtime_inspector = runtime_inspector or RuntimeInspector(portainer=portainer)

    # Index Portainer endpoints by name for service discovery
    portainer_endpoints_by_name = {}
    portainer_endpoints_by_ip = {}
    if portainer:
        # Resolve the Portainer server's own IP once so we can map the
        # "local" (unix-socket) endpoint to the host container by IP.
        portainer_server_ip = _resolve_portainer_server_ip(portainer_url) if portainer_url else ""
        for ep in portainer.get_endpoints():
            ep_url = ep.get("URL", "")
            raw_ip = ep_url.replace("tcp://", "").split(":")[0]
            # Unix-socket endpoints yield "unix" or empty — not a routable IP.
            # Map them to the Portainer server's resolved IP instead so they
            # match the host LXC container (e.g. management-stack).
            if not raw_ip or raw_ip.startswith("unix") or raw_ip.startswith("/"):
                ip = portainer_server_ip
            else:
                ip = raw_ip
            ep_entry = {
                "id": ep["Id"],
                "ip": ip,
                "status": "active" if ep["Status"] == 1 else "offline",
            }
            portainer_endpoints_by_name[ep["Name"]] = ep_entry
            if ip:
                portainer_endpoints_by_ip[ip] = ep_entry

    vms = []

    # Process all containers/VMs from Proxmox (authoritative source)
    for container in proxmox_data.get("containers", []):
        pve_name = container["name"]
        container_ip = _get_container_ip(container)
        container_ip_addr = container_ip.split("/")[0] if container_ip else None
        portainer_ep = (
            portainer_endpoints_by_name.get(pve_name)
            or (portainer_endpoints_by_ip.get(container_ip_addr) if container_ip_addr else None)
            or {}
        )

        config = container.get("config", {})
        ip = _get_container_ip(container)
        if not ip:
            # Skip containers without IPs
            continue

        vcpus = _int_config_value(config, "cores")
        memory = _int_config_value(config, "memory")
        disk = _get_container_disk(container)

        vm = {
            "name": pve_name,
            "ip": ip,
            "status": container.get("status", "unknown"),
            "vcpus": vcpus,
            "memory": memory,
            "disk": disk,
            "description": config.get("description", f"Proxmox {container['type'].upper()} VMID {container['vmid']}"),
            "tags": _get_container_tags(container),
            "services": [],
            "mounts": container.get("mounts", []),
            "vmid": container["vmid"],
            "vm_type": container["type"],
            "node": container["node"],
        }

        # Use the runtime inspection seam to obtain observed services. Two
        # cases are supported for backwards compatibility:
        #  - a modern inspector object exposing `inspect(container, portainer_ep=None)`
        #  - a legacy callable that accepts a single `container` argument
        try:
            if hasattr(runtime_inspector, "inspect") and callable(getattr(runtime_inspector, "inspect")):
                # Modern inspector: let it decide between Portainer and guest probe
                vm["services"] = runtime_inspector.inspect(container, portainer_ep=portainer_ep)
            else:
                # Legacy callable: preserve previous behavior where Portainer is
                # preferred when available, otherwise call the provided callable.
                if portainer and portainer_ep:
                    vm["services"] = _build_portainer_services(portainer, portainer_ep)
                else:
                    vm["services"] = runtime_inspector(container)
        except Exception as exc:
            print(f"  warn: runtime service inspection skipped for {pve_name}: {exc}")
            vm["services"] = []

        vms.append(vm)

    return vms


def build_topology(proxmox_data=None, stack_yamls=None, portainer=None, portainer_ip=None, portainer_url=None):
    """Build the full topology dict from all available data sources.

    Priority: Proxmox (authoritative) → runtime service inspection.
    """
    if proxmox_data is None:
        proxmox_data = discover_from_proxmox()

    return build_vm_list(proxmox_data, stack_yamls, portainer=portainer, portainer_url=portainer_url)


_EMPTY_NETWORK_TOPOLOGY: dict = {
    "router": None,
    "interfaces": [],
    "vlans": [],
    "ip_addresses": [],
}


def build_network_topology():
    """Build router and network topology from Mikrotik.

    Returns a dict with router metadata, interfaces, VLANs, and IP addresses.
    If Mikrotik credentials are not configured, or auth fails, returns an empty topology.
    """
    if not (
        (os.environ.get("MIKROTIK_READONLY_USER") and os.environ.get("MIKROTIK_READONLY_PASSWORD"))
        or (os.environ.get("MIKROTIK_USER") and os.environ.get("MIKROTIK_PASSWORD"))
    ):
        return dict(_EMPTY_NETWORK_TOPOLOGY)

    try:
        data = discover_from_mikrotik()
    except RuntimeError as exc:
        print(f"warn: MikroTik discovery failed; skipping network topology: {exc}")
        return dict(_EMPTY_NETWORK_TOPOLOGY)

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
    proxmox_data = discover_from_proxmox()

    # Attempt to instantiate a Portainer client when environment values
    # indicate a Portainer endpoint and admin password are available.
    # This enables Portainer-backed service discovery for VMs that have
    # Portainer endpoints configured.
    portainer_client = None
    try:
        has_admin_pw = bool(os.environ.get("PORTAINER_ADMIN_PASSWORD"))
        has_url = bool(_resolved_env_value("PORTAINER_URL") or _resolved_env_value("PORTAINER_SERVER_IP") or _resolved_env_value("LAB_IP_PORTAINER"))
        if has_admin_pw and has_url:
            try:
                portainer_client = PortainerClient()
            except Exception:
                # If Portainer client construction fails, quietly disable it
                portainer_client = None
    except Exception:
        portainer_client = None

    return {
        "vms": build_topology(
            proxmox_data=proxmox_data,
            stack_yamls=None,
            portainer=portainer_client,
        ),
        "network": build_network_topology(),
        "proxmox": build_proxmox_context(proxmox_data),
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
