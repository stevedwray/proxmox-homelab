#!/usr/bin/env python3
"""Populate NetBox with Proxmox homelab topology.

Reads homelab definitions and idempotently creates all objects in dependency
order: foundation → physical → virtual → IPAM.

Usage:
    source ../../.env  # (from repo root)
    export NETBOX_URL=http://192.168.1.30:8080
    python3 populate.py
"""

from client import NetBoxClient

# ---------------------------------------------------------------------------
# Homelab data
# ---------------------------------------------------------------------------

SITE = {
    "name": "Homelab",
    "slug": "homelab",
    "status": "active",
    "description": "Proxmox-based home laboratory",
}

MANUFACTURERS = [
    {"name": "Generic", "slug": "generic"},
]

PLATFORMS = [
    {"name": "Proxmox VE", "slug": "proxmox-ve"},
    {"name": "Debian 13", "slug": "debian-13"},
]

CLUSTER_TYPES = [
    {"name": "Proxmox VE", "slug": "proxmox-ve"},
]

DEVICE_ROLES = [
    {"name": "Hypervisor", "slug": "hypervisor", "color": "4caf50"},
    {"name": "Network", "slug": "network", "color": "2196f3"},
]

DEVICE_TYPES = [
    {
        "manufacturer": "Generic",
        "model": "Proxmox Server",
        "slug": "proxmox-server",
    },
]

# Proxmox host(s)
DEVICES = [
    {
        "name": "pve",
        "role": "Hypervisor",
        "device_type": "Proxmox Server",
        "platform": "Proxmox VE",
        "site": "Homelab",
        "status": "active",
        "description": "Primary Proxmox VE hypervisor",
        "interfaces": [
            {"name": "vmbr0", "type": "bridge", "description": "Primary bridge"},
        ],
        "ip": "192.168.1.2/24",
    },
]

CLUSTERS = [
    {
        "name": "pve-cluster",
        "type": "Proxmox VE",
        "site": "Homelab",
        "description": "Single-node Proxmox cluster",
    },
]

