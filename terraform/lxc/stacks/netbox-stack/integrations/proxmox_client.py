"""Proxmox API client for homelab discovery."""

import json
import os
import ssl
import urllib.request
import urllib.error


class ProxmoxClient:
    """Thin wrapper around the Proxmox REST API.
    
    Proxmox uses token auth in the format: PVEAPIToken=userid:token_secret
    Self-signed certificates are common in homelab environments.
    """

    def __init__(self, url=None, token_id=None, token_secret=None):
        self.url = (url or os.environ.get("PROXMOX_URL") or f"https://{os.environ.get('PROXMOX_HOST')}:8006").rstrip("/")
        self.token_id = token_id or os.environ.get("PROXMOX_TOKEN_ID")
        self.token_secret = token_secret or os.environ.get("PROXMOX_TOKEN_SECRET")
        
        if not self.token_id or not self.token_secret:
            raise ValueError(
                "Proxmox auth requires PROXMOX_TOKEN_ID and PROXMOX_TOKEN_SECRET env vars"
            )

    def _request(self, method, path, data=None):
        """Make HTTP request to Proxmox API."""
        endpoint = f"{self.url}/api2/json{path}"
        body = json.dumps(data).encode() if data else None
        
        req = urllib.request.Request(
            endpoint,
            data=body,
            method=method,
            headers={
                "Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        
        # Disable SSL cert verification for self-signed homelab certs
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            with urllib.request.urlopen(req, context=ctx) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode())
                return None
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else ""
            raise RuntimeError(
                f"{method} {path} → {e.code}: {err_body}"
            ) from e

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, data):
        return self._request("POST", path, data)

    def get_nodes(self):
        """Get all cluster nodes."""
        resp = self.get("/nodes")
        return resp.get("data", []) if resp else []

    def get_lxc_containers(self, node):
        """Get all LXC containers on a node."""
        resp = self.get(f"/nodes/{node}/lxc")
        return resp.get("data", []) if resp else []

    def get_qemu_vms(self, node):
        """Get all QEMU VMs on a node."""
        resp = self.get(f"/nodes/{node}/qemu")
        return resp.get("data", []) if resp else []

    def get_node_config(self, node, vmid):
        """Get LXC or QEMU config. Tries LXC first, then QEMU."""
        try:
            resp = self.get(f"/nodes/{node}/lxc/{vmid}/config")
            if resp:
                return resp.get("data", {}), "lxc"
        except RuntimeError:
            pass
        
        try:
            resp = self.get(f"/nodes/{node}/qemu/{vmid}/config")
            if resp:
                return resp.get("data", {}), "qemu"
        except RuntimeError:
            pass
        
        return {}, None

    def get_node_status(self, node, vmid, vm_type):
        """Get current status (online/offline) of a container or VM."""
        endpoint = f"/nodes/{node}/{vm_type}/{vmid}/status/current"
        try:
            resp = self.get(endpoint)
            return resp.get("data", {}) if resp else {}
        except RuntimeError:
            return {}

    def get_node_networks(self, node):
        """Get network interfaces on a node (bridges, bonds, VLANs)."""
        resp = self.get(f"/nodes/{node}/network")
        return resp.get("data", []) if resp else []

    def get_storage(self):
        """Get all storage pools in the cluster."""
        resp = self.get("/storage")
        return resp.get("data", []) if resp else []

    def get_storage_content(self, storage_id):
        """Get content (volumes, snapshots) of a storage pool."""
        resp = self.get(f"/storage/{storage_id}/content")
        return resp.get("data", []) if resp else []


