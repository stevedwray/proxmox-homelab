"""Mikrotik RouterOS API client for network topology discovery."""

import base64
import json
import os
import ssl
import urllib.request
import urllib.error


class MikrotikClient:
    """REST API client for Mikrotik RouterOS.
    
    RouterOS 7.x provides a REST API over HTTPS with self-signed certificates.
    Uses basic authentication (username:password in Authorization header).
    """

    def __init__(self, host=None, port=None, user=None, password=None):
        self.host = host or os.environ.get("MIKROTIK_HOST", "192.168.1.1")
        self.port = port or int(os.environ.get("MIKROTIK_PORT", "8729"))
        self.user = user or os.environ.get("MIKROTIK_USER")
        self.password = password or os.environ.get("MIKROTIK_PASSWORD")
        
        if not all([self.user, self.password]):
            raise ValueError(
                "Mikrotik auth requires MIKROTIK_USER and MIKROTIK_PASSWORD env vars"
            )
        
        # Create basic auth header: base64(user:password)
        auth_str = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        self.auth_header = f"Basic {auth_str}"
        self.base_url = f"https://{self.host}:{self.port}"

    def _request(self, method, path, data=None):
        """Make HTTP request to RouterOS REST API."""
        endpoint = f"{self.base_url}/rest{path}"
        body = json.dumps(data).encode() if data else None
        
        req = urllib.request.Request(
            endpoint,
            data=body,
            method=method,
            headers={
                "Authorization": self.auth_header,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        
        # Disable SSL cert verification for self-signed homelab certs
        # Use more permissive SSL settings for RouterOS compatibility
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # Allow older TLS versions for RouterOS compatibility
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
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

    def get_interfaces(self):
        """Get all network interfaces."""
        resp = self.get("/interface")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_vlans(self):
        """Get VLAN configuration."""
        resp = self.get("/interface/vlan")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_bridges(self):
        """Get bridge configuration."""
        resp = self.get("/interface/bridge")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_ip_addresses(self):
        """Get all configured IP addresses."""
        resp = self.get("/ip/address")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_routes(self):
        """Get routing table."""
        resp = self.get("/ip/route")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_firewall_rules(self):
        """Get firewall filter rules."""
        resp = self.get("/ip/firewall/filter")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_nat_rules(self):
        """Get NAT rules."""
        resp = self.get("/ip/firewall/nat")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_dhcp_servers(self):
        """Get DHCP server configuration."""
        resp = self.get("/ip/dhcp-server")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_dhcp_networks(self):
        """Get DHCP network pools."""
        resp = self.get("/ip/dhcp-server/network")
        if isinstance(resp, list):
            return resp
        if resp:
            return resp.get("response", [])
        return []

    def get_system_identity(self):
        """Get router system identity/name."""
        resp = self.get("/system/identity")
        if isinstance(resp, dict):
            return resp
        if resp:
            return resp.get("response", {})
        return {}


def discover_from_mikrotik(host=None, port=None, user=None, password=None):
    """Discover network topology from Mikrotik RouterOS.
    
    Returns dict structure:
    {
        "router": {name, identity, ...},
        "interfaces": [{interface info}, ...],
        "vlans": [{vlan info}, ...],
        "ip_addresses": [{ip config}, ...],
        "routes": [{route info}, ...],
        "firewall": {filter_rules: [...], nat_rules: [...]},
        "dhcp": {servers: [...], networks: [...]},
    }
    """
    client = MikrotikClient(host, port, user, password)
    
    try:
        identity = client.get_system_identity()
        interfaces = client.get_interfaces()
        vlans = client.get_vlans()
        bridges = client.get_bridges()
        ip_addresses = client.get_ip_addresses()
        routes = client.get_routes()
        filter_rules = client.get_firewall_rules()
        nat_rules = client.get_nat_rules()
        dhcp_servers = client.get_dhcp_servers()
        dhcp_networks = client.get_dhcp_networks()
    except Exception as e:
        print(f"Error querying Mikrotik: {e}")
        raise
    
    return {
        "router": {
            "identity": identity.get("name", "RouterOS"),
            "host": f"{client.host}:{client.port}",
        },
        "interfaces": interfaces,
        "vlans": vlans,
        "bridges": bridges,
        "ip_addresses": ip_addresses,
        "routes": routes,
        "firewall": {
            "filter_rules": filter_rules,
            "nat_rules": nat_rules,
        },
        "dhcp": {
            "servers": dhcp_servers,
            "networks": dhcp_networks,
        },
    }


if __name__ == "__main__":
    """Test connectivity and output network topology."""
    import pprint
    
    try:
        print(f"Mikrotik: {os.environ.get('MIKROTIK_HOST')}:{os.environ.get('MIKROTIK_PORT')}")
        data = discover_from_mikrotik()
        
        print(f"\nRouter: {data['router']['identity']}")
        
        print(f"\nInterfaces: {len(data['interfaces'])}")
        for iface in data["interfaces"][:10]:
            running = "↑" if iface.get("running") else "↓"
            print(f"  {running} {iface.get('name', '?'):15s} {iface.get('type', '?')}")
        if len(data['interfaces']) > 10:
            print(f"  ... and {len(data['interfaces']) - 10} more")
        
        print(f"\nVLANs: {len(data['vlans'])}")
        for vlan in data["vlans"][:5]:
            print(f"  - {vlan.get('name')} (ID {vlan.get('vlan-id')}) on {vlan.get('interface')}")
        if len(data['vlans']) > 5:
            print(f"  ... and {len(data['vlans']) - 5} more")
        
        print(f"\nIP Addresses: {len(data['ip_addresses'])}")
        for ip in data["ip_addresses"][:5]:
            print(f"  - {ip.get('address')} on {ip.get('interface')}")
        if len(data['ip_addresses']) > 5:
            print(f"  ... and {len(data['ip_addresses']) - 5} more")
        
        print(f"\nFirewall Rules: {len(data['firewall']['filter_rules'])} filter, {len(data['firewall']['nat_rules'])} NAT")
        
        print(f"\nDHCP: {len(data['dhcp']['servers'])} servers, {len(data['dhcp']['networks'])} networks")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
