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
import json
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

# Managed hosts are left out of the Full-and-fast target only (see
# full_vuln_excludes below); Discovery still covers the whole zone.
ZONES = [
    {"key": "build_seg", "cidr": "192.168.10.0/24"},
    {"key": "mgmt_seg", "cidr": "192.168.20.0/24"},
    {"key": "edge_seg", "cidr": "192.168.30.0/24"},
    {"key": "infra_seg", "cidr": "192.168.40.0/24"},
    {"key": "ai_seg", "cidr": "192.168.50.0/24"},
    {"key": "game_seg", "cidr": "192.168.60.0/24"},
    {"key": "pentest_seg", "cidr": "192.168.70.0/24"},
    {"key": "media_seg", "cidr": "192.168.80.0/24"},
    {"key": "cse_seg", "cidr": "192.168.100.0/24"},
    {"key": "connector_seg", "cidr": "192.168.110.0/24"},
    {"key": "apps_seg", "cidr": "192.168.120.0/24"},
    {"key": "lan", "cidr": "192.168.1.0/24"},
]

# Permanent red-team / test fixtures -- excluded from every routine target
# (both tiers) in their zone; their findings are known/meaningless noise
# and they stay reachable via the on-demand gvm-bridge/PentAGI path only.
FIXTURE_EXCLUDE = {
    "lan": ["192.168.1.113", "192.168.1.55"],  # Metasploitable2, harness-target
    # harness-target-pve, pentagi-upstream-control, cse-kali
    "pentest_seg": ["192.168.70.12", "192.168.70.13", "192.168.70.210"],
}

# The full-vuln tasks scan UNMANAGED addresses only (docs/gvm-scan-redesign/):
# a managed host already has a weekly credentialed task, which runs the same
# network checks plus the local ones, so rescanning it here found nothing extra
# (compared 2026-10-14). The managed list comes from
# gvm_fleet_targets_generate.py --managed-hosts-out, copied to the scanner host
# by the playbook, so there are no hand-maintained lists.
MANAGED_HOSTS_FILE = os.environ.get("GVM_MANAGED_HOSTS", "/tmp/managed-hosts.json")

# Covered by a credentialed task that is not part of the managed list.
CREDENTIALED_ELSEWHERE = {
    "lan": ["192.168.1.1"],  # MikroTik: "Credentialed scan: MikroTik router"
}

# On the managed list but with no working credentialed scan yet, so they must
# stay in the unauthenticated scan or nothing scans them. Remove an entry once
# its credentialed scan is verified.
STILL_UNCOVERED = {
    "192.168.1.104",  # this workstation: sshd is off, so gvm-scan cannot log in
}

# Devices that stop answering under scanning, left out of BOTH the discovery and
# the full-vuln targets. Network gear is also the original "discovery-only" tier
# (docs/greenbone-stack/network-scan-rollout-plan.md), and Omada already monitors it.
FRAGILE_HOSTS = {
    # 5-port switch. The first full-vuln scan of the /24 (2026-10-14 baseline) was the
    # first time it was probed hard; it dropped off the network mid-scan and was still
    # offline in Omada an hour after the scan stopped.
    "lan": ["192.168.1.253"],
}

# Concurrent hosts for the unauthenticated full-vuln tasks. They used to run 20
# at once (GVM's default for a new task), which drove the 4-core scanner to a
# load of 33 on 2026-10-14.
FULL_VULN_MAX_HOSTS = 6

# Discovery tasks had no max_hosts either, so GVM ran 20 hosts at once. mgmt_seg
# discovery (2026-10-15 23:00) ran all 10 of its hosts together, including OpenBao,
# and pinned Redis at its 6 GB cap for ten minutes before the task was Interrupted.
# mgmt_seg keeps the credentialed task's limit of 2 (ZONE_MAX_HOSTS in
# setup_credentials.py); its web UIs are what fill Redis.
DISCOVERY_MAX_HOSTS = 6
DISCOVERY_ZONE_MAX_HOSTS = {"mgmt_seg": 2}

# Left out of discovery only. 192.168.20.16 (openbao): its UI on 8200 answers every
# /ui/<anything> with a ~1 MB page, which the web probes cache in Redis (see
# SPLIT_HOSTS in setup_credentials.py). It is a managed host with its own credentialed
# task, which excludes port 8200; discovery shares the zone port list, so exclude the host.
DISCOVERY_EXCLUDE = {
    "mgmt_seg": ["192.168.20.16"],
}


def load_managed_hosts(path=MANAGED_HOSTS_FILE):
    """{zone: [ip, ...]}. Raises if the file is missing, so a broken deploy
    cannot silently turn the unmanaged scans back into whole-zone scans."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def full_vuln_excludes(zone_key, managed, fixtures):
    """Addresses the unauthenticated full-vuln task leaves out for a zone."""
    covered = set(managed.get(zone_key, [])) - STILL_UNCOVERED
    covered |= set(CREDENTIALED_ELSEWHERE.get(zone_key, []))
    return sorted(covered | set(fixtures) | set(FRAGILE_HOSTS.get(zone_key, [])))


def discovery_excludes(zone_key, fixtures):
    """Addresses the discovery task leaves out for a zone."""
    return sorted(set(fixtures) | set(FRAGILE_HOSTS.get(zone_key, [])) | set(DISCOVERY_EXCLUDE.get(zone_key, [])))


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


def ensure_target_and_task(gmp, name, cidr, exclude_hosts, config_id, scanner_id, port_list_id, max_hosts=None):
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

    prefs = {"preferences": {"max_hosts": str(max_hosts)}} if max_hosts is not None else {}
    if task_id:
        print(f"task {name!r} already exists ({task_id}), skipping")
        if max_hosts is not None:
            task = gmp.get_task(task_id).find("task")
            current = {p.findtext("scanner_name"): p.findtext("value") for p in task.findall("preferences/preference")}
            if current.get("max_hosts") != str(max_hosts) and task.findtext("status") not in ACTIVE_TASK_STATUSES:
                gmp.modify_task(task_id, **prefs)
                print(f"set max_hosts={max_hosts} on task {name!r}")
    else:
        response = gmp.create_task(name=name, config_id=config_id, target_id=target_id, scanner_id=scanner_id, **prefs)
        print(f"created task {name!r} ({response.get('id')})")


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        discovery_config_id = resolve_id(gmp, gmp.get_scan_configs, DISCOVERY_CONFIG_NAME, "config")
        full_config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        managed = load_managed_hosts()
        for zone in ZONES:
            key, cidr = zone["key"], zone["cidr"]
            fixtures = FIXTURE_EXCLUDE.get(key, [])

            ensure_target_and_task(
                gmp, f"LAN scan: {key} discovery", cidr, discovery_excludes(key, fixtures),
                discovery_config_id, scanner_id, port_list_id,
                max_hosts=DISCOVERY_ZONE_MAX_HOSTS.get(key, DISCOVERY_MAX_HOSTS),
            )
            ensure_target_and_task(
                gmp, f"LAN scan: {key} full-vuln", cidr, full_vuln_excludes(key, managed, fixtures),
                full_config_id, scanner_id, port_list_id, max_hosts=FULL_VULN_MAX_HOSTS,
            )

    print("done")


if __name__ == "__main__":
    sys.exit(main())
