#!/usr/bin/env python3
"""Derive inter-service data flows for threat modeling from homelab stack config.

Auto-populates from:
  - stack.yaml   (processes, depends_on, provides, registry_host,
                  apt_cacher_host, docker_socket_proxy_targets,
                  enable_docker_socket_proxy)
  - edge.yaml    (Traefik routes and auth modes)
  - docker-compose.yml (monitoring agent sidecars: promtail, cadvisor)
  - terraform/lxc/network/{env}.yaml  (zone policies)

Merges with manual annotations from docs/threat-model/annotations.yaml.

Standalone usage:
    python3 flows.py [--env pve]              # print derived model as YAML
    python3 flows.py --env pve --json         # print as JSON

Called from populate.py to push the model to NetBox as a config context.
"""

import glob
import json
import os
import re
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

_INTEG_DIR = Path(__file__).parent.resolve()
_STACKS_DIR = _INTEG_DIR.parent.parent          # terraform/lxc/stacks/
_NETWORK_DIR = _INTEG_DIR.parent.parent.parent / "network"  # terraform/lxc/network/
_REPO_ROOT = _INTEG_DIR.parents[4]              # repo root
_ANNOTATIONS_PATH = _REPO_ROOT / "docs" / "threat-model" / "annotations.yaml"

_ENV_TOKEN_RE = re.compile(r"^\$\{([A-Za-z_]\w*)\}$")
_HOLD_DIR = "/.hold/"  # nosonar: python:S1192
_MIKROTIK_FIREWALL = "MikroTik inter-VLAN firewall"  # nosonar: python:S1192

