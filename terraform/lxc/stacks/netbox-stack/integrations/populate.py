#!/usr/bin/env python3
"""Populate NetBox with Proxmox homelab topology.

Discovers VMs from stack.yaml files and the Portainer API, then idempotently
creates all objects in NetBox in dependency order.

Usage:
    source ../../../../../.env
    export NETBOX_URL=http://192.168.1.30:8080
    python3 populate.py          # populate
    python3 populate.py --clean  # wipe all managed objects
"""

from client import NetBoxClient
from discover import build_topology

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
        "ip": "192.168.1.2/24",
    },
]

CLUSTERS = [
    {"name": "pve-cluster", "type": "Proxmox VE",
     "description": "Single-node Proxmox cluster"},
]

PREFIX = {"prefix": "192.168.1.0/24", "description": "Homelab LAN"}


# ---------------------------------------------------------------------------
# Population functions
# ---------------------------------------------------------------------------


def populate_foundation(nb):
    """Create site, manufacturers, platforms, cluster types, device roles, device types."""
    print("\n=== Foundation ===")

    site = nb.ensure("/dcim/sites/", {"name": SITE["name"]}, {
        "slug": SITE["slug"], "status": SITE["status"], "description": SITE["description"],
    })

    for m in MANUFACTURERS:
        nb.ensure("/dcim/manufacturers/", {"name": m["name"]}, {"slug": m["slug"]})

    for p in PLATFORMS:
        nb.ensure("/dcim/platforms/", {"name": p["name"]}, {"slug": p["slug"]})

    for ct in CLUSTER_TYPES:
        nb.ensure("/virtualization/cluster-types/", {"name": ct["name"]}, {"slug": ct["slug"]})

    for dr in DEVICE_ROLES:
        nb.ensure("/dcim/device-roles/", {"name": dr["name"]}, {
            "slug": dr["slug"], "color": dr["color"],
        })

    for dt in DEVICE_TYPES:
        mfg = nb.get("/dcim/manufacturers/", name=dt["manufacturer"])["results"][0]
        nb.ensure("/dcim/device-types/", {"model": dt["model"]}, {
            "slug": dt["slug"], "manufacturer": mfg["id"],
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
            "role": role["id"], "device_type": dtype["id"], "platform": platform["id"],
            "site": site["id"], "status": dev_def["status"],
            "description": dev_def["description"],
        })

        for iface_def in dev_def.get("interfaces", []):
            nb.ensure("/dcim/interfaces/", {
                "device_id": device["id"], "name": iface_def["name"],
            }, {
                "device": device["id"], "name": iface_def["name"],
                "type": iface_def["type"],
                "description": iface_def.get("description", ""),
            })

    for cl_def in CLUSTERS:
        ctype = nb.get("/virtualization/cluster-types/", name=cl_def["type"])["results"][0]
        nb.ensure("/virtualization/clusters/", {"name": cl_def["name"]}, {
            "type": ctype["id"], "site": site["id"], "description": cl_def["description"],
        })


def populate_virtual(nb, vms):
    """Create VMs, their interfaces, and tags from discovered data."""
    print("\n=== Virtual Infrastructure ===")

    cluster = nb.get("/virtualization/clusters/", name="pve-cluster")["results"][0]
    platform = nb.get("/dcim/platforms/", name="Debian 13")["results"][0]

    for vm_def in vms:
        tag_ids = []
        for tag_name in vm_def.get("tags", []):
            tag = nb.ensure("/extras/tags/", {"name": tag_name}, {"slug": tag_name})
            tag_ids.append({"name": tag_name, "slug": tag_name})

        vm = nb.ensure("/virtualization/virtual-machines/", {"name": vm_def["name"]}, {
            "cluster": cluster["id"],
            "platform": platform["id"],
            "status": vm_def["status"],
            "vcpus": vm_def.get("vcpus"),
            "memory": vm_def.get("memory"),
            "disk": vm_def.get("disk"),
            "description": vm_def.get("description", ""),
            "tags": tag_ids,
        })

        nb.ensure("/virtualization/interfaces/", {
            "virtual_machine_id": vm["id"], "name": "eth0",
        }, {
            "virtual_machine": vm["id"], "name": "eth0", "type": "virtual",
        })