# Virtual machines (LXC containers)
VIRTUAL_MACHINES = [
    # --- Active (managed by terraform/lxc/) ---
    {
        "name": "netbox-stack",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 2,
        "memory": 4096,
        "disk": 8,
        "description": "NetBox IPAM/DCIM (VMID 119)",
        "ip": "192.168.1.30/24",
        "services": [
            {"name": "netbox-web", "port": 8080, "protocol": "tcp"},
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["infrastructure", "docker"],
    },
    # --- Legacy stacks (managed by standalone TF dirs) ---
    {
        "name": "portainer-server",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 2,
        "memory": 3072,
        "disk": 8,
        "description": "Central Portainer + NPM (VMID 101)",
        "ip": "192.168.1.4/24",
        "services": [
            {"name": "portainer", "port": 9443, "protocol": "tcp"},
            {"name": "npm-http", "port": 80, "protocol": "tcp"},
            {"name": "npm-https", "port": 443, "protocol": "tcp"},
        ],
        "tags": ["management", "docker"],
    },
    {
        "name": "torrent-stack",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 2,
        "memory": 4096,
        "disk": 8,
        "description": "Torrent/media automation (VMID auto)",
        "ip": "192.168.1.5/24",
        "services": [
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["media", "docker"],
    },
    {
        "name": "media-stack",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 4,
        "memory": 8192,
        "disk": 8,
        "description": "Media services — Arr apps (VMID 800)",
        "ip": "192.168.1.6/24",
        "services": [
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["media", "docker"],
    },
    {
        "name": "gaming-stack",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 4,
        "memory": 16384,
        "disk": 8,
        "description": "Gaming server — Minecraft",
        "ip": "192.168.1.7/24",
        "services": [
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["gaming", "docker"],
    },
    {
        "name": "cloud-stack",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 2,
        "memory": 4096,
        "disk": 8,
        "description": "Cloud services",
        "ip": "192.168.1.9/24",
        "services": [
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["cloud", "docker"],
    },
    {
        "name": "security-stack",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "offline",
        "vcpus": 2,
        "memory": 4096,
        "disk": 8,
        "description": "Security services",
        "ip": "192.168.1.11/24",
        "services": [
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["security", "docker"],
    },
    {
        "name": "analysis-stack",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "offline",
        "vcpus": 2,
        "memory": 4096,
        "disk": 8,
        "description": "Analysis services",
        "ip": "192.168.1.16/24",
        "services": [
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["analysis", "docker"],
    },
    {
        "name": "elastic-stack",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 4,
        "memory": 8192,
        "disk": 8,
        "description": "Elasticsearch / Kibana",
        "ip": "192.168.1.24/24",
        "services": [
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["monitoring", "docker"],
    },
    # --- Test containers ---
    {
        "name": "test-docker",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 2,
        "memory": 2048,
        "disk": 8,
        "description": "Test container — Nginx via Portainer (VMID 131)",
        "ip": "192.168.1.52/24",
        "services": [
            {"name": "portainer-agent", "port": 9001, "protocol": "tcp"},
        ],
        "tags": ["test", "docker"],
    },
    {
        "name": "test-lxc",
        "cluster": "pve-cluster",
        "platform": "Debian 13",
        "status": "active",
        "vcpus": 2,
        "memory": 2048,
        "disk": 8,
        "description": "Test container — bare Docker (VMID 130)",
        "ip": "192.168.1.51/24",
        "services": [],
        "tags": ["test", "docker"],
    },
]

PREFIX = {"prefix": "192.168.1.0/24", "description": "Homelab LAN"}


# ---------------------------------------------------------------------------
# Population functions
# ---------------------------------------------------------------------------


def populate_foundation(nb, site_data):
    """Create site, manufacturers, platforms, cluster types, device roles, device types."""
    print("\n=== Foundation ===")

    site = nb.ensure("/dcim/sites/", {"name": site_data["name"]}, {
        "slug": site_data["slug"],
        "status": site_data["status"],
        "description": site_data["description"],
    })

    for m in MANUFACTURERS:
        nb.ensure("/dcim/manufacturers/", {"name": m["name"]}, {"slug": m["slug"]})

    for p in PLATFORMS:
        nb.ensure("/dcim/platforms/", {"name": p["name"]}, {"slug": p["slug"]})

    for ct in CLUSTER_TYPES:
        nb.ensure("/virtualization/cluster-types/", {"name": ct["name"]}, {"slug": ct["slug"]})

    for dr in DEVICE_ROLES:
        nb.ensure("/dcim/device-roles/", {"name": dr["name"]}, {
            "slug": dr["slug"],
            "color": dr["color"],
        })

    # Device types need manufacturer ID
    for dt in DEVICE_TYPES:
        mfg = nb.get("/dcim/manufacturers/", name=dt["manufacturer"])["results"][0]
        nb.ensure("/dcim/device-types/", {"model": dt["model"]}, {
            "slug": dt["slug"],
            "manufacturer": mfg["id"],
        })

    return site


def populate_physical(nb, site):
    """Create physical devices (PVE host), their interfaces, and the cluster."""
    print("\n=== Physical Infrastructure ===")

    for dev_def in DEVICES:
        role = nb.get("/dcim/device-roles/", name=dev_def["role"])["results"][0]
        dtype = nb.get("/dcim/device-types/", model=dev_def["device_type"])["results"][0]
        platform = nb.get("/dcim/platforms/", name=dev_def["platform"])["results"][0]

        device = nb.ensure("/dcim/devices/", {"name": dev_def["name"]}, {
            "role": role["id"],
            "device_type": dtype["id"],
            "platform": platform["id"],
            "site": site["id"],
            "status": dev_def["status"],
            "description": dev_def["description"],
        })

        # Create interfaces
        for iface_def in dev_def.get("interfaces", []):
            nb.ensure("/dcim/interfaces/", {
                "device_id": device["id"],
                "name": iface_def["name"],
            }, {
                "device": device["id"],
                "name": iface_def["name"],
                "type": iface_def["type"],
                "description": iface_def.get("description", ""),
            })

    for cl_def in CLUSTERS:
        ctype = nb.get("/virtualization/cluster-types/", name=cl_def["type"])["results"][0]
        nb.ensure("/virtualization/clusters/", {"name": cl_def["name"]}, {
            "type": ctype["id"],
            "site": site["id"],
            "description": cl_def["description"],
        })


def populate_virtual(nb):
    """Create VMs (LXC containers), their interfaces, and tags."""
    print("\n=== Virtual Infrastructure ===")

    for vm_def in VIRTUAL_MACHINES:
        cluster = nb.get("/virtualization/clusters/", name=vm_def["cluster"])["results"][0]
        platform = nb.get("/dcim/platforms/", name=vm_def["platform"])["results"][0]

        # Ensure tags exist
        tag_ids = []
        for tag_name in vm_def.get("tags", []):
            tag = nb.ensure("/extras/tags/", {"name": tag_name}, {
                "slug": tag_name,
            })
            tag_ids.append({"name": tag_name, "slug": tag_name})

        vm = nb.ensure("/virtualization/virtual-machines/", {"name": vm_def["name"]}, {
            "cluster": cluster["id"],
            "platform": platform["id"],
            "status": vm_def["status"],
            "vcpus": vm_def.get("vcpus"),
            "memory": vm_def.get("memory"),
            "disk": vm_def.get("disk"),
            "description": vm_def["description"],
            "tags": tag_ids,
        })

        # Create eth0 interface
        nb.ensure("/virtualization/interfaces/", {
            "virtual_machine_id": vm["id"],
            "name": "eth0",
        }, {
            "virtual_machine": vm["id"],
            "name": "eth0",
            "type": "virtual",
        })


def populate_ipam(nb, site):
    """Create prefix, assign IPs to VM interfaces, and register services."""
    print("\n=== IPAM ===")

    nb.ensure("/ipam/prefixes/", {"prefix": PREFIX["prefix"]}, {
        "site": site["id"],
        "description": PREFIX["description"],
        "status": "active",
    })

    # Assign IP to PVE host interface
    for dev_def in DEVICES:
        if not dev_def.get("ip"):
            continue
        device = nb.get("/dcim/devices/", name=dev_def["name"])["results"][0]
        iface_name = dev_def["interfaces"][0]["name"]
        iface = nb.get("/dcim/interfaces/", device_id=device["id"], name=iface_name)["results"][0]

        ip = nb.ensure("/ipam/ip-addresses/", {"address": dev_def["ip"]}, {
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": iface["id"],
            "status": "active",
            "description": dev_def["name"],
        })

        # Set as primary IP for the device if not already set
        if not device.get("primary_ip4"):
            nb.patch(f"/dcim/devices/{device['id']}/", {"primary_ip4": ip["id"]})
            print(f"  updated: primary_ip4 for {dev_def['name']}")

    # Assign IPs to VM interfaces and create services
    for vm_def in VIRTUAL_MACHINES:
        if not vm_def.get("ip"):
            continue
        vm = nb.get("/virtualization/virtual-machines/", name=vm_def["name"])["results"][0]
        iface = nb.get("/virtualization/interfaces/", virtual_machine_id=vm["id"], name="eth0")["results"][0]

        ip = nb.ensure("/ipam/ip-addresses/", {"address": vm_def["ip"]}, {
            "assigned_object_type": "virtualization.vminterface",
            "assigned_object_id": iface["id"],
            "status": "active",
            "description": vm_def["name"],
        })

        # Set as primary IP
        if not vm.get("primary_ip4"):
            nb.patch(f"/virtualization/virtual-machines/{vm['id']}/", {"primary_ip4": ip["id"]})
            print(f"  updated: primary_ip4 for {vm_def['name']}")

        # Create services
        for svc_def in vm_def.get("services", []):
            nb.ensure("/ipam/services/", {
                "name": svc_def["name"],
                "parent_object_type": "virtualization.virtualmachine",
                "parent_object_id": vm["id"],
            }, {
                "name": svc_def["name"],
                "parent_object_type": "virtualization.virtualmachine",
                "parent_object_id": vm["id"],
                "ports": [svc_def["port"]],
                "protocol": svc_def["protocol"],
            })


def main():
    nb = NetBoxClient()
    print(f"NetBox: {nb.url}")

    site = populate_foundation(nb, SITE)
    populate_physical(nb, site)
    populate_virtual(nb)
    populate_ipam(nb, site)

    print("\n=== Done ===")
    vms = nb.get("/virtualization/virtual-machines/")
    ips = nb.get("/ipam/ip-addresses/")
    svcs = nb.get("/ipam/services/")
    print(f"VMs: {vms['count']}, IPs: {ips['count']}, Services: {svcs['count']}")


if __name__ == "__main__":
    main()