def discover_from_proxmox(url=None, token_id=None, token_secret=None):
    """Discover all infrastructure from Proxmox API.
    
    Returns dict structure:
    {
        "nodes": [{node info}, ...],
        "containers": [{container info with mounts}, ...],
        "storage": [{storage pool info}, ...],
        "networks": [{network interface info}, ...],
    }
    """
    client = ProxmoxClient(url, token_id, token_secret)
    
    nodes = client.get_nodes()
    containers = []
    storage = client.get_storage()
    networks = {}
    
    def parse_storage_spec(spec):
        """Parse Proxmox storage spec format: pool:id,mp=/path,size=XG
        Returns dict with: pool, id, mountpoint, size
        """
        if not spec:
            return None
        parts = spec.split(",")
        pool_id = parts[0].split(":")
        result = {"pool": pool_id[0], "id": pool_id[1] if len(pool_id) > 1 else None}
        for part in parts[1:]:
            if "=" in part:
                k, v = part.split("=", 1)
                result[k] = v
        return result
    
    # Collect all containers and VMs from each node
    for node in nodes:
        node_name = node["node"]
        
        # Get LXC containers
        for lxc in client.get_lxc_containers(node_name):
            vmid = lxc["vmid"]
            config, vm_type = client.get_node_config(node_name, vmid)
            status = client.get_node_status(node_name, vmid, "lxc")
            
            # Parse mounts from config
            mounts = []
            if "rootfs" in config:
                rootfs_spec = parse_storage_spec(config["rootfs"])
                if rootfs_spec:
                    rootfs_spec["type"] = "rootfs"
                    mounts.append(rootfs_spec)
            
            # Parse mp0, mp1, mp2, etc.
            for key in config:
                if key.startswith("mp") and key[2:].isdigit():
                    mp_spec = parse_storage_spec(config[key])
                    if mp_spec:
                        mp_spec["type"] = "mountpoint"
                        mounts.append(mp_spec)
            
            containers.append({
                "type": "lxc",
                "node": node_name,
                "vmid": vmid,
                "name": lxc.get("name"),
                "status": status.get("status"),
                "uptime": status.get("uptime"),
                "config": config,
                "mounts": mounts,
                "storage": lxc.get("storage"),
            })
        
        # Get QEMU VMs
        for qemu in client.get_qemu_vms(node_name):
            vmid = qemu["vmid"]
            config, vm_type = client.get_node_config(node_name, vmid)
            status = client.get_node_status(node_name, vmid, "qemu")
            
            # Parse mounts from QEMU config (disks are listed differently)
            mounts = []
            for key in config:
                if key in ["scsi0", "scsi1", "ide0", "ide1", "ide2", "virtio0", "virtio1"] or key.startswith(("scsi", "ide", "virtio", "sata")):
                    # QEMU disk format: storage:size,format=qcow2 or file
                    if ":" in config[key]:
                        disk_spec = parse_storage_spec(config[key])
                        if disk_spec:
                            disk_spec["type"] = key
                            mounts.append(disk_spec)
            
            containers.append({
                "type": "qemu",
                "node": node_name,
                "vmid": vmid,
                "name": qemu.get("name"),
                "status": status.get("status"),
                "uptime": status.get("uptime"),
                "config": config,
                "mounts": mounts,
                "storage": qemu.get("storage"),
            })
        
        # Get network config for this node
        networks[node_name] = client.get_node_networks(node_name)
    
    return {
        "nodes": nodes,
        "containers": containers,
        "storage": storage,
        "networks": networks,
    }


if __name__ == "__main__":
    """Test connectivity and output discovered topology."""
    import pprint
    
    try:
        print(f"Proxmox Host: {os.environ.get('PROXMOX_HOST')}")
        print(f"Proxmox Token ID: {os.environ.get('PROXMOX_TOKEN_ID')}")
        
        data = discover_from_proxmox()
        
        print(f"\nNodes: {len(data['nodes'])}")
        for node in data["nodes"]:
            print(f"  - {node['node']} ({node.get('cpu', 0):.2f} CPU, {node.get('maxcpu', 0)} cores, {node.get('memory', 0) / 1000000:.1f}GB RAM, {node.get('disk', 0) / 1000000:.1f}GB disk)")
        
        print(f"\nContainers/VMs: {len(data['containers'])}")
        for c in data["containers"][:5]:  # Show first 5
            print(f"  - {c['name']} ({c['type']}, VMID {c['vmid']}, status: {c['status']})")
            for mount in c.get('mounts', []):
                print(f"      mount: {mount['type']} → {mount.get('mp', mount.get('id', '?'))} on {mount['pool']} (size: {mount.get('size', '?')})")
        if len(data['containers']) > 5:
            print(f"  ... and {len(data['containers']) - 5} more")
        
        print(f"\nStorage Pools: {len(data['storage'])}")
        for s in data["storage"][:5]:  # Show first 5
            print(f"  - {s['storage']} ({s['type']}, {s.get('enabled', 0)} enabled)")
        if len(data['storage']) > 5:
            print(f"  ... and {len(data['storage']) - 5} more")
        
        print("\nNetworks by node:")
        for node_name, ifaces in data["networks"].items():
            print(f"  {node_name}: {len(ifaces)} interfaces")
            for iface in ifaces:
                print(f"    - {iface['iface']} ({iface['type']})")
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
