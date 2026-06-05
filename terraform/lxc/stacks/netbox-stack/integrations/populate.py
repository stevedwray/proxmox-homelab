#!/usr/bin/env python3
"""Populate NetBox with Proxmox homelab topology.

Discovers VMs and runtime services from live infrastructure inspection, then
idempotently creates all objects in NetBox in dependency order.

Usage:
    ./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py
    ./with-secrets python3 terraform/lxc/stacks/netbox-stack/integrations/populate.py --clean

Required environment:
    - NETBOX_URL
    - one of: NETBOX_NETWORK_INTENT_PATH, NETBOX_NETWORK_ENV, PVE_ENV,
      TF_VAR_proxmox_node
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
import ipaddress

import yaml

from client import NetBoxClient
from discover import build_full_topology, load_stack_yamls

# ---------------------------------------------------------------------------
# Static definitions (things not discovered automatically)
# ---------------------------------------------------------------------------

SITE = {"name": "Homelab", "slug": "homelab", "status": "active",
        "description": "Proxmox-based home laboratory"}

MANUFACTURERS = [{"name": "Generic", "slug": "generic"}]

PLATFORMS = [
    {"name": "Proxmox VE", "slug": "proxmox-ve"},
    {"name": "Debian 13", "slug": "debian-13"},
]

CLUSTER_TYPES = [{"name": "Proxmox VE", "slug": "proxmox-ve"}]

DEVICE_ROLES = [
    {"name": "Hypervisor", "slug": "hypervisor", "color": "4caf50"},
    {"name": "Network", "slug": "network", "color": "2196f3"},
]

DEVICE_TYPES = [
    {"manufacturer": "Generic", "model": "Proxmox Server", "slug": "proxmox-server"},
    {"manufacturer": "Generic", "model": "Mikrotik Router", "slug": "mikrotik-router"},
]

DEVICES = [
    {
        "name": "pve",
        "role": "Hypervisor",
        "device_type": "Proxmox Server",
        "platform": "Proxmox VE",
        "status": "active",
        "description": "Primary Proxmox VE hypervisor",
        "interfaces": [
            {"name": "vmbr0", "type": "bridge", "description": "Primary bridge"},
        ],
    },
]



CLUSTERS = [
    {"name": "pve-cluster", "type": "Proxmox VE",
     "description": "Single-node Proxmox cluster"},
]

NETWORK_INTENT_FILES = {
    "pve": "pve.yaml",
    "pve-test": "pve-test.yaml",
}

NETWORK_INTENT_ROOT = Path(__file__).resolve().parents[3] / "network"

_ENV_TOKEN_RE = re.compile(r"^\$\{([A-Za-z_]\w*)\}$")


# ---------------------------------------------------------------------------
# NetBox API path constants
# ---------------------------------------------------------------------------

NB_DCIM_SITES = "/dcim/sites/"
NB_DCIM_MANUFACTURERS = "/dcim/manufacturers/"
NB_DCIM_PLATFORMS = "/dcim/platforms/"
NB_DCIM_DEVICE_ROLES = "/dcim/device-roles/"
NB_DCIM_DEVICE_TYPES = "/dcim/device-types/"
NB_DCIM_DEVICES = "/dcim/devices/"
NB_DCIM_INTERFACES = "/dcim/interfaces/"
NB_VIRT_CLUSTER_TYPES = "/virtualization/cluster-types/"
NB_VIRT_CLUSTERS = "/virtualization/clusters/"
NB_VIRT_VIRTUAL_MACHINES = "/virtualization/virtual-machines/"
NB_VIRT_INTERFACES = "/virtualization/interfaces/"
NB_IPAM_IP_ADDRESSES = "/ipam/ip-addresses/"
NB_IPAM_SERVICES = "/ipam/services/"
NB_EXTRAS_TAGS = "/extras/tags/"

MANAGED_TAG_NAME = "managed-by-proxmox-homelab"
MANAGED_TAG_SLUG = "managed-by-proxmox-homelab"
ENV_TAG_PREFIX = "netbox-env-"


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------

_INTERNAL_PREFIXES = (
    "192.168.",
    "10.",
    "172.16.",
    "172.17.",
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
)


def _is_internal_ip(address: str) -> bool:
    """Return True if address is an RFC 1918 private IP."""
    host = address.split("/")[0]
    return host.startswith(_INTERNAL_PREFIXES)


def _tag_ref(name: str) -> dict:
    """Return a NetBox tag reference payload."""
    return {"name": name, "slug": name}


def _slugify_tag_suffix(value: str) -> str:
    """Return a lowercase, NetBox-safe suffix for generated tag names."""
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "default"


def _environment_tag_name(environment: str) -> str:
    """Return the environment-scoped NetBox tag name."""
    return f"{ENV_TAG_PREFIX}{_slugify_tag_suffix(environment)}"


def _managed_tag_refs(extra_tags=None, environment: str | None = None) -> list[dict]:
    """Return ownership tag plus any extra managed tags."""
    names = [MANAGED_TAG_NAME]
    if environment:
        names.append(_environment_tag_name(environment))
    names.extend(extra_tags or [])

    refs = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        refs.append(_tag_ref(name))
    return refs


def _ensure_tags(nb, names):
    """Ensure tags exist in NetBox for the provided names."""
    for name in names:
        if not isinstance(name, str):
            continue
        nb.ensure(NB_EXTRAS_TAGS, {"name": name}, {"slug": name})


def _detect_population_environment(environment: str | None = None) -> str | None:
    """Detect the target population environment from explicit arg or environment.

    This is a lightweight helper used by build_population_intent. It prefers an
    explicit argument, then common environment variables if present.
    """
    if environment:
        return environment
    for var in ("NETBOX_NETWORK_ENV", "PVE_ENV", "TF_VAR_proxmox_node"):
        v = os.environ.get(var)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _select_network_intent_path(
    environment: str | None = None,
    explicit_path: str | None = None,
) -> Path:
    """Select network intent path from explicit path, env override, or environment map."""
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()

    path_override = os.environ.get("NETBOX_NETWORK_INTENT_PATH")
    if path_override:
        return Path(path_override).expanduser().resolve()

    selected_environment = _detect_population_environment(environment)
    if not selected_environment:
        raise ValueError(
            "NetBox population environment is ambiguous. Set NETBOX_NETWORK_ENV, "
            "PVE_ENV, TF_VAR_proxmox_node, or NETBOX_NETWORK_INTENT_PATH."
        )
    mapped_file = NETWORK_INTENT_FILES.get(selected_environment)
    if not mapped_file:
        supported = ", ".join(sorted(NETWORK_INTENT_FILES))
        raise ValueError(
            "Unsupported NETBOX network environment "
            f"'{selected_environment}'. Supported values: {supported}"
        )

    return (NETWORK_INTENT_ROOT / mapped_file).resolve()


def _load_network_intent(path: Path) -> dict:
    """Load and validate the network intent YAML payload."""
    with open(path, encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Network intent file must decode to a mapping: {path}")
    return payload


def _resolve_env_token(raw_value):
    """Resolve ${token} style placeholders from environment when possible."""
    if not isinstance(raw_value, str):
        return raw_value

    match = _ENV_TOKEN_RE.match(raw_value.strip())
    if not match:
        return raw_value

    token = match.group(1)
    candidates = [
        token,
        token.lower(),
        token.upper(),
        f"TF_VAR_{token}",
        f"TF_VAR_{token.lower()}",
        f"TF_VAR_{token.upper()}",
    ]

    for name in dict.fromkeys(candidates):
        value = os.environ.get(name)
        if value:
            return value
    return raw_value


def _extract_routed_segment_prefixes(network_intent: dict) -> list[dict]:
    """Extract one prefix per routed segment from network intent."""
    attachments = network_intent.get("attachments", {})
    zones = network_intent.get("zones", {})
    if not isinstance(attachments, dict) or not isinstance(zones, dict):
        return []

    prefixes = []
    for segment_name, zone_def in zones.items():
        if not isinstance(zone_def, dict):
            continue

        attachment = {}
        attachment_name = zone_def.get("attachment")
        if isinstance(attachment_name, str):
            candidate = attachments.get(attachment_name, {})
            if isinstance(candidate, dict):
                attachment = candidate

        if attachment.get("type") == "bridge":
            continue

        attachment_sdn = attachment.get("sdn", {})
        if not isinstance(attachment_sdn, dict):
            attachment_sdn = {}

        # Support direct zone CIDR keys plus the repo's attachment.sdn.subnet shape.
        prefix = (
            zone_def.get("prefix")
            or zone_def.get("cidr")
            or zone_def.get("network")
            or attachment_sdn.get("subnet")
        )
        prefix = _resolve_env_token(prefix)
        if not isinstance(prefix, str) or not prefix.strip():
            continue
        prefixes.append({
            "prefix": prefix.strip(),
            "description": zone_def.get("description", segment_name),
        })

    return prefixes


def _derive_proxmox_host_address() -> str | None:
    """Derive the Proxmox host address from environment, never from stale literals."""
    raw = (
        os.environ.get("NETBOX_PROXMOX_HOST_ADDRESS")
        or os.environ.get("LAB_IP_PROXMOX_HOST")
        or os.environ.get("PROXMOX_HOST_IP")
    )
    if not raw:
        return None

    raw = raw.strip()
    if not raw:
        return None
    if "/" in raw:
        return raw

    prefix_len = os.environ.get("NETBOX_PROXMOX_HOST_PREFIXLEN", "24").strip() or "24"
    if not prefix_len.isdigit():
        raise ValueError(
            "NETBOX_PROXMOX_HOST_PREFIXLEN must be a numeric prefix length"
        )

    return f"{raw}/{prefix_len}"


def _extract_proxmox_target_node(network_intent: dict, environment: str | None) -> str:
    """Return the Proxmox target node name for the selected inventory source."""
    proxmox = network_intent.get("proxmox", {})
    if isinstance(proxmox, dict):
        raw = proxmox.get("target_node")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return environment or DEVICES[0]["name"]


def _cluster_name_for_target_node(target_node: str) -> str:
    """Return the NetBox cluster name for one Proxmox source node."""
    return f"{target_node}-cluster"


def _virtual_machine_name(vm_def: dict, inventory: dict) -> str:
    """Return the shared-inventory-safe NetBox VM name for a discovered VM."""
    source_node = vm_def.get("node")
    if not source_node or source_node == "external":
        source_node = inventory["environment"]
    return f"{vm_def['name']}@{source_node}"


def _legacy_virtual_machine_lookups(vm_def: dict, inventory: dict) -> list[dict]:
    """Return legacy VM lookups used to migrate pre-shared-inventory records."""
    if not inventory.get("legacy_name_migration_enabled"):
        return []
    current_name = _virtual_machine_name(vm_def, inventory)
    legacy = []
    if current_name != vm_def["name"]:
        legacy.append({"name": vm_def["name"]})
    return legacy


def _build_inventory_context(population_intent: dict) -> dict:
    """Build environment-aware identity metadata for shared NetBox inventory."""
    environment = population_intent["environment"]
    target_node = population_intent["proxmox"]["target_node"]
    return {
        "environment": environment,
        "environment_tag": _environment_tag_name(environment),
        "target_node": target_node,
        "cluster_name": _cluster_name_for_target_node(target_node),
        "hypervisor_device_name": target_node,
        "legacy_name_migration_enabled": target_node == "pve-test",
    }


def _apply_discovered_proxmox_host_context(population_intent: dict, topology: dict) -> dict:
    """Prefer discovered Proxmox host address data over env-seeded fallbacks."""
    proxmox = topology.get("proxmox", {}) if isinstance(topology, dict) else {}
    if not isinstance(proxmox, dict):
        return population_intent

    host_address = proxmox.get("host_address")
    if host_address:
        population_intent["proxmox_host"]["address"] = host_address

    host_interface = proxmox.get("host_interface")
    if host_interface:
        population_intent["proxmox_host"]["interface_name"] = host_interface

    return population_intent


def build_population_intent(
    environment: str | None = None,
    network_intent_path: str | None = None,
) -> dict:
    """Build parsed network/prefix seed data for population."""
    selected_environment = _detect_population_environment(environment)
    resolved_path = _select_network_intent_path(
        environment=selected_environment,
        explicit_path=network_intent_path,
    )
    if not selected_environment:
        selected_environment = "custom"
    intent = _load_network_intent(resolved_path)

    target_node = _extract_proxmox_target_node(intent, selected_environment)
    device_name = os.environ.get("NETBOX_PROXMOX_DEVICE_NAME", target_node).strip()
    interface_name = DEVICES[0]["interfaces"][0]["name"]

    return {
        "environment": selected_environment,
        "network_intent_path": str(resolved_path),
        "proxmox": {
            "target_node": target_node,
            "cluster_name": _cluster_name_for_target_node(target_node),
        },
        "prefixes": _extract_routed_segment_prefixes(intent),
        "proxmox_host": {
            "device_name": device_name,
            "interface_name": interface_name,
            "address": _derive_proxmox_host_address(),
        },
    }


SHARED_STALE_TRACKED_PATHS = [
    NB_DCIM_SITES,
    NB_DCIM_MANUFACTURERS,
    NB_DCIM_PLATFORMS,
    NB_DCIM_DEVICE_ROLES,
    NB_DCIM_DEVICE_TYPES,
    NB_VIRT_CLUSTER_TYPES,
    "/ipam/vlan-groups/",
    "/ipam/vlans/",
    "/ipam/prefixes/",
]


ENV_STALE_TRACKED_PATHS = [
    NB_DCIM_DEVICES,
    NB_DCIM_INTERFACES,
    NB_VIRT_CLUSTERS,
    NB_VIRT_VIRTUAL_MACHINES,
    NB_VIRT_INTERFACES,
    NB_IPAM_IP_ADDRESSES,
    NB_IPAM_SERVICES,
]


SHARED_CLEAN_FILTERS = {
    NB_DCIM_SITES: {"tag": MANAGED_TAG_SLUG},
    NB_DCIM_MANUFACTURERS: {"tag": MANAGED_TAG_SLUG},
    NB_DCIM_PLATFORMS: {"tag": MANAGED_TAG_SLUG},
    NB_DCIM_DEVICE_ROLES: {"tag": MANAGED_TAG_SLUG},
    NB_DCIM_DEVICE_TYPES: {"tag": MANAGED_TAG_SLUG},
    NB_VIRT_CLUSTER_TYPES: {"tag": MANAGED_TAG_SLUG},
    "/ipam/vlan-groups/": {"tag": MANAGED_TAG_SLUG},
    "/ipam/vlans/": {"tag": MANAGED_TAG_SLUG},
    "/ipam/prefixes/": {"tag": MANAGED_TAG_SLUG},
    NB_EXTRAS_TAGS: {"name": MANAGED_TAG_NAME},
}


def _managed_tag_exists_live(nb):
    """Return True when the ownership tag exists in live NetBox state."""
    results = nb.live_get(NB_EXTRAS_TAGS, slug=MANAGED_TAG_SLUG)
    return results.get("count", 0) > 0


def _environment_tag_exists_live(nb, inventory: dict) -> bool:
    """Return True when the current environment tag exists in live NetBox state."""
    results = nb.live_get(NB_EXTRAS_TAGS, slug=inventory["environment_tag"])
    return results.get("count", 0) > 0


def _environment_tag_ref(inventory: dict) -> dict:
    """Return the current environment tag payload reference."""
    return _tag_ref(inventory["environment_tag"])


def _environment_filters(path: str, inventory: dict) -> dict:
    """Return the environment-scoped tag filter for one API path."""
    if path == NB_EXTRAS_TAGS:
        return {"name": inventory["environment_tag"]}
    return {"tag": inventory["environment_tag"]}


def _primary_ip_id(obj: dict, field: str = "primary_ip4") -> int | None:
    """Return the referenced primary IP object id from a NetBox object dict."""
    value = obj.get(field)
    if isinstance(value, dict):
        return value.get("id")
    return value


def _tag_slugs(obj: dict) -> set[str]:
    """Return a set of tag slugs from one NetBox object dict."""
    tags = obj.get("tags", [])
    slugs = set()
    for tag in tags:
        if isinstance(tag, dict):
            slug = tag.get("slug") or tag.get("name")
            if slug:
                slugs.add(slug)
        elif isinstance(tag, str):
            slugs.add(tag)
    return slugs


def _service_protocol_value(service: dict) -> str | None:
    """Return the normalized protocol value from one NetBox service object."""
    protocol = service.get("protocol")
    if isinstance(protocol, dict):
        protocol = protocol.get("value") or protocol.get("label")
    if not isinstance(protocol, str):
        return None
    return protocol.lower()


def _service_first_port(service: dict) -> int | None:
    """Return the first port from one NetBox service object."""
    ports = service.get("ports")
    if isinstance(ports, list) and ports:
        first = ports[0]
        if isinstance(first, int) and not isinstance(first, bool):
            return first
    return None


def _service_last_seen_description(vm_name: str, observed_at: str) -> str:
    """Return a canonical service description with last-seen runtime metadata."""
    return f"{vm_name} | last-seen={observed_at}"


def _vm_description(vm_def: dict) -> str:
    """Return a NetBox-safe VM description capped at 200 characters."""
    description = (
        f"{vm_def.get('description', '')} "
        f"[Status: {vm_def['status']}] "
        f"[Source name: {vm_def['name']}]"
    ).strip()
    return description[:200]


def _legacy_cluster_lookups(inventory: dict) -> list[dict]:
    """Return legacy cluster lookups used during the shared-inventory migration."""
    if not inventory.get("legacy_name_migration_enabled"):
        return []
    legacy = []
    if inventory["cluster_name"] != CLUSTERS[0]["name"]:
        legacy.append({"name": CLUSTERS[0]["name"]})
    return legacy


def _legacy_hypervisor_lookups(inventory: dict) -> list[dict]:
    """Return legacy hypervisor device lookups used during migration."""
    if not inventory.get("legacy_name_migration_enabled"):
        return []
    legacy = []
    if inventory["hypervisor_device_name"] != DEVICES[0]["name"]:
        legacy.append({"name": DEVICES[0]["name"]})
    return legacy


# ---------------------------------------------------------------------------
# Population functions
# ---------------------------------------------------------------------------


def populate_foundation(nb):
    """Create site, manufacturers, platforms, cluster types, device roles, device types."""
    print("\n=== Foundation ===")

    _ensure_tags(nb, [MANAGED_TAG_NAME])
    managed_tags = _managed_tag_refs()

    site = nb.ensure(NB_DCIM_SITES, {"name": SITE["name"]}, {
        "slug": SITE["slug"],
        "status": SITE["status"],
        "description": SITE["description"],
        "tags": managed_tags,
    })

    for m in MANUFACTURERS:
        nb.ensure(NB_DCIM_MANUFACTURERS, {"name": m["name"]}, {
            "slug": m["slug"],
            "tags": managed_tags,
        })

    for p in PLATFORMS:
        nb.ensure(NB_DCIM_PLATFORMS, {"name": p["name"]}, {
            "slug": p["slug"],
            "tags": managed_tags,
        })

    for ct in CLUSTER_TYPES:
        nb.ensure(NB_VIRT_CLUSTER_TYPES, {"name": ct["name"]}, {
            "slug": ct["slug"],
            "tags": managed_tags,
        })

    for dr in DEVICE_ROLES:
        nb.ensure(NB_DCIM_DEVICE_ROLES, {"name": dr["name"]}, {
            "slug": dr["slug"],
            "color": dr["color"],
            "tags": managed_tags,
        })

    for dt in DEVICE_TYPES:
        mfg = nb.get(NB_DCIM_MANUFACTURERS, name=dt["manufacturer"])["results"][0]
        nb.ensure(NB_DCIM_DEVICE_TYPES, {"model": dt["model"]}, {
            "slug": dt["slug"],
            "manufacturer": mfg["id"],
            "tags": managed_tags,
        })

    return site


def populate_physical(nb, site, inventory):
    """Create physical devices (PVE host), their interfaces, and the cluster."""
    print("\n=== Physical Infrastructure ===")
    managed_tags = _managed_tag_refs(environment=inventory["environment"])
    _ensure_tags(nb, [MANAGED_TAG_NAME, inventory["environment_tag"]])

    dev_def = {**DEVICES[0], "name": inventory["hypervisor_device_name"]}
    role = nb.get(NB_DCIM_DEVICE_ROLES, name=dev_def["role"])["results"][0]
    dtype = nb.get(NB_DCIM_DEVICE_TYPES, model=dev_def["device_type"])["results"][0]
    platform = nb.get(NB_DCIM_PLATFORMS, name=dev_def["platform"])["results"][0]

    device = nb.ensure(
        NB_DCIM_DEVICES,
        {"name": dev_def["name"]},
        {
            "role": role["id"], "device_type": dtype["id"], "platform": platform["id"],
            "site": site["id"], "status": dev_def["status"],
            "description": dev_def["description"],
            "tags": managed_tags,
        },
        legacy_lookups=_legacy_hypervisor_lookups(inventory),
    )

    for iface_def in dev_def.get("interfaces", []):
        nb.ensure(NB_DCIM_INTERFACES, {
            "device_id": device["id"], "name": iface_def["name"],
        }, {
            "device": device["id"], "name": iface_def["name"],
            "type": iface_def["type"],
            "description": iface_def.get("description", ""),
            "tags": managed_tags,
        })

    cl_def = {**CLUSTERS[0], "name": inventory["cluster_name"]}
    ctype = nb.get(NB_VIRT_CLUSTER_TYPES, name=cl_def["type"])["results"][0]
    nb.ensure(
        NB_VIRT_CLUSTERS,
        {"name": cl_def["name"]},
        {
            "type": ctype["id"],
            "site": site["id"],
            "description": cl_def["description"],
            "tags": managed_tags,
        },
        legacy_lookups=_legacy_cluster_lookups(inventory),
    )


def populate_network(nb, site, network):
    """Create router device, interfaces, VLANs, and router IPs from Mikrotik discovery."""
    print("\n=== Network Infrastructure ===")

    router = network.get("router")
    if not router:
        print("  skip: Mikrotik credentials not configured; no router data discovered")
        return

    role = nb.get(NB_DCIM_DEVICE_ROLES, name="Network")["results"][0]
    dtype = nb.get(NB_DCIM_DEVICE_TYPES, model="Mikrotik Router")["results"][0]
    managed_tags = _managed_tag_refs()

    router_name = router.get("identity", "mikrotik-router")
    router_device = nb.ensure(NB_DCIM_DEVICES, {"name": router_name}, {
        "role": role["id"],
        "device_type": dtype["id"],
        "site": site["id"],
        "status": "active",
        "description": f"Discovered via Mikrotik API ({router.get('host', '')})",
        "tags": managed_tags,
    })

    # Create router interfaces.
    for iface_def in network.get("interfaces", []):
        name = iface_def.get("name")
        if not name:
            continue
        nb.ensure(NB_DCIM_INTERFACES, {
            "device_id": router_device["id"], "name": name,
        }, {
            "device": router_device["id"],
            "name": name,
            "type": "virtual",
            "enabled": not iface_def.get("disabled", False),
            "description": iface_def.get("type", "") or "",
            "tags": managed_tags,
        })

    # Create VLAN group for router and VLANs discovered on it.
    vlan_group = nb.ensure("/ipam/vlan-groups/", {"name": f"{router_name}-vlans"}, {
        "slug": f"{router_name.lower().replace(' ', '-')}-vlans",
        "scope_type": "dcim.site",
        "scope_id": site["id"],
        "tags": managed_tags,
    })

    # Aggregate discovered VLAN names by VID so we can choose a single
    # deterministic canonical name per VID and avoid patching the same
    # NetBox object to multiple discovered names in one run.
    vlan_by_vid: dict[int, set[str]] = {}
    for vlan in network.get("vlans", []):
        vid_raw = vlan.get("vlan-id")
        if vid_raw is None:
            continue
        try:
            vid = int(vid_raw)
        except (TypeError, ValueError):
            continue
        name = vlan.get("name") or f"vlan-{vid}"
        vlan_by_vid.setdefault(vid, set()).add(name)

    for vid, names in sorted(vlan_by_vid.items()):
        # Prefer the existing live name if present to avoid unnecessary churn;
        # otherwise pick a deterministic canonical name (sorted order).
        lookup = {"group_id": vlan_group["id"], "vid": vid}
        existing = nb.get("/ipam/vlans/", **lookup)
        if existing.get("count", 0) > 0:
            canonical_name = existing["results"][0].get("name") or sorted(names)[0]
        else:
            canonical_name = sorted(names)[0]

        nb.ensure("/ipam/vlans/", lookup, {
            "group": vlan_group["id"],
            "name": canonical_name,
            "vid": vid,
            "status": "active",
            "tags": managed_tags,
        })

    # Assign router interface IPs. Collect internal candidates first and then
    # select a single deterministic primary IP to patch the device at most
    # once. Preference: management/LAN 192.168.1.x, else numerically lowest.
    internal_candidates: list[dict] = []
    for ip_def in network.get("ip_addresses", []):
        address = ip_def.get("address")
        iface_name = ip_def.get("interface")
        if not address or not iface_name:
            continue
        iface_results = nb.get(NB_DCIM_INTERFACES, device_id=router_device["id"], name=iface_name)["results"]
        if not iface_results:
            continue
        iface = iface_results[0]
        ip_obj = nb.ensure(NB_IPAM_IP_ADDRESSES, {"address": address}, {
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": iface["id"],
            "status": "active",
            "description": f"{router_name}:{iface_name}",
            "tags": managed_tags,
        })
        if _is_internal_ip(address):
            internal_candidates.append({"ip": ip_obj, "address": address, "iface": iface})

    def _is_mgmt_addr(addr: str) -> bool:
        return addr.split("/")[0].startswith("192.168.1.")

    def _addr_key(addr: str) -> int:
        # numeric ordering of IPv4 address for stable selection
        return int(ipaddress.ip_address(addr.split("/")[0]))

    selected_ip_obj = None
    if internal_candidates:
        # Policy preference order:
        # 1) If the discovered router management/API host address (router['host'])
        #    appears among the discovered router IPs, prefer that exact IP.
        # 2) Otherwise prefer management/LAN 192.168.1.x addresses.
        # 3) Otherwise fall back to numerically lowest internal IP.
        router_host_ip = None
        host_field = router.get("host") if isinstance(router, dict) else None
        if isinstance(host_field, str) and host_field.strip():
            # router['host'] is formatted as "<host>[:<port>]" in discovery;
            # strip an optional port portion.
            router_host_ip = host_field.rsplit(":", 1)[0]

        preferred: list[dict] = []
        if router_host_ip:
            preferred = [c for c in internal_candidates if c["address"].split("/")[0] == router_host_ip]

        if not preferred:
            preferred = [c for c in internal_candidates if _is_mgmt_addr(c["address"])]

        if preferred:
            chosen = sorted(preferred, key=lambda c: _addr_key(c["address"]))[0]
        else:
            chosen = sorted(internal_candidates, key=lambda c: _addr_key(c["address"]))[0]

        selected_ip_obj = chosen["ip"]

    if selected_ip_obj and _primary_ip_id(router_device) != selected_ip_obj.get("id"):
        router_device = nb.patch_object(
            NB_DCIM_DEVICES,
            router_device,
            {"primary_ip4": selected_ip_obj.get("id")},
        )


def populate_virtual(nb, vms, inventory):
    """Create VMs, their interfaces, and tags from discovered data."""
    print("\n=== Virtual Infrastructure ===")

    cluster = nb.get(NB_VIRT_CLUSTERS, name=inventory["cluster_name"])["results"][0]
    platform = nb.get(NB_DCIM_PLATFORMS, name="Debian 13")["results"][0]

    for vm_def in vms:
        extra_tags = vm_def.get("tags", [])
        # Determine environment for this VM: prefer the VM's source node,
        # otherwise fall back to the population inventory environment.
        vm_env = vm_def.get("node")
        if not vm_env or vm_env == "external":
            vm_env = inventory["environment"]
        vm_name = _virtual_machine_name(vm_def, inventory)
        _ensure_tags(nb, [MANAGED_TAG_NAME, _environment_tag_name(vm_env), *extra_tags])
        tag_refs = _managed_tag_refs(extra_tags, environment=vm_env)

        # NetBox 4.5 virtual-machines only accept 'active' status; use description for state
        vm = nb.ensure(NB_VIRT_VIRTUAL_MACHINES, {"name": vm_name}, {
            "cluster": cluster["id"],
            "platform": platform["id"],
            "status": "active",  # NetBox only accepts 'active' for VMs
            "vcpus": vm_def.get("vcpus"),
            "memory": vm_def.get("memory"),
            "disk": vm_def.get("disk"),
            "description": _vm_description(vm_def),
            "tags": tag_refs,
        }, legacy_lookups=_legacy_virtual_machine_lookups(vm_def, inventory))

        nb.ensure(NB_VIRT_INTERFACES, {
            "virtual_machine_id": vm["id"], "name": "eth0",
        }, {
            "virtual_machine": vm["id"],
            "name": "eth0",
            "tags": _managed_tag_refs(environment=vm_env),
        })


def populate_ipam(nb, site, vms, population_intent, inventory):
    """Create prefix, assign IPs to interfaces, and register services."""
    print("\n=== IPAM ===")
    shared_managed_tags = _managed_tag_refs()
    env_managed_tags = _managed_tag_refs(environment=inventory["environment"])
    service_observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    for prefix in population_intent.get("prefixes", []):
        nb.ensure("/ipam/prefixes/", {"prefix": prefix["prefix"]}, {
            "site": site["id"],
            "description": prefix["description"],
            "status": "active",
            "tags": shared_managed_tags,
        })

    # Proxmox host IP from environment/repo-driven population intent.
    proxmox_host = population_intent.get("proxmox_host", {})
    host_address = proxmox_host.get("address")
    if host_address:
        device_results = nb.get(
            NB_DCIM_DEVICES,
            name=proxmox_host.get("device_name", DEVICES[0]["name"]),
        )["results"]
        if device_results:
            device = device_results[0]
            iface_name = proxmox_host.get("interface_name") or DEVICES[0]["interfaces"][0]["name"]
            iface_results = nb.get(
                NB_DCIM_INTERFACES,
                device_id=device["id"],
                name=iface_name,
            )["results"]
            if iface_results:
                iface = iface_results[0]
                existing_ip_results = nb.get(
                    NB_IPAM_IP_ADDRESSES,
                    address=host_address,
                )["results"]
                ip = next(
                    (
                        candidate
                        for candidate in existing_ip_results
                        if candidate.get("address") == host_address
                    ),
                    None,
                )
                if ip is None:
                    ip = nb.ensure(NB_IPAM_IP_ADDRESSES, {"address": host_address}, {
                        "assigned_object_type": "dcim.interface",
                        "assigned_object_id": iface["id"],
                        "status": "active",
                        "description": device["name"],
                        "tags": env_managed_tags,
                    })
                if (
                    _primary_ip_id(device) != ip["id"]
                    and ip.get("assigned_object_type") == "dcim.interface"
                    and ip.get("assigned_object_id") == iface["id"]
                ):
                    device = nb.patch_object(
                        NB_DCIM_DEVICES,
                        device,
                        {"primary_ip4": ip["id"]},
                    )

                desired_tags = {MANAGED_TAG_SLUG, inventory["environment_tag"]}
                assigned_ips = nb.get(
                    NB_IPAM_IP_ADDRESSES,
                    assigned_object_type="dcim.interface",
                    assigned_object_id=iface["id"],
                )["results"]
                for assigned_ip in assigned_ips:
                    if assigned_ip.get("address") == host_address:
                        continue
                    if not desired_tags.issubset(_tag_slugs(assigned_ip)):
                        continue
                    nb.delete_object(NB_IPAM_IP_ADDRESSES, assigned_ip)

    # VM IPs and services
    for vm_def in vms:
        if not vm_def.get("ip"):
            continue
        # Determine VM-specific environment for IP/service tagging.
        vm_env = vm_def.get("node")
        if not vm_env or vm_env == "external":
            vm_env = inventory["environment"]
        vm_env_managed_tags = _managed_tag_refs(environment=vm_env)
        vm = nb.get(
            NB_VIRT_VIRTUAL_MACHINES,
            name=_virtual_machine_name(vm_def, inventory),
        )["results"][0]
        iface = nb.get(NB_VIRT_INTERFACES,
                       virtual_machine_id=vm["id"], name="eth0")["results"][0]

        ip = nb.ensure(NB_IPAM_IP_ADDRESSES, {"address": vm_def["ip"]}, {
            "assigned_object_type": "virtualization.vminterface",
            "assigned_object_id": iface["id"],
            "status": "active",
            "description": vm_def["name"],
            "tags": vm_env_managed_tags,
        })
        if _primary_ip_id(vm) != ip["id"]:
            vm = nb.patch_object(
                NB_VIRT_VIRTUAL_MACHINES,
                vm,
                {"primary_ip4": ip["id"]},
            )

        for svc_def in vm_def.get("services", []):
            # Compose tags: keep existing managed/environment tags, and
            # optionally add a single runtime-source tag when discovery source
            # metadata is available on the observed service.
            service_tags = list(vm_env_managed_tags)
            svc_source = svc_def.get("source")
            if svc_source:
                source_tag_name = f"runtime-source-{svc_source}"
                _ensure_tags(nb, [source_tag_name])
                service_tags.append(_tag_ref(source_tag_name))

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
                "description": _service_last_seen_description(vm_def["name"], service_observed_at),
                "tags": service_tags,
            })

        desired_service_keys = {
            (svc["name"], svc["protocol"], svc["port"])
            for svc in vm_def.get("services", [])
        }
        # Only consider services that are managed and carry the VM's
        # environment tag (derived from the VM's source node). Previously
        # this used the inventory-level environment tag which caused
        # cross-node VMs to be reconciled against the wrong environment
        # during cleanup. Use the per-VM environment here.
        desired_tags = {MANAGED_TAG_SLUG, _environment_tag_name(vm_env)}
        existing_services = nb.get(
            NB_IPAM_SERVICES,
            parent_object_type="virtualization.virtualmachine",
            parent_object_id=vm["id"],
        )["results"]
        for existing_service in existing_services:
            existing_slugs = _tag_slugs(existing_service)
            # Only consider automation-managed services.
            if MANAGED_TAG_SLUG not in existing_slugs:
                continue

            # Detect any environment tag currently present on the service.
            existing_env_tags = [s for s in existing_slugs if s.startswith(ENV_TAG_PREFIX)]
            existing_env_tag = existing_env_tags[0] if existing_env_tags else None
            desired_env_tag = _environment_tag_name(vm_env)

            existing_key = (
                existing_service.get("name"),
                _service_protocol_value(existing_service),
                _service_first_port(existing_service),
            )

            if existing_env_tag == desired_env_tag:
                # Service already carries the VM's environment tag; apply
                # standard reconciliation (delete if not desired).
                if existing_key in desired_service_keys:
                    continue
                nb.delete_object(NB_IPAM_SERVICES, existing_service)
                continue

            # Service is managed but either missing an environment tag or
            # tagged for a different environment (cross-node). If it matches
            # a desired service, retag it to the current VM environment while
            # preserving any runtime-source tags. Otherwise delete it so it
            # will be recreated correctly.
            if existing_key in desired_service_keys:
                runtime_slugs = [s for s in existing_slugs if s.startswith("runtime-source-")]
                new_tags = _managed_tag_refs(extra_tags=runtime_slugs, environment=vm_env)
                nb.patch_object(NB_IPAM_SERVICES, existing_service, {"tags": new_tags})
            else:
                nb.delete_object(NB_IPAM_SERVICES, existing_service)


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

WIPE_ORDER = [
    NB_IPAM_SERVICES,
    NB_IPAM_IP_ADDRESSES,
    "/ipam/vlans/",
    "/ipam/vlan-groups/",
    "/ipam/prefixes/",
    NB_VIRT_INTERFACES,
    NB_VIRT_VIRTUAL_MACHINES,
    NB_VIRT_CLUSTERS,
    NB_VIRT_CLUSTER_TYPES,
    NB_DCIM_INTERFACES,
    NB_DCIM_DEVICES,
    NB_DCIM_DEVICE_TYPES,
    NB_DCIM_DEVICE_ROLES,
    NB_DCIM_PLATFORMS,
    NB_DCIM_MANUFACTURERS,
    NB_DCIM_SITES,
    NB_EXTRAS_TAGS,
]


def clean(nb, inventory):
    """Delete automation-owned objects for the current environment, in reverse dependency order."""
    print(f"NetBox: {nb.url}\n=== Cleaning ===")
    managed_tag_exists = _managed_tag_exists_live(nb)
    environment_tag_exists = _environment_tag_exists_live(nb, inventory)
    if not managed_tag_exists:
        print(f"  skip: ownership tag {MANAGED_TAG_NAME!r} does not exist live")
    if not environment_tag_exists:
        print(f"  skip: environment tag {inventory['environment_tag']!r} does not exist live")

    total = 0
    for path in WIPE_ORDER:
        if path in SHARED_CLEAN_FILTERS:
            filters = SHARED_CLEAN_FILTERS.get(path, {})
            if filters.get("tag") == MANAGED_TAG_SLUG and not managed_tag_exists:
                continue
        else:
            filters = _environment_filters(path, inventory)
            if not environment_tag_exists:
                continue
        if filters.get("tag") == MANAGED_TAG_SLUG and not managed_tag_exists:
            continue
        while True:
            results = nb.get(path, **filters)
            items = results.get("results", [])
            if not items:
                break
            for obj in items:
                name = (obj.get("name") or obj.get("display") or
                        obj.get("address") or obj.get("prefix") or str(obj["id"]))
                try:
                    nb.delete(f"{path}{obj['id']}/")
                    print(f"  deleted: {path} → {name} (id={obj['id']})")
                    total += 1
                except RuntimeError as e:
                    print(f"  skip: {path} → {name} (id={obj['id']}): {e}")
    print(f"\n=== Deleted {total} objects ===")


def report_stale_managed_objects(nb, inventory):
    """Report currently managed objects that no longer match desired lookups."""
    print(f"\n=== {'Planned' if nb.dry_run else 'Managed'} Drift Report ===")
    managed_tag_exists = _managed_tag_exists_live(nb)
    environment_tag_exists = _environment_tag_exists_live(nb, inventory)
    if not managed_tag_exists:
        print(f"  no stale managed objects detected (ownership tag {MANAGED_TAG_NAME!r} not present live)")
        return 0

    total = 0
    for path in SHARED_STALE_TRACKED_PATHS:
        stale = nb.find_stale(path, tag=MANAGED_TAG_SLUG)
        if not stale:
            continue
        total += len(stale)
        for obj in stale:
            print(
                f"  {'would mark stale' if nb.dry_run else 'stale'}: "
                f"{path} → {obj.get('name') or obj.get('display') or obj.get('address') or obj.get('prefix')} "
                f"(id={obj['id']})"
            )
    if environment_tag_exists:
        for path in ENV_STALE_TRACKED_PATHS:
            stale = nb.find_stale(path, tag=inventory["environment_tag"])
            if not stale:
                continue
            total += len(stale)
            for obj in stale:
                print(
                    f"  {'would mark stale' if nb.dry_run else 'stale'}: "
                    f"{path} → {obj.get('name') or obj.get('display') or obj.get('address') or obj.get('prefix')} "
                    f"(id={obj['id']})"
                )
    if total == 0:
        print("  no stale managed objects detected")
    return total


def reconcile_service_env_tags(nb):
    """Ensure managed services carry the same environment tag as their parent VM.

    This is a narrowly scoped reconciliation that patches service objects which
    are owned by the automation but carry an environment tag different from
    their VM parent. Runtime-source tags are preserved where present.
    """
    vms = nb.get(NB_VIRT_VIRTUAL_MACHINES, tag=MANAGED_TAG_SLUG).get("results", [])
    for vm in vms:
        vm_id = vm.get("id")
        if not vm_id:
            continue
        vm_slugs = _tag_slugs(vm)
        vm_env_tags = [s for s in vm_slugs if s.startswith(ENV_TAG_PREFIX)]
        if not vm_env_tags:
            continue
        vm_env_tag = vm_env_tags[0]
        # Derive environment token to pass to _managed_tag_refs
        env_value = vm_env_tag[len(ENV_TAG_PREFIX):]

        services = nb.get(
            NB_IPAM_SERVICES,
            parent_object_type="virtualization.virtualmachine",
            parent_object_id=vm_id,
        ).get("results", [])

        for svc in services:
            svc_slugs = _tag_slugs(svc)
            if MANAGED_TAG_SLUG not in svc_slugs:
                continue
            svc_env_tags = [s for s in svc_slugs if s.startswith(ENV_TAG_PREFIX)]
            if svc_env_tags and svc_env_tags[0] == vm_env_tag:
                continue

            # Preserve runtime-source tags while enforcing managed + VM env tag.
            runtime_slugs = [s for s in svc_slugs if s.startswith("runtime-source-")]
            new_tags = _managed_tag_refs(extra_tags=runtime_slugs, environment=env_value)
            nb.patch_object(NB_IPAM_SERVICES, svc, {"tags": new_tags})


# ---------------------------------------------------------------------------
# Augmentation helpers
# ---------------------------------------------------------------------------


def _augment_vms_with_declared_socket_proxy_targets(nb, vms, stacks):
    """Augment discovered `vms` with declared socket-proxy candidate targets.

    For each stack declaration, collect candidate probe addresses from
    `ip_address` and the optional `docker_socket_proxy_targets` key. Each
    candidate is resolved for `${TOKEN}` environment placeholders, skipped if
    it matches an already-discovered VM name or IP, and then attempted to be
    mapped to an existing NetBox VM/interface by IP. When a mapping is
    found, append a `vm_def` that references the existing VM so runtime
    inspection can attach services to the existing inventory object.

    This function will not create new NetBox VM objects.
    """
    existing_ips = {vm.get("ip") for vm in vms if vm.get("ip")}

    for name, stack in stacks.items():
        # Collect declared candidate probe addresses from common stack fields
        candidates = []
        ip_raw = stack.get("ip_address")
        if ip_raw:
            candidates.append(ip_raw)

        extra_targets = stack.get("docker_socket_proxy_targets")
        if isinstance(extra_targets, list):
            candidates.extend(extra_targets)
        elif isinstance(extra_targets, str):
            candidates.append(extra_targets)

        if not candidates:
            continue

        # Preserve original behavior: if the stack name is already present in
        # discovered VMs, skip the stack entirely (do not attempt augmentation).
        if any(vm.get("name") == name for vm in vms):
            continue

        for ip_candidate in candidates:
            ip = str(_resolve_env_token(ip_candidate)) if isinstance(ip_candidate, str) else None
            if not ip:
                continue

            # Normalize to address/prefix if template expects guest_ip without prefix
            ip_addr = ip.split("/", 1)[0]
            if ip in existing_ips or ip_addr in existing_ips:
                # Skip candidates whose address is already present in discovered VMs
                continue

            # Try to map the declared IP to an existing NetBox VM; if an
            # existing VM is found by IP, append a vm_def that points to that
            # VM so the runtime inspection will attach services to the
            # existing inventory object. Do NOT create new VMs here.
            try:
                ip_objs = nb.get(NB_IPAM_IP_ADDRESSES, address=ip)
                ip_results = ip_objs.get("results", []) if isinstance(ip_objs, dict) else []
            except Exception:
                ip_results = []

            for ip_obj in ip_results:
                if ip_obj.get("assigned_object_type") != "virtualization.vminterface":
                    continue
                assigned_id = ip_obj.get("assigned_object_id")
                if not assigned_id:
                    continue
                try:
                    iface_q = nb.get(NB_VIRT_INTERFACES, id=assigned_id)
                    iface_res = iface_q.get("results", []) if isinstance(iface_q, dict) else []
                except Exception:
                    iface_res = []
                if not iface_res:
                    continue
                iface = iface_res[0]
                vm_ref = iface.get("virtual_machine")
                vm_id = vm_ref.get("id") if isinstance(vm_ref, dict) else vm_ref
                if not vm_id:
                    continue
                try:
                    vm_q = nb.get(NB_VIRT_VIRTUAL_MACHINES, id=vm_id)
                    vm_res = vm_q.get("results", []) if isinstance(vm_q, dict) else []
                except Exception:
                    vm_res = []
                if not vm_res:
                    continue
                nb_vm = vm_res[0]
                nb_name = nb_vm.get("name") or name
                # Split NetBox name `foo@node` into base and node when present
                if isinstance(nb_name, str) and "@" in nb_name:
                    base, nodepart = nb_name.split("@", 1)
                else:
                    base = nb_name
                    nodepart = stack.get("proxmox", {}).get("target_node") or "external"

                vm_def = {
                    "name": base,
                    "ip": ip if "/" in ip else f"{ip}/24",
                    "status": "unknown",
                    "vcpus": stack.get("cores", 1) or 1,
                    "memory": stack.get("memory", 0) or 0,
                    "disk": stack.get("rootfs_size", 0) or 0,
                    "description": stack.get("description", "declared in stack.yaml"),
                    "tags": stack.get("tags", []),
                    "services": [],
                    "mounts": [],
                    "vmid": stack.get("vmid") or 0,
                    "vm_type": "declared",
                    "node": nodepart,
                }

                # Avoid duplicate appends for the same VM/ip
                if not any(v.get("ip") == vm_def["ip"] and v.get("name") == vm_def["name"] for v in vms):
                    vms.append(vm_def)
                # Candidate mapped; mark ip as seen and continue
                existing_ips.add(ip)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    import sys

    plan_mode = "--plan" in sys.argv
    nb = NetBoxClient(dry_run=plan_mode)
    population_intent = build_population_intent()
    inventory = _build_inventory_context(population_intent)

    if "--clean" in sys.argv and plan_mode:
        raise ValueError("--plan and --clean cannot be used together")

    if "--clean" in sys.argv:
        clean(nb, inventory)
        return

    print(f"NetBox: {nb.url}{' [plan mode]' if plan_mode else ''}")

    print(
        f"Using network intent: {population_intent['network_intent_path']} "
        f"(environment={population_intent['environment']})"
    )
    print(f"Routed segment prefixes in scope: {len(population_intent['prefixes'])}")

    # Discover full topology (VM + network).
    topology = build_full_topology()
    population_intent = _apply_discovered_proxmox_host_context(population_intent, topology)
    vms = topology["vms"]
    network = topology["network"]

    # Augment discovered VMs with declared stack YAMLs when a per-guest
    # socket-proxy template is provided but the Proxmox discovery did not
    # return the expected stack VM (common when the populate job targets the
    # local test Proxmox instance but the stack record lives under another
    # inventory node such as `pve`). This allows the standard populate path
    # to probe a declared VM IP via the `{guest_ip}` socket-proxy template
    # and ingest runtime services without relying on an ad hoc injection.
    try:
        template = os.environ.get("DOCKER_SOCKET_PROXY_URL_TEMPLATE") or os.environ.get("DOCKER_SOCKET_PROXY_URL")
        if template:
            stacks = load_stack_yamls()
            _augment_vms_with_declared_socket_proxy_targets(nb, vms, stacks)
    except Exception:
        # Non-fatal augmentation; discovery should continue even if stack
        # YAML parsing or env token resolution fails.
        pass
    print(f"Discovered {len(vms)} VMs from Proxmox + Portainer")
    if network.get("router"):
        print(
            f"Discovered router {network['router'].get('identity', 'Mikrotik')} "
            f"with {len(network.get('interfaces', []))} interfaces and "
            f"{len(network.get('vlans', []))} VLANs"
        )

    site = populate_foundation(nb)
    populate_physical(nb, site, inventory)
    populate_network(nb, site, network)
    populate_virtual(nb, vms, inventory)
    populate_ipam(nb, site, vms, population_intent, inventory)
    # Service-level reconciliation: ensure managed services' env tags match their VM
    reconcile_service_env_tags(nb)
    stale_total = report_stale_managed_objects(nb, inventory)

    print("\n=== Done ===")
    vm_count = nb.get(NB_VIRT_VIRTUAL_MACHINES)["count"]
    ip_count = nb.get(NB_IPAM_IP_ADDRESSES)["count"]
    svc_count = nb.get(NB_IPAM_SERVICES)["count"]
    print(
        f"VMs: {vm_count}, IPs: {ip_count}, Services: {svc_count}, "
        f"Stale managed objects: {stale_total}"
    )


if __name__ == "__main__":
    main()
