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
from discover import build_full_topology

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
        "ip": "192.168.1.2/24",
    },
]

CLUSTERS = [
    {"name": "pve-cluster", "type": "Proxmox VE",
     "description": "Single-node Proxmox cluster"},
]

PREFIX = {"prefix": "192.168.1.0/24", "description": "Homelab LAN"}


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


# ---------------------------------------------------------------------------
# Population functions
# ---------------------------------------------------------------------------


def populate_foundation(nb):
    """Create site, manufacturers, platforms, cluster types, device roles, device types."""
    print("\n=== Foundation ===")

    site = nb.ensure(NB_DCIM_SITES, {"name": SITE["name"]}, {
        "slug": SITE["slug"], "status": SITE["status"], "description": SITE["description"],
    })

    for m in MANUFACTURERS:
        nb.ensure(NB_DCIM_MANUFACTURERS, {"name": m["name"]}, {"slug": m["slug"]})

    for p in PLATFORMS:
        nb.ensure(NB_DCIM_PLATFORMS, {"name": p["name"]}, {"slug": p["slug"]})

    for ct in CLUSTER_TYPES:
        nb.ensure(NB_VIRT_CLUSTER_TYPES, {"name": ct["name"]}, {"slug": ct["slug"]})

    for dr in DEVICE_ROLES:
        nb.ensure(NB_DCIM_DEVICE_ROLES, {"name": dr["name"]}, {
            "slug": dr["slug"], "color": dr["color"],
        })

    for dt in DEVICE_TYPES:
        mfg = nb.get(NB_DCIM_MANUFACTURERS, name=dt["manufacturer"])["results"][0]
        nb.ensure(NB_DCIM_DEVICE_TYPES, {"model": dt["model"]}, {
            "slug": dt["slug"], "manufacturer": mfg["id"],
        })

    return site


def populate_physical(nb, site):
    """Create physical devices (PVE host), their interfaces, and the cluster."""
    print("\n=== Physical Infrastructure ===")

    for dev_def in DEVICES:
        role = nb.get(NB_DCIM_DEVICE_ROLES, name=dev_def["role"])["results"][0]
        dtype = nb.get(NB_DCIM_DEVICE_TYPES, model=dev_def["device_type"])["results"][0]
        platform = nb.get(NB_DCIM_PLATFORMS, name=dev_def["platform"])["results"][0]

        device = nb.ensure(NB_DCIM_DEVICES, {"name": dev_def["name"]}, {
            "role": role["id"], "device_type": dtype["id"], "platform": platform["id"],
            "site": site["id"], "status": dev_def["status"],
            "description": dev_def["description"],
        })

        for iface_def in dev_def.get("interfaces", []):
            nb.ensure(NB_DCIM_INTERFACES, {
                "device_id": device["id"], "name": iface_def["name"],
            }, {
                "device": device["id"], "name": iface_def["name"],
                "type": iface_def["type"],
                "description": iface_def.get("description", ""),
            })

    for cl_def in CLUSTERS:
        ctype = nb.get(NB_VIRT_CLUSTER_TYPES, name=cl_def["type"])["results"][0]
        nb.ensure(NB_VIRT_CLUSTERS, {"name": cl_def["name"]}, {
            "type": ctype["id"], "site": site["id"], "description": cl_def["description"],
        })


def populate_network(nb, site, network):
    """Create router device, interfaces, VLANs, and router IPs from Mikrotik discovery."""
    print("\n=== Network Infrastructure ===")

    router = network.get("router")
    if not router:
        print("  skip: Mikrotik credentials not configured; no router data discovered")
        return

    role = nb.get(NB_DCIM_DEVICE_ROLES, name="Network")["results"][0]
    dtype = nb.get(NB_DCIM_DEVICE_TYPES, model="Mikrotik Router")["results"][0]

    router_name = router.get("identity", "mikrotik-router")
    router_device = nb.ensure(NB_DCIM_DEVICES, {"name": router_name}, {
        "role": role["id"],
        "device_type": dtype["id"],
        "site": site["id"],
        "status": "active",
        "description": f"Discovered via Mikrotik API ({router.get('host', '')})",
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
        })

    # Create VLAN group for router and VLANs discovered on it.
    vlan_group = nb.ensure("/ipam/vlan-groups/", {"name": f"{router_name}-vlans"}, {
        "slug": f"{router_name.lower().replace(' ', '-')}-vlans",
        "scope_type": "dcim.site",
        "scope_id": site["id"],
    })

    for vlan in network.get("vlans", []):
        vid_raw = vlan.get("vlan-id")
        if vid_raw is None:
            continue
        try:
            vid = int(vid_raw)
        except (TypeError, ValueError):
            continue
        name = vlan.get("name") or f"vlan-{vid}"
        nb.ensure("/ipam/vlans/", {"group_id": vlan_group["id"], "vid": vid}, {
            "group": vlan_group["id"],
            "name": name,
            "vid": vid,
            "status": "active",
        })

    # Assign router interface IPs.
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
        })
        if not router_device.get("primary_ip4") and "." in address:
            nb.patch(f"/dcim/devices/{router_device['id']}/", {"primary_ip4": ip_obj["id"]})
            print(f"  updated: primary_ip4 for {router_name}")