def populate_ipam(nb, site, vms):
    """Create prefix, assign IPs to interfaces, and register services."""
    print("\n=== IPAM ===")

    nb.ensure("/ipam/prefixes/", {"prefix": PREFIX["prefix"]}, {
        "site": site["id"], "description": PREFIX["description"], "status": "active",
    })

    # PVE host IP
    for dev_def in DEVICES:
        if not dev_def.get("ip"):
            continue
        device = nb.get("/dcim/devices/", name=dev_def["name"])["results"][0]
        iface = nb.get("/dcim/interfaces/", device_id=device["id"],
                       name=dev_def["interfaces"][0]["name"])["results"][0]

        ip = nb.ensure("/ipam/ip-addresses/", {"address": dev_def["ip"]}, {
            "assigned_object_type": "dcim.interface",
            "assigned_object_id": iface["id"],
            "status": "active", "description": dev_def["name"],
        })
        if not device.get("primary_ip4"):
            nb.patch(f"/dcim/devices/{device['id']}/", {"primary_ip4": ip["id"]})
            print(f"  updated: primary_ip4 for {dev_def['name']}")

    # VM IPs and services
    for vm_def in vms:
        if not vm_def.get("ip"):
            continue
        vm = nb.get("/virtualization/virtual-machines/", name=vm_def["name"])["results"][0]
        iface = nb.get("/virtualization/interfaces/",
                       virtual_machine_id=vm["id"], name="eth0")["results"][0]

        ip = nb.ensure("/ipam/ip-addresses/", {"address": vm_def["ip"]}, {
            "assigned_object_type": "virtualization.vminterface",
            "assigned_object_id": iface["id"],
            "status": "active", "description": vm_def["name"],
        })
        if not vm.get("primary_ip4"):
            nb.patch(f"/virtualization/virtual-machines/{vm['id']}/",
                     {"primary_ip4": ip["id"]})
            print(f"  updated: primary_ip4 for {vm_def['name']}")

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


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

WIPE_ORDER = [
    "/ipam/services/",
    "/ipam/ip-addresses/",
    "/ipam/prefixes/",
    "/virtualization/interfaces/",
    "/virtualization/virtual-machines/",
    "/virtualization/clusters/",
    "/virtualization/cluster-types/",
    "/dcim/interfaces/",
    "/dcim/devices/",
    "/dcim/device-types/",
    "/dcim/device-roles/",
    "/dcim/platforms/",
    "/dcim/manufacturers/",
    "/dcim/sites/",
    "/extras/tags/",
]


def clean(nb):
    """Delete all objects created by populate, in reverse dependency order."""
    print(f"NetBox: {nb.url}\n=== Cleaning ===")
    total = 0
    for path in WIPE_ORDER:
        while True:
            results = nb.get(path)
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    import sys

    nb = NetBoxClient()

    if "--clean" in sys.argv:
        clean(nb)
        return

    print(f"NetBox: {nb.url}")

    # Discover VMs from stack.yaml + Portainer
    vms = build_topology()
    print(f"Discovered {len(vms)} VMs from stack.yaml + Portainer")

    site = populate_foundation(nb)
    populate_physical(nb, site)
    populate_virtual(nb, vms)
    populate_ipam(nb, site, vms)

    print("\n=== Done ===")
    vm_count = nb.get("/virtualization/virtual-machines/")["count"]
    ip_count = nb.get("/ipam/ip-addresses/")["count"]
    svc_count = nb.get("/ipam/services/")["count"]
    print(f"VMs: {vm_count}, IPs: {ip_count}, Services: {svc_count}")


if __name__ == "__main__":
    main()
