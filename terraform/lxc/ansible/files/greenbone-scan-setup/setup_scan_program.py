#!/usr/bin/env python3
"""Idempotent setup for the LAN/VLAN discovery + vulnerability scan program
-- docs/greenbone-stack/network-scan-rollout-plan.md Phase 2, extended by
docs/gvm-coverage-cleanup/plan.md (2026-10-11: added pentest_seg,
media_seg, cse_seg, connector_seg and apps_seg; dropped the NAS and the
retired pve-test-vm from the lan full-vuln exclusions).

Run inside the greenbone-stack compose's throwaway gvm-tools container:

    docker compose run --rm \
      -v <this file>:/tmp/setup_scan_program.py:ro \
      -e GVM_USERNAME=admin -e GVM_PASSWORD=... \
      gvm-tools python3 /tmp/setup_scan_program.py

Creates one Discovery and one Full-and-fast Target+Task per zone/LAN.
Discovery Tasks stay unscheduled; full-vuln Tasks get their weekly
Schedule from setup_schedules.py (run after this file by the playbook).

Reconciles, not create-only: if an existing Target's hosts/exclude_hosts
differ from this file, its Task and Target are deleted (ultimate) and
recreated -- gvmd refuses to change hosts on a Target in use by a Task.
A Task that is currently running is left alone with a WARN and picked up
on the next run. setup_schedules.py re-attaches the weekly Schedule to a
recreated full-vuln Task by name.
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

# GVM's own standard pairing for "Full and fast"; create_target has no
# implicit port default (confirmed live 2026-08-16).
PORT_LIST_NAME = "All TCP and Nmap top 100 UDP"

# GVM's standard combined default. Exact enum string confirmed live
# 2026-08-16 against python-gvm's AliveTest enum.
ALIVE_TESTS = "ICMP, TCP-ACK Service & ARP Ping"

ACTIVE_TASK_STATUSES = {"Running", "Requested", "Queued", "Stop Requested", "Delete Requested"}

# Tier A hosts are excluded from the Full-and-fast target only -- still
# covered by Discovery, and every one of them has its own daily
# credentialed scan (setup_credentials.py).
ZONES = [
    {"key": "build_seg", "cidr": "192.168.10.0/24", "tier_a_exclude": []},
    {
        "key": "mgmt_seg",
        "cidr": "192.168.20.0/24",
        # Authentik, step-ca, openbao. openbao's UI (8200) answers any /ui/ path
        # with a ~1MB page and the web-app probes cache each reply in Redis; it
        # is scanned by "Credentialed scan: mgmt_seg (openbao)" without port 8200.
        "tier_a_exclude": ["192.168.20.10", "192.168.20.11", "192.168.20.16"],
    },
    {"key": "edge_seg", "cidr": "192.168.30.0/24", "tier_a_exclude": ["192.168.30.10"]},  # Traefik
    {"key": "infra_seg", "cidr": "192.168.40.0/24", "tier_a_exclude": ["192.168.40.10"]},  # Harbor
    {"key": "ai_seg", "cidr": "192.168.50.0/24", "tier_a_exclude": []},
    {"key": "game_seg", "cidr": "192.168.60.0/24", "tier_a_exclude": []},
    {"key": "pentest_seg", "cidr": "192.168.70.0/24", "tier_a_exclude": []},
    {"key": "media_seg", "cidr": "192.168.80.0/24", "tier_a_exclude": []},
    {"key": "cse_seg", "cidr": "192.168.100.0/24", "tier_a_exclude": []},
    {"key": "connector_seg", "cidr": "192.168.110.0/24", "tier_a_exclude": []},
    {"key": "apps_seg", "cidr": "192.168.120.0/24", "tier_a_exclude": []},
    {
        "key": "lan",
        "cidr": "192.168.1.0/24",
        "tier_a_exclude": ["192.168.1.1", "192.168.1.2"],  # MikroTik, pve
    },
]

# Permanent red-team / test fixtures -- excluded from every routine target
# (both tiers) in their zone; their findings are known/meaningless noise
# and they stay reachable via the on-demand gvm-bridge/PentAGI path only.
FIXTURE_EXCLUDE = {
    "lan": ["192.168.1.113", "192.168.1.55"],  # Metasploitable2, harness-target
    # harness-target-pve, pentagi-upstream-control, cse-kali
    "pentest_seg": ["192.168.70.12", "192.168.70.13", "192.168.70.210"],
}


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


def _host_set(text):
    return {h.strip() for h in (text or "").split(",") if h.strip()}


def target_matches(gmp, target_id, cidr, exclude_hosts):
    target = gmp.get_target(target_id)
    return (
        _host_set(target.findtext("target/hosts")) == {cidr}
        and _host_set(target.findtext("target/exclude_hosts")) == set(exclude_hosts)
    )


def ensure_target_and_task(gmp, name, cidr, exclude_hosts, config_id, scanner_id, port_list_id):
    """exclude_hosts is a list[str] of individual addresses -- a pre-joined
    comma string fails live with GvmResponseError 400 "Error in host
    specification" (confirmed 2026-08-16)."""
    target_id = find_by_name(gmp, gmp.get_targets, "target", name)
    task_id = find_by_name(gmp, gmp.get_tasks, "task", name)

    if target_id and not target_matches(gmp, target_id, cidr, exclude_hosts):
        if task_id:
            status = gmp.get_task(task_id).findtext("task/status", default="unknown")
            if status in ACTIVE_TASK_STATUSES:
                print(f"WARN: task {name!r} is {status}; its target is stale, leaving it alone this run")
                return
            gmp.delete_task(task_id, ultimate=True)
            print(f"deleted task {name!r} ({task_id}) -- target hosts/excludes changed")
            task_id = None
        gmp.delete_target(target_id, ultimate=True)
        print(f"deleted target {name!r} ({target_id}) -- hosts/excludes changed")
        target_id = None

    if target_id:
        print(f"target {name!r} already exists ({target_id}), up to date")
    else:
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

    if task_id:
        print(f"task {name!r} already exists ({task_id}), skipping")
    else:
        response = gmp.create_task(name=name, config_id=config_id, target_id=target_id, scanner_id=scanner_id)
        print(f"created task {name!r} ({response.get('id')})")


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        discovery_config_id = resolve_id(gmp, gmp.get_scan_configs, DISCOVERY_CONFIG_NAME, "config")
        full_config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        for zone in ZONES:
            key, cidr = zone["key"], zone["cidr"]
            fixtures = FIXTURE_EXCLUDE.get(key, [])

            ensure_target_and_task(
                gmp, f"LAN scan: {key} discovery", cidr, list(fixtures),
                discovery_config_id, scanner_id, port_list_id,
            )
            ensure_target_and_task(
                gmp, f"LAN scan: {key} full-vuln", cidr, list(zone["tier_a_exclude"]) + list(fixtures),
                full_config_id, scanner_id, port_list_id,
            )

    print("done")


if __name__ == "__main__":
    sys.exit(main())