def populate_virtual(nb, vms):
    """Create VMs, their interfaces, and tags from discovered data."""
    print("\n=== Virtual Infrastructure ===")

    cluster = nb.get(NB_VIRT_CLUSTERS, name="pve-cluster")["results"][0]
    platform = nb.get(NB_DCIM_PLATFORMS, name="Debian 13")["results"][0]

    for vm_def in vms:
        tag_ids = []
        for tag_name in vm_def.get("tags", []):
            tag = nb.ensure("/extras/tags/", {"name": tag_name}, {"slug": tag_name})
            tag_ids.append({"name": tag_name, "slug": tag_name})

        # NetBox 4.5 virtual-machines only accept 'active' status; use description for state
        vm = nb.ensure(NB_VIRT_VIRTUAL_MACHINES, {"name": vm_def["name"]}, {
            "cluster": cluster["id"],
            "platform": platform["id"],
            "status": "active",  # NetBox only accepts 'active' for VMs
            "vcpus": vm_def.get("vcpus"),
            "memory": vm_def.get("memory"),
            "disk": vm_def.get("disk"),
            "description": f"{vm_def.get('description', '')} [Status: {vm_def['status']}]",
            "tags": tag_ids,
        })

        nb.ensure(NB_VIRT_INTERFACES, {
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
        device = nb.get(NB_DCIM_DEVICES, name=dev_def["name"])["results"][0]
        iface = nb.get(NB_DCIM_INTERFACES, device_id=device["id"],
                       name=dev_def["interfaces"][0]["name"])["results"][0]

        ip = nb.ensure(NB_IPAM_IP_ADDRESSES, {"address": dev_def["ip"]}, {
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
        vm = nb.get(NB_VIRT_VIRTUAL_MACHINES, name=vm_def["name"])["results"][0]
        iface = nb.get(NB_VIRT_INTERFACES,
                       virtual_machine_id=vm["id"], name="eth0")["results"][0]

        ip = nb.ensure(NB_IPAM_IP_ADDRESSES, {"address": vm_def["ip"]}, {
            "assigned_object_type": "virtualization.vminterface",
            "assigned_object_id": iface["id"],
            "status": "active", "description": vm_def["name"],
        })
        if not vm.get("primary_ip4"):
            nb.patch(f"/virtualization/virtual-machines/{vm['id']}/",
                     {"primary_ip4": ip["id"]})
            print(f"  updated: primary_ip4 for {vm_def['name']}")

        for svc_def in vm_def.get("services", []):
            nb.ensure(NB_IPAM_SERVICES, {
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

    # Discover full topology (VM + network).
    topology = build_full_topology()
    vms = topology["vms"]
    network = topology["network"]
    print(f"Discovered {len(vms)} VMs from Proxmox + Portainer")
    if network.get("router"):
        print(
            f"Discovered router {network['router'].get('identity', 'Mikrotik')} "
            f"with {len(network.get('interfaces', []))} interfaces and "
            f"{len(network.get('vlans', []))} VLANs"
        )

    site = populate_foundation(nb)
    populate_physical(nb, site)
    populate_network(nb, site, network)
    populate_virtual(nb, vms)
    populate_ipam(nb, site, vms)

    print("\n=== Done ===")
    vm_count = nb.get(NB_VIRT_VIRTUAL_MACHINES)["count"]
    ip_count = nb.get(NB_IPAM_IP_ADDRESSES)["count"]
    svc_count = nb.get(NB_IPAM_SERVICES)["count"]
    print(f"VMs: {vm_count}, IPs: {ip_count}, Services: {svc_count}")


if __name__ == "__main__":
    main()
