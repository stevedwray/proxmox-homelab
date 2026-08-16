#!/usr/bin/env python3
"""One-shot, idempotent setup for the LAN/VLAN discovery + vulnerability
scan program -- docs/greenbone-stack/network-scan-rollout-plan.md, Phase 2.

Run inside the greenbone-stack compose's throwaway gvm-tools container
(same pattern as deploy-greenbone-stack.yml's other GMP calls, just Python
instead of gvm-cli/XML -- this needed structured idempotency checks
(get_targets/get_tasks by exact name) that were simpler to write directly
against python-gvm than by regex-scraping gvm-cli's XML stdout):

    docker compose run --rm \
      -v <this file>:/tmp/setup_scan_program.py:ro \
      -e GVM_USERNAME=admin -e GVM_PASSWORD=... \
      gvm-tools python3 /tmp/setup_scan_program.py

python-gvm call shapes (create_target/create_task, alive_test as a plain
string, get_scan_configs/get_scanners resolved by name filter rather than
a hardcoded UUID) all mirror gvm-bridge/app.py's already-live-proven usage
-- see that file's scan_start()/_resolve_ids() for the precedent.

Creates two GVM Targets and two Tasks per zone/LAN (one Discovery, one
Full-and-fast pair) -- 14 Targets + 14 Tasks total. Does NOT attach a
Schedule (Phase 4, not yet done); Tasks are created unscheduled and can be
started manually (GSA, or `gmp.start_task`) until scheduling lands. Safe
to re-run: every create is preceded by an exact-name lookup and skipped if
already present.
"""
import os
import sys

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]

DISCOVERY_CONFIG_NAME = "Discovery"
FULL_CONFIG_NAME = "Full and fast"
SCANNER_NAME = "OpenVAS Default"

# GVM's own standard pairing for "Full and fast" -- confirmed live
# 2026-08-16: create_target has no implicit port default (GmvResponseError
# 400 "One of PORT_LIST and PORT_RANGE are required" if omitted, contrary
# to this file's original draft assumption). Resolved by name, same
# convention as the scan config/scanner, not hardcoded.
PORT_LIST_NAME = "All TCP and Nmap top 100 UDP"

# GVM's standard combined default -- deliberately NOT gvm-bridge's
# hardcoded "Consider Alive" (that was justified specifically for
# pentest_seg's own deliberately ICMP-firewalled lab targets; every host
# here is normal LAN/VLAN infrastructure that should respond to ICMP/ARP
# like anything else). Revisit per-zone only if a specific zone is
# observed to have real false-negative host-alive results.
#
# Exact string confirmed live 2026-08-16 against python-gvm's AliveTest
# enum (gvm.protocols.gmp.requests.v224._targets.AliveTest) -- the
# original draft guessed "ICMP, TCP-ACK Service Ping, ARP Ping" and it
# does not match any enum value (raises InvalidArgument). The real
# combined-default member is "ICMP, TCP-ACK Service & ARP Ping" (comma +
# ampersand, "Service" not "Service Ping" in the middle clause).
ALIVE_TESTS = "ICMP, TCP-ACK Service & ARP Ping"

# Tier A hosts (docs/greenbone-stack/network-scan-rollout-plan.md Phase 2)
# are excluded from the Full-and-fast target only -- still covered by
# Discovery. Promoting one to full scanning later means removing it from
# this list and re-running this script (idempotency check is by target
# name, not content, so an already-existing Full-and-fast target won't be
# auto-updated -- see "Known gap" at the bottom of this file).
ZONES = [
    {"key": "build_seg", "cidr": "192.168.10.0/24", "tier_a_exclude": []},
    {
        "key": "mgmt_seg",
        "cidr": "192.168.20.0/24",
        "tier_a_exclude": ["192.168.20.10", "192.168.20.11"],  # Authentik, step-ca
    },
    {"key": "edge_seg", "cidr": "192.168.30.0/24", "tier_a_exclude": ["192.168.30.10"]},  # Traefik
    {"key": "infra_seg", "cidr": "192.168.40.0/24", "tier_a_exclude": ["192.168.40.10"]},  # Harbor
    {"key": "ai_seg", "cidr": "192.168.50.0/24", "tier_a_exclude": []},
    {"key": "game_seg", "cidr": "192.168.60.0/24", "tier_a_exclude": []},
    {
        "key": "lan",
        "cidr": "192.168.1.0/24",
        # MikroTik, pve, NAS, pve-test-vm
        "tier_a_exclude": ["192.168.1.1", "192.168.1.2", "192.168.1.3", "192.168.1.41"],
    },
]