NETWORK_INTENT_FILES = {
    "pve": "pve.yaml",
    "pve-test": "pve-test.yaml",
    "pve-test-vm": "pve-test-vm.yaml",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_token(value):
    """Resolve a ${VAR} placeholder from the environment, or return raw value."""
    if not isinstance(value, str):
        return value
    m = _ENV_TOKEN_RE.match(value.strip())
    if not m:
        return value
    token = m.group(1)
    for name in (token, token.upper(), f"TF_VAR_{token}", f"TF_VAR_{token.upper()}",
                 token.lower(), f"TF_VAR_{token.lower()}"):
        v = os.environ.get(name)
        if v:
            return v
    return value


def _load_yaml(path):
    """Load a YAML file, returning {} on missing or error."""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _process_id(stack_name):
    """Convert a stack name to a process id: 'proxy-stack' → 'p-proxy'."""
    return "p-" + re.sub(r"-stack$", "", stack_name)


def _flow_id(*parts):
    """Build a flow id from parts, slugifying each."""
    return "df-" + "-to-".join(
        re.sub(r"[^a-z0-9]+", "-", str(p).lower()).strip("-")
        for p in parts
    )


def _ip_from_address(raw):
    """Strip prefix length from an IP address string."""
    if isinstance(raw, str):
        return raw.split("/")[0].strip()
    return None


# ---------------------------------------------------------------------------
# Load source files
# ---------------------------------------------------------------------------

def load_all_stacks(stacks_dir=None):
    """Return dict {stack_name: stack_dict} for all non-hold platform stacks."""
    root = Path(stacks_dir) if stacks_dir else _STACKS_DIR
    stacks = {}
    for path in sorted(root.glob("*/stack.yaml")):
        if _HOLD_DIR in str(path) or "\\.hold\\" in str(path):
            continue
        name = path.parent.name
        data = _load_yaml(path)
        # Resolve common env tokens
        for field in ("ip_address", "registry_host", "apt_cacher_host",
                      "portainer_server_ip"):
            if field in data:
                data[field] = _resolve_token(data[field])
        if isinstance(data.get("docker_socket_proxy_targets"), list):
            data["docker_socket_proxy_targets"] = [
                _resolve_token(t) for t in data["docker_socket_proxy_targets"]
            ]
        stacks[name] = data
    return stacks


def load_edge_yamls(stacks_dir=None):
    """Return dict {stack_name: edge_dict} for all stacks that have an edge.yaml."""
    root = Path(stacks_dir) if stacks_dir else _STACKS_DIR
    edges = {}
    for path in sorted(root.glob("*/edge.yaml")):
        if _HOLD_DIR in str(path):
            continue
        name = path.parent.name
        edges[name] = _load_yaml(path)
    return edges


def load_docker_composes(stacks_dir=None):
    """Return dict {stack_name: compose_dict} for stacks with docker-compose.yml."""
    root = Path(stacks_dir) if stacks_dir else _STACKS_DIR
    composes = {}
    for path in sorted(root.glob("*/docker-compose.yml")):
        if _HOLD_DIR in str(path):
            continue
        name = path.parent.name
        composes[name] = _load_yaml(path)
    return composes


def load_network_intent(env=None):
    """Load the network intent YAML for the given environment."""
    if env is None:
        env = (os.environ.get("NETBOX_NETWORK_ENV")
               or os.environ.get("PVE_ENV")
               or os.environ.get("TF_VAR_proxmox_node")
               or "pve")
    filename = NETWORK_INTENT_FILES.get(env, f"{env}.yaml")
    path = _NETWORK_DIR / filename
    return _load_yaml(path)


def load_annotations(path=None):
    """Load manual annotations from docs/threat-model/annotations.yaml."""
    return _load_yaml(path or _ANNOTATIONS_PATH)


# ---------------------------------------------------------------------------
# Platform stack detection
# ---------------------------------------------------------------------------

_PLATFORM_TIERS = {"platform"}
_SKIP_STACKS = {
    "docker-socket-proxy-test", "test-docker", "test-lxc",
    "test-storage", "test-storage-extra",
    "net-app-01", "net-build-01", "net-client-01", "net-client-02",
    "net-isolated-01", "net-service-01", "net-service-02", "net-svc-01",
    "net-artifacts-01",
}


def _is_platform_stack(name, stack):
    if name in _SKIP_STACKS:
        return False
    tier = stack.get("deployment_tier")
    if tier and tier not in _PLATFORM_TIERS:
        return False
    # Must have a network zone or be a known platform service
    return bool(stack.get("network", {}).get("zone"))


# ---------------------------------------------------------------------------
# Static definitions
# ---------------------------------------------------------------------------

EXTERNAL_ENTITIES = [
    {
        "id": "ee-lan-user",
        "name": "LAN User / Operator",
        "description": (
            "Human operator accessing lab services via browser from the local LAN. "
            "Currently a single-person homelab."
        ),
        "trust_level": "medium",
    },
    {
        "id": "ee-internet",
        "name": "Public internet",
        "description": (
            "Untrusted public internet. Inbound limited to tcp/80 and tcp/443 "
            "forwarded by MikroTik NAT to Traefik."
        ),
        "trust_level": "untrusted",
    },
    {
        "id": "ee-github",
        "name": "GitHub / GitHub Actions",
        "description": (
            "GitHub-hosted infrastructure: git hosting, Actions job dispatch to the "
            "self-hosted CI runner, and GitHub REST API (polled by NetBox)."
        ),
        "trust_level": "low",
    },
    {
        "id": "ee-letsencrypt",
        "name": "Let's Encrypt ACME",
        "description": (
            "Public CA for TLS certificates on *.lab.gibbsgreatly.xyz. "
            "Traefik handles ACME via httpChallenge."
        ),
        "trust_level": "medium",
    },
    {
        "id": "ee-upstream-registries",
        "name": "Upstream container registries",
        "description": (
            "Docker Hub, ghcr.io, gcr.io. Harbor proxies all pulls; LXCs never "
            "contact upstream registries directly."
        ),
        "trust_level": "low",
    },
    {
        "id": "ee-debian-mirrors",
        "name": "Debian package mirrors",
        "description": (
            "Public Debian APT mirrors. apt-cacher-ng proxies all package fetches; "
            "LXCs never contact mirrors directly."
        ),
        "trust_level": "low",
    },
    {
        "id": "ee-github-api",
        "name": "GitHub REST API",
        "description": (
            "GitHub API polled by NetBox for release version checks "
            "(RELEASE_CHECK_URL, unauthenticated)."
        ),
        "trust_level": "low",
    },
]

TRUST_BOUNDARIES = [
    {
        "id": "tb-internet",
        "name": "Internet perimeter",
        "type": "network",
        "description": (
            "Physical boundary between the public internet and the LAN. "
            "MikroTik performs NAT; only ports 80 and 443 are forwarded inbound to Traefik."
        ),
        "enforcement": "MikroTik NAT + firewall",
    },
    {
        "id": "tb-edge-to-mgmt",
        "name": "edge_seg → mgmt_seg",
        "type": "network-zone",
        "description": "VLAN 30 → VLAN 20. MikroTik enforces firewall rules.",
        "allowed_flows": "tcp/9000, tcp/9443 (forwardAuth); tcp/80 (ACME callback)",
        "enforcement": "MikroTik inter-VLAN firewall",
    },
    {
        "id": "tb-edge-to-infra",
        "name": "edge_seg → infra_seg",
        "type": "network-zone",
        "description": "VLAN 30 → VLAN 40. MikroTik enforces firewall rules.",
        "allowed_flows": "tcp/80, tcp/443, tcp/3142",
        "enforcement": "MikroTik inter-VLAN firewall",
    },
    {
        "id": "tb-mgmt-to-infra",
        "name": "mgmt_seg → infra_seg",
        "type": "network-zone",
        "description": "VLAN 20 → VLAN 40. MikroTik enforces firewall rules.",
        "allowed_flows": "tcp/80, tcp/443, tcp/3142, tcp/9000, tcp/9443",
        "enforcement": "MikroTik inter-VLAN firewall",
    },
    {
        "id": "tb-build-to-mgmt",
        "name": "build_seg → mgmt_seg",
        "type": "network-zone",
        "description": "VLAN 10 → VLAN 20. MikroTik enforces firewall rules.",
        "allowed_flows": "tcp/9000, tcp/8428, tcp/3100",
        "enforcement": "MikroTik inter-VLAN firewall",
    },
    {
        "id": "tb-build-to-infra",
        "name": "build_seg → infra_seg",
        "type": "network-zone",
        "description": "VLAN 10 → VLAN 40. MikroTik enforces firewall rules.",
        "allowed_flows": "tcp/80, tcp/443, tcp/3142",
        "enforcement": "MikroTik inter-VLAN firewall",
    },
    {
        "id": "tb-lxc-host",
        "name": "LXC container boundary",
        "type": "host",
        "description": (
            "Proxmox LXC namespace boundary. Unprivileged containers sharing the "
            "host kernel. Breakout reaches the pve host directly."
        ),
        "enforcement": "Proxmox LXC (Linux namespaces, cgroups)",
    },
]

# Static data stores (not derived — these are known from docker-compose inspection)
DATA_STORES = [
    {
        "id": "ds-authentik-db",
        "name": "Authentik PostgreSQL",
        "host": "p-authentik",
        "type": "postgresql",
        "data_classification": "secret",
        "contents": (
            "User accounts and hashed passwords, OAuth2 client credentials, "
            "OIDC tokens, active sessions, group memberships."
        ),
    },
    {
        "id": "ds-harbor-storage",
        "name": "Harbor image storage",
        "host": "p-harbor",
        "type": "filesystem",
        "data_classification": "internal",
        "contents": "OCI image blobs and manifests for all lab services.",
    },
    {
        "id": "ds-harbor-db",
        "name": "Harbor PostgreSQL",
        "host": "p-harbor",
        "type": "postgresql",
        "data_classification": "confidential",
        "contents": "Registry metadata, user accounts, OIDC mappings, vulnerability scan results.",
    },
    {
        "id": "ds-netbox-db",
        "name": "NetBox PostgreSQL",
        "host": "p-netbox",
        "type": "postgresql",
        "data_classification": "internal",
        "contents": "Full infrastructure inventory: VM IDs, IPs, MACs, topology, service endpoints.",
    },
    {
        "id": "ds-monitoring-metrics",
        "name": "VictoriaMetrics time-series",
        "host": "p-monitoring",
        "type": "victoriametrics",
        "data_classification": "internal",
        "contents": "Container resource metrics for all monitored LXCs.",
    },
    {
        "id": "ds-monitoring-logs",
        "name": "Loki log store",
        "host": "p-monitoring",
        "type": "loki",
        "data_classification": "confidential",
        "contents": "Container logs. May contain auth events, error traces, credential fragments.",
    },
    {
        "id": "ds-step-ca-keys",
        "name": "step-ca CA private keys",
        "host": "p-step-ca",
        "type": "filesystem",
        "data_classification": "secret",
        "contents": "CA root and intermediate private keys for lab.gibbsgreatly.xyz.",
    },
    {
        "id": "ds-sops-secrets",
        "name": "SOPS-encrypted secrets",
        "host": "pve-host",
        "type": "filesystem",
        "data_classification": "secret",
        "contents": (
            "terraform/secrets.enc.yaml and secrets.pve.enc.yaml. "
            "DB passwords, API tokens, OIDC client secrets. "
            "Encrypted with age key at ~/.config/sops/age/keys.txt."
        ),
        "encryption_at_rest": True,
    },
]

# Static external flows that cannot be derived from config files
_EXTERNAL_FLOWS = [
    {
        "id": "df-harbor-upstream-pull",
        "name": "Harbor upstream registry proxy on cache miss",
        "from": "p-harbor",
        "to": "ee-upstream-registries",
        "protocol": "tcp",
        "port": 443,
        "transport_security": "tls",
        "auth": "none",
        "data_classification": "public",
        "data": "OCI image manifests and layer blobs from Docker Hub, ghcr.io, gcr.io.",
        "trigger": "on-demand",
        "trust_boundary_crossing": "tb-internet",
        "inferred_from": "Harbor proxy-cache config; all stack.yaml registry_host values",
    },
    {
        "id": "df-apt-cacher-upstream",
        "name": "apt-cacher-ng upstream mirror fetch on cache miss",
        "from": "p-apt-cacher",
        "to": "ee-debian-mirrors",
        "protocol": "tcp",
        "port": 80,
        "transport_security": "none",
        "auth": "none",
        "data_classification": "public",
        "data": "Debian package files and index metadata.",
        "trigger": "on-demand",
        "trust_boundary_crossing": "tb-internet",
        "inferred_from": "apt-cacher-ng standard operation",
        "needs_annotation": True,
        "annotation_hint": "Does apt-cacher use https mirrors? Check apt-cacher-ng config.",
    },
    {
        "id": "df-traefik-to-letsencrypt",
        "name": "Traefik ACME certificate issuance",
        "from": "p-traefik",
        "to": "ee-letsencrypt",
        "protocol": "tcp",
        "port": 443,
        "transport_security": "tls",
        "auth": "acme-account-key",
        "data_classification": "internal",
        "data": "ACME CSRs for *.lab.gibbsgreatly.xyz TLS certificates.",
        "trigger": "scheduled",
        "trust_boundary_crossing": "tb-internet",
        "inferred_from": "edge.yaml (tls.resolver: letsencrypt on all routes)",
    },
    {
        "id": "df-letsencrypt-to-traefik",
        "name": "Let's Encrypt httpChallenge validation",
        "from": "ee-letsencrypt",
        "to": "p-traefik",
        "protocol": "tcp",
        "port": 80,
        "transport_security": "none",
        "auth": "none",
        "data_classification": "public",
        "data": "Validation GET to /.well-known/acme-challenge/<token>.",
        "trigger": "on-demand",
        "trust_boundary_crossing": "tb-internet",
        "inferred_from": "standard ACME httpChallenge flow",
    },
    {
        "id": "df-step-ca-to-traefik",
        "name": "step-ca ACME challenge via Traefik",
        "from": "p-step-ca",
        "to": "p-traefik",
        "protocol": "tcp",
        "port": 80,
        "transport_security": "none",
        "auth": "none",
        "data_classification": "public",
        "data": "step-ca's own ACME httpChallenge token served through Traefik.",
        "trigger": "scheduled",
        "trust_boundary_crossing": "tb-edge-to-mgmt",
        "inferred_from": "pve.yaml policy: mgmt_seg → edge_seg :80",
    },
    {
        "id": "df-ci-to-github",
        "name": "CI runner to GitHub Actions (polling and status)",
        "from": "p-ci-runner",
        "to": "ee-github",
        "protocol": "tcp",
        "port": 443,
        "transport_security": "tls",
        "auth": "runner-registration-token",
        "data_classification": "confidential",
        "data": (
            "Job polling (long-poll), job status reporting, artifact uploads, "
            "git repository fetch for checked-out code."
        ),
        "trigger": "runtime",
        "trust_boundary_crossing": "tb-internet",
        "inferred_from": "ci-runner-01 stack.yaml (build_seg, GitHub Actions runner)",
    },
    {
        "id": "df-netbox-to-github-api",
        "name": "NetBox release check to GitHub API",
        "from": "p-netbox",
        "to": "ee-github-api",
        "protocol": "tcp",
        "port": 443,
        "transport_security": "tls",
        "auth": "none",
        "data_classification": "public",
        "data": "GET /repos/netbox-community/netbox/releases (unauthenticated).",
        "trigger": "runtime",
        "trust_boundary_crossing": "tb-internet",
        "inferred_from": "RELEASE_CHECK_URL in netbox-stack docker-compose.yml",
    },
    {
        "id": "df-user-to-traefik",
        "name": "Browser HTTPS ingress",
        "from": "ee-lan-user",
        "to": "p-traefik",
        "protocol": "tcp",
        "port": 443,
        "transport_security": "tls",
        "auth": "none",
        "data_classification": "varies",
        "data": "HTTPS requests for all lab services. TLS terminated at Traefik.",
        "trigger": "runtime",
        "trust_boundary_crossing": "tb-internet",
        "inferred_from": "edge.yaml routes, MikroTik port forward",
        "needs_annotation": True,
        "annotation_hint": "Is tcp/443 port-forwarded from the internet, or LAN-only?",
    },
    {
        "id": "df-traefik-forwardauth",
        "name": "Traefik forward auth check to Authentik",
        "from": "p-traefik",
        "to": "p-authentik",
        "protocol": "tcp",
        "port": 9000,
        "transport_security": "none",
        "auth": "session-cookie",
        "data_classification": "confidential",
        "data": (
            "Per-request auth check: forwarded request headers (cookies, X-Forwarded-*). "
            "Authentik returns X-Authentik-* headers (username, email, groups) or 401."
        ),
        "trigger": "runtime",
        "trust_boundary_crossing": "tb-edge-to-mgmt",
        "inferred_from": "netbox and proxy-stack edge.yaml (auth.mode: forwardAuth)",
    },
]

# ---------------------------------------------------------------------------
# Derivation functions
# ---------------------------------------------------------------------------

def derive_processes(stacks):
    """Build process node list from platform stack.yaml files."""
    processes = []
    for name, stack in stacks.items():
        if not _is_platform_stack(name, stack):
            continue
        pid = _process_id(name)
        zone = stack.get("network", {}).get("zone", "unknown")
        ip_raw = stack.get("ip_address", "")
        ip = _ip_from_address(ip_raw)

        provides = [
            {
                "port": p.get("port"),
                "protocol": p.get("protocol", "tcp"),
                "service": p.get("service", ""),
            }
            for p in (stack.get("provides") or [])
        ]

        processes.append({
            "id": pid,
            "name": stack.get("hostname", name),
            "stack": name,
            "vmid": stack.get("vmid"),
            "zone": zone,
            "ip": ip,
            "provides": provides,
            "deployment_tier": stack.get("deployment_tier", "platform"),
            "tags": stack.get("tags", []),
        })
    return processes


def derive_registry_flows(stacks, processes):
    """Derive OCI image pull flows from registry_host declarations."""
    flows = []
    process_ids = {p["stack"]: p["id"] for p in processes}
    harbor_pid = process_ids.get("harbor-stack", "p-harbor")

    for name, stack in stacks.items():
        if not _is_platform_stack(name, stack):
            continue
        registry = stack.get("registry_host") or ""
        if not registry or name == "harbor-stack":
            continue
        pid = process_ids.get(name, _process_id(name))
        src_zone = stack.get("network", {}).get("zone", "unknown")
        tb = _zone_boundary(src_zone, "infra_seg")
        flows.append({
            "id": _flow_id(pid, harbor_pid),
            "name": f"{name} pulls images from Harbor",
            "from": pid,
            "to": harbor_pid,
            "protocol": "tcp",
            "port": 443,
            "transport_security": "tls",
            "auth": "none",
            "data_classification": "public",
            "data": "OCI image layers and manifests for all deployed containers.",
            "trigger": "deploy-time",
            "trust_boundary_crossing": tb,
            "inferred_from": f"registry_host in {name}/stack.yaml",
            "needs_annotation": True,
            "annotation_hint": "Does this LXC authenticate to Harbor for pulls, or anonymous?",
        })
    return flows


def derive_apt_flows(stacks, processes):
    """Derive APT proxy flows from apt_cacher_host declarations."""
    flows = []
    process_ids = {p["stack"]: p["id"] for p in processes}
    apt_pid = process_ids.get("apt-cacher-stack", "p-apt-cacher")

    for name, stack in stacks.items():
        if not _is_platform_stack(name, stack):
            continue
        apt_host = stack.get("apt_cacher_host") or ""
        # Empty string means "no apt proxy" (e.g. harbor-stack on first deploy)
        if not apt_host or name == "apt-cacher-stack":
            continue
        pid = process_ids.get(name, _process_id(name))
        src_zone = stack.get("network", {}).get("zone", "unknown")
        tb = _zone_boundary(src_zone, "infra_seg")
        flows.append({
            "id": _flow_id(pid, apt_pid),
            "name": f"{name} apt packages via apt-cacher-ng",
            "from": pid,
            "to": apt_pid,
            "protocol": "tcp",
            "port": 3142,
            "transport_security": "none",
            "auth": "none",
            "data_classification": "public",
            "data": "Debian/Ubuntu package downloads.",
            "trigger": "deploy-time",
            "trust_boundary_crossing": tb,
            "inferred_from": f"apt_cacher_host in {name}/stack.yaml",
        })
    return flows


def derive_socket_proxy_flows(stacks, processes):
    """Derive NetBox docker-socket-proxy discovery flows.

    The netbox populate script queries port 2375 on each host that has
    enable_docker_socket_proxy: true.
    """
    flows = []
    process_ids = {p["stack"]: p["id"] for p in processes}
    netbox_pid = process_ids.get("netbox-stack", "p-netbox")
    netbox_zone = stacks.get("netbox-stack", {}).get("network", {}).get("zone", "infra_seg")

    for name, stack in stacks.items():
        if not _is_platform_stack(name, stack):
            continue
        if not stack.get("enable_docker_socket_proxy"):
            continue
        target_pid = process_ids.get(name, _process_id(name))
        target_zone = stack.get("network", {}).get("zone", "unknown")
        tb = _zone_boundary(netbox_zone, target_zone)
        flows.append({
            "id": _flow_id(netbox_pid, target_pid) + "-socket-proxy",
            "name": f"NetBox docker-socket-proxy discovery → {name}",
            "from": netbox_pid,
            "to": target_pid,
            "protocol": "tcp",
            "port": stack.get("docker_socket_proxy_listen_port", 2375),
            "transport_security": "none",
            "auth": "none",
            "data_classification": "internal",
            "data": (
                "Read-only Docker API: container list, image list, port bindings. "
                "Used by populate.py for NetBox service discovery."
            ),
            "trigger": "on-demand",
            "trust_boundary_crossing": tb,
            "inferred_from": f"enable_docker_socket_proxy in {name}/stack.yaml",
        })
    return flows


def derive_edge_flows(stacks, edge_yamls, processes):
    """Derive Traefik reverse-proxy route flows from edge.yaml files."""
    flows = []
    process_ids = {p["stack"]: p["id"] for p in processes}
    traefik_pid = process_ids.get("proxy-stack", "p-proxy")

    for stack_name, edge in edge_yamls.items():
        spec = edge.get("spec", {})
        for route in spec.get("routes", []):
            backend = route.get("backend", {})
            btype = backend.get("type", "")
            url = backend.get("url", "")
            auth_mode = route.get("auth", {}).get("mode", "none")

            # Skip internal Traefik service routes (e.g. api@internal)
            if btype == "traefikService":
                continue

            # Try to match the backend URL to a process by IP
            target_pid = _url_to_process_id(url, stacks, process_ids)
            if not target_pid:
                target_pid = process_ids.get(stack_name, _process_id(stack_name))

            port = _url_port(url)
            host = route.get("host", "")
            route_name = route.get("name", stack_name)

            # Map auth mode to transport and auth fields
            transport_security = "none"   # backend connection within zone
            if auth_mode == "forwardAuth":
                auth_desc = "forward-auth (Authentik per-request check)"
            elif auth_mode == "oidc":
                auth_desc = "oidc (Authentik)"
            else:
                auth_desc = "none"

            target_zone = stacks.get(stack_name, {}).get("network", {}).get("zone", "unknown")
            tb = _zone_boundary("edge_seg", target_zone)

            flows.append({
                "id": f"df-traefik-to-{_process_id(stack_name)[2:]}",
                "name": f"Traefik routes {host} → {stack_name}",
                "from": traefik_pid,
                "to": target_pid,
                "protocol": "tcp",
                "port": port,
                "transport_security": transport_security,
                "auth": auth_desc,
                "data_classification": "internal",
                "data": f"Routed traffic for {host}",
                "trigger": "runtime",
                "trust_boundary_crossing": tb,
                "inferred_from": f"{stack_name}/edge.yaml (auth.mode: {auth_mode})",
            })

    return flows


def derive_zone_policy_flows(network_intent, processes):
    """Derive zone-level flows from network intent policy section.

    These are zone-level (not service-level) firewall intents that document
    permitted inter-zone traffic patterns.
    """
    flows = []
    policies = network_intent.get("policies", [])
    for i, policy in enumerate(policies):
        from_zone = policy.get("from", "unknown")
        to_zone = policy.get("to", "unknown")
        ports = policy.get("ports", [])
        proto = policy.get("protocol", "tcp")
        desc = policy.get("description", "")

        flows.append({
            "id": f"df-zone-policy-{i:02d}",
            "name": f"Zone policy: {from_zone} → {to_zone}",
            "from": f"zone:{from_zone}",
            "to": f"zone:{to_zone}",
            "protocol": proto,
            "ports": ports,
            "data_classification": "varies",
            "data": desc,
            "trigger": "runtime",
            "trust_boundary_crossing": _zone_boundary(from_zone, to_zone),
            "inferred_from": "pve.yaml policies section",
            "flow_type": "zone-policy",
        })
    return flows


def derive_monitoring_flows(stacks, composes, processes):
    """Derive log-shipping and metrics-scrape flows from docker-compose.yml sidecars."""
    flows = []
    process_ids = {p["stack"]: p["id"] for p in processes}
    monitoring_pid = process_ids.get("monitoring-stack", "p-monitoring")
    monitoring_zone = stacks.get("monitoring-stack", {}).get("network", {}).get("zone", "mgmt_seg")

    for stack_name, compose in composes.items():
        if not _is_platform_stack(stack_name, stacks.get(stack_name, {})):
            continue
        stack_pid = process_ids.get(stack_name, _process_id(stack_name))
        stack_zone = stacks.get(stack_name, {}).get("network", {}).get("zone", "unknown")
        services = compose.get("services", {}) or {}

        # Promtail → Loki (log shipping)
        if "promtail" in services:
            tb = _zone_boundary(stack_zone, monitoring_zone)
            flows.append({
                "id": f"df-{_process_id(stack_name)[2:]}-to-loki",
                "name": f"{stack_name} promtail log shipping to Loki",
                "from": stack_pid,
                "to": monitoring_pid,
                "protocol": "tcp",
                "port": 3100,
                "transport_security": "none",
                "auth": "none",
                "data_classification": "confidential",
                "data": (
                    "Container stdout/stderr logs. May contain auth events, error traces, "
                    "or credential fragments."
                ),
                "trigger": "runtime",
                "trust_boundary_crossing": tb,
                "inferred_from": f"promtail service in {stack_name}/docker-compose.yml",
                "needs_annotation": True,
                "annotation_hint": "Is Loki push authenticated? Are logs filtered to redact secrets?",
            })

        # Cadvisor → VictoriaMetrics scrape
        if "cadvisor" in services:
            cadvisor_svc = services["cadvisor"]
            cadvisor_ports = cadvisor_svc.get("ports", [])
            # ports may be ["8080:8080"] or ["8081:8080"]
            host_port = 8080
            for p in cadvisor_ports:
                if isinstance(p, str) and ":" in p:
                    try:
                        host_port = int(p.split(":")[0])
                    except ValueError:
                        pass
            tb = _zone_boundary(monitoring_zone, stack_zone)
            flows.append({
                "id": f"df-monitoring-scrape-{_process_id(stack_name)[2:]}",
                "name": f"VictoriaMetrics scrapes cadvisor on {stack_name}",
                "from": monitoring_pid,
                "to": stack_pid,
                "protocol": "tcp",
                "port": host_port,
                "transport_security": "none",
                "auth": "none",
                "data_classification": "internal",
                "data": "Container resource metrics: CPU, memory, disk I/O, network.",
                "trigger": "runtime",
                "trust_boundary_crossing": tb,
                "inferred_from": f"cadvisor service in {stack_name}/docker-compose.yml",
                "needs_annotation": True,
                "annotation_hint": "Confirm VictoriaMetrics scrape config targets this host.",
            })

    return flows


# ---------------------------------------------------------------------------
# Zone boundary helpers
# ---------------------------------------------------------------------------

_ZONE_BOUNDARY_MAP = {
    frozenset({"edge_seg", "mgmt_seg"}): "tb-edge-to-mgmt",
    frozenset({"edge_seg", "infra_seg"}): "tb-edge-to-infra",
    frozenset({"mgmt_seg", "infra_seg"}): "tb-mgmt-to-infra",
    frozenset({"build_seg", "mgmt_seg"}): "tb-build-to-mgmt",
    frozenset({"build_seg", "infra_seg"}): "tb-build-to-infra",
}


def _zone_boundary(src, dst):
    """Return trust boundary id for a zone pair, or None if same zone."""
    if not src or not dst or src == dst:
        return None
    return _ZONE_BOUNDARY_MAP.get(frozenset({src, dst}))


def _url_port(url):
    """Extract port from a backend URL like http://1.2.3.4:9000."""
    if not isinstance(url, str):
        return 80
    m = re.search(r":(\d+)(?:/|$)", url.replace("http://", "").replace("https://", ""))
    if m:
        return int(m.group(1))
    return 443 if url.startswith("https") else 80


def _url_to_process_id(url, stacks, process_ids):
    """Try to map a backend URL to a process id by resolving its IP."""
    if not isinstance(url, str):
        return None
    # Strip scheme and path, extract host:port
    host_part = url.replace("http://", "").replace("https://", "").split("/")[0]
    host = host_part.split(":")[0].strip()
    if not host:
        return None
    for name, stack in stacks.items():
        ip_raw = stack.get("ip_address", "")
        ip = _ip_from_address(_resolve_token(ip_raw))
        if ip and ip == host:
            return process_ids.get(name, _process_id(name))
    return None


# ---------------------------------------------------------------------------
# Annotation merging
# ---------------------------------------------------------------------------

def merge_annotations(model, annotations):
    """Merge manual annotations from annotations.yaml into the derived model.

    Annotations keyed by object id can:
    - Add or override fields on the matching object
    - Set exclude: true to remove the object entirely
    """
    if not annotations:
        return model

    def _merge_section(items, overrides, id_field="id"):
        merged = []
        for item in items:
            oid = item.get(id_field)
            override = overrides.get(oid, {})
            if override.get("exclude"):
                continue
            merged.append({**item, **{k: v for k, v in override.items() if k != "exclude"}})
        return merged

    ann_flows = annotations.get("flows", {})
    ann_processes = annotations.get("processes", {})
    ann_stores = annotations.get("data_stores", {})

    model["data_flows"] = _merge_section(model.get("data_flows", []), ann_flows)
    model["processes"] = _merge_section(model.get("processes", []), ann_processes)
    model["data_stores"] = _merge_section(model.get("data_stores", []), ann_stores)
    return model


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_threat_model(env=None, stacks_dir=None, annotations_path=None):
    """Build the full threat model dict from all sources."""
    stacks = load_all_stacks(stacks_dir)
    edge_yamls = load_edge_yamls(stacks_dir)
    composes = load_docker_composes(stacks_dir)
    network_intent = load_network_intent(env)
    annotations = load_annotations(annotations_path)

    processes = derive_processes(stacks)

    flows = []
    flows.extend(_EXTERNAL_FLOWS)
    flows.extend(derive_registry_flows(stacks, processes))
    flows.extend(derive_apt_flows(stacks, processes))
    flows.extend(derive_socket_proxy_flows(stacks, processes))
    flows.extend(derive_edge_flows(stacks, edge_yamls, processes))
    flows.extend(derive_monitoring_flows(stacks, composes, processes))
    flows.extend(derive_zone_policy_flows(network_intent, processes))

    model = {
        "metadata": {
            "name": "Proxmox Homelab",
            "version": "auto",
            "description": (
                "Auto-derived threat model. Flows inferred from stack.yaml, edge.yaml, "
                "docker-compose.yml, and network intent policies. "
                "Manual annotations from docs/threat-model/annotations.yaml."
            ),
            "methodology": "STRIDE",
        },
        "trust_boundaries": TRUST_BOUNDARIES,
        "external_entities": EXTERNAL_ENTITIES,
        "processes": processes,
        "data_stores": DATA_STORES,
        "data_flows": flows,
    }

    return merge_annotations(model, annotations)


# ---------------------------------------------------------------------------
# NetBox config context integration
# ---------------------------------------------------------------------------

NB_CONFIG_CONTEXTS = "/extras/config-contexts/"
THREAT_MODEL_CONTEXT_NAME = "threat-model"


def populate_threat_model(nb, site, managed_tags, env=None):
    """Derive and push the threat model to NetBox as a config context.

    Creates or updates a single config context named 'threat-model' scoped
    to the Homelab site. Owned by the managed-by-proxmox-homelab tag.
    """
    print("\n=== Threat Model ===")
    try:
        model = build_threat_model(env=env)
    except Exception as exc:
        print(f"  warn: threat model derivation failed: {exc}")
        return

    flow_count = len(model.get("data_flows", []))
    process_count = len(model.get("processes", []))
    print(f"  derived {process_count} processes, {flow_count} data flows")

    nb.ensure(
        NB_CONFIG_CONTEXTS,
        {"name": THREAT_MODEL_CONTEXT_NAME},
        {
            "name": THREAT_MODEL_CONTEXT_NAME,
            "weight": 1000,
            "is_active": True,
            "description": (
                "Auto-derived inter-service data flow model for threat analysis. "
                "Generated by populate.py from stack.yaml, edge.yaml, and network intent."
            ),
            "data": model,
            "sites": [site["id"]],
            "tags": managed_tags,
        },
        managed_tag_slug="managed-by-proxmox-homelab",
        allow_unmanaged_patch=False,
    )
    print(f"  threat model config context '{THREAT_MODEL_CONTEXT_NAME}' upserted")


# ---------------------------------------------------------------------------
# Standalone export
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Derive homelab threat model from config files")
    parser.add_argument("--env", default=None, help="Network environment (pve, pve-test, pve-test-vm)")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of YAML")
    args = parser.parse_args()

    model = build_threat_model(env=args.env)

    if args.json:
        print(json.dumps(model, indent=2))
    else:
        print(yaml.dump(model, default_flow_style=False, sort_keys=False, allow_unicode=True))