# Metasploitable2, harness-target -- deliberately excluded from every
# routine target (both tiers), not just Full-and-fast. Both are permanent
# red-team fixtures on the flat LAN; their findings are known/meaningless
# noise for a "catch new vulnerabilities" mission, and they stay reachable
# via the existing on-demand gvm-bridge/PentAGI path only.
REDTEAM_EXCLUDE = ["192.168.1.113", "192.168.1.55"]


def resolve_id(gmp, getter, name, tag):
    response = getter(filter_string=f'name="{name}"')
    el = response.find(tag)
    if el is None:
        raise RuntimeError(f"{tag} {name!r} not found on this gvmd")
    return el.get("id")


def find_by_name(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    el = response.find(tag)
    return el.get("id") if el is not None else None


def ensure_target(gmp, name, cidr, exclude_hosts, port_list_id):
    """exclude_hosts is a list[str] of individual addresses, per
    python-gvm's Targets.create_target signature -- a pre-joined comma
    string here fails live with GvmResponseError 400 "Error in host
    specification" (confirmed 2026-08-16), the same "hosts wants a list,
    not a string" shape as the hosts=[cidr] argument below.
    """
    existing = find_by_name(gmp, gmp.get_targets, "target", name)
    if existing:
        print(f"target {name!r} already exists ({existing}), skipping")
        return existing
    kwargs = {"exclude_hosts": exclude_hosts} if exclude_hosts else {}
    response = gmp.create_target(
        name=name,
        hosts=[cidr],
        alive_test=ALIVE_TESTS,
        port_list_id=port_list_id,
        **kwargs,
    )
    target_id = response.get("id")
    print(f"created target {name!r} ({target_id})")
    return target_id


def ensure_task(gmp, name, config_id, target_id, scanner_id):
    existing = find_by_name(gmp, gmp.get_tasks, "task", name)
    if existing:
        print(f"task {name!r} already exists ({existing}), skipping")
        return existing
    response = gmp.create_task(name=name, config_id=config_id, target_id=target_id, scanner_id=scanner_id)
    task_id = response.get("id")
    print(f"created task {name!r} ({task_id})")
    return task_id


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        discovery_config_id = resolve_id(gmp, gmp.get_scan_configs, DISCOVERY_CONFIG_NAME, "config")
        full_config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        for zone in ZONES:
            key, cidr, tier_a_exclude = zone["key"], zone["cidr"], zone["tier_a_exclude"]

            discovery_exclude = list(REDTEAM_EXCLUDE) if key == "lan" else []
            discovery_target_id = ensure_target(
                gmp, f"LAN scan: {key} discovery", cidr, discovery_exclude, port_list_id
            )
            ensure_task(gmp, f"LAN scan: {key} discovery", discovery_config_id, discovery_target_id, scanner_id)

            full_exclude = list(tier_a_exclude)
            if key == "lan":
                full_exclude += REDTEAM_EXCLUDE
            full_target_id = ensure_target(
                gmp, f"LAN scan: {key} full-vuln", cidr, full_exclude, port_list_id
            )
            ensure_task(gmp, f"LAN scan: {key} full-vuln", full_config_id, full_target_id, scanner_id)

    print("done")


# Known gap: this script is create-only, not a full reconciler -- if a
# Target already exists, its exclude_hosts/alive_test/hosts are never
# updated to match this file even if this file's own ZONES table changes
# later (e.g. a Tier A host promoted off the exclude list). Re-running
# after such a change requires manually deleting the stale Target (and its
# Task) first, or extending this script with a real diff/update path --
# not built, since Phase 2's first run has nothing to reconcile against.
if __name__ == "__main__":
    sys.exit(main())
