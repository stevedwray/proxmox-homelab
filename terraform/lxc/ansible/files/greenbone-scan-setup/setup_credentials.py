#!/usr/bin/env python3
"""Reconcile Greenbone's credentialed scan objects
(docs/gvm-coverage-cleanup/plan.md; originally
docs/lxc-scan-and-monitoring-rollout/plan.md gvm-07/gvm-08).

Two kinds of credentialed target:

1. Fleet hosts (every LXC, Proxmox node, framework, the workstation and the
   Raspberry Pis): one unique "gvm-scan" SSH keypair per host, read from
   OpenBao (services/greenbone/scan-hosts/<name>) by
   scripts/gvm_fleet_targets_generate.py and delivered as a single
   bind-mounted directory (GVM_FLEET_DIR, default /tmp/fleet): one
   targets.json manifest (list of {"name", "host", "zone"} -- no secret
   content) plus one "<name>.key" per host. Each host gets its own "usk"
   login credential, Target and Task. There is NO elevate-privileges
   credential: GVM's elevate feature is su-based, not sudo-based --
   confirmed live 2026-10-11 from target sshd logs, every fleet scan ran
   `su -l gvm-scan` (switching to itself) and every one of ~170 scheduled
   runs since 2026-09-30 reported "SSH Login Failed For Authenticated
   Checks" with zero Local Security Check results. Operator decision
   2026-10-11: scan as the unprivileged gvm-scan account (Debian/Ubuntu
   package checks don't need root).

2. The MikroTik router: its own RouterOS "gvm-scan" user and key
   (GREENBONE_MIKROTIK_KEY_PATH), created by
   ansible/00-initial-setup/mikrotik-gvm-scan-user.yml.

Reconciliation, not create-only: every fleet Target carries a
"managed-fp:<hash>" marker in its comment, a hash of (host, private key,
port list, alive test, RECONCILE_VERSION). If the marker is missing or
differs -- a rotated key in OpenBao, a changed IP, a changed scan
setting -- the host's Task, Target and credentials are deleted and
recreated. Delete-and-recreate rather than modify_target because gvmd
refuses to change hosts/credentials on a Target that is in use by a Task.
A Task that is currently running is left alone with a WARN and picked up
on the next run. Deleting a Task deletes its reports in GVM; findings
already ingested into OpenSearch (gvm-findings) are unaffected.

Credentialed Targets are explicit single-host lists so a credential can
never be applied accidentally to an arbitrary host discovered on a
subnet.

VLAN-organized scheduling: a GVM Target can only carry one
ssh_credential_id for every host it contains, so each host keeps its own
Target/Task and gets its zone's daily Schedule (ZONE_SCHEDULE_TIMES) plus
a zone Tag (zone:<name>) for GSA-side grouping and filtering.
"""
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

# Daily, staggered ~45min apart overnight in the operator's own local time
# (Pacific/Auckland, a real IANA zone so NZ DST transitions resolve
# correctly -- see the 2026-09-30 UTC-vs-NZT fix in git history).
ZONE_SCHEDULE_TIMES = {
    "cse_seg": "23:30",
    "lan": "00:15",
    "mgmt_seg": "01:00",
    "infra_seg": "01:45",
    "ai_seg": "02:30",
    "media_seg": "03:15",
    "game_seg": "04:00",
    "edge_seg": "04:45",
    "pentest_seg": "05:30",
    "connector_seg": "06:15",
    "build_seg": "07:00",
    "apps_seg": "07:45",
}
SCHEDULE_TIMEZONE = "Pacific/Auckland"

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]
START_TASK_NAME = os.environ.get("GREENBONE_START_TASK_NAME", "")
STATUS_TASK_NAME = os.environ.get("GREENBONE_STATUS_TASK_NAME", "")

GVM_FLEET_DIR = os.environ.get("GVM_FLEET_DIR", "/tmp/fleet")  # nosonar: python:S5443 -- container-internal /tmp inside an isolated `docker compose run --rm` gvm-tools container, not a shared host path
GVM_FLEET_LOGIN = "gvm-scan"

FULL_CONFIG_NAME = "Full and fast"
SCANNER_NAME = "OpenVAS Default"
PORT_LIST_NAME = "All TCP and Nmap top 100 UDP"
ALIVE_TESTS = "ICMP, TCP-ACK Service & ARP Ping"

# Bump to force every fleet host's GVM objects to be rebuilt on the next
# run, e.g. after changing how targets are built. "2" = no elevate
# credential (2026-10-11).
RECONCILE_VERSION = "2"
FP_MARKER = "managed-fp:"
ACTIVE_TASK_STATUSES = {"Running", "Requested", "Queued", "Stop Requested", "Delete Requested"}

MIKROTIK_CREDENTIAL = {
    "name": "MikroTik gvm-scan SSH key",
    "login": "gvm-scan",
    "key_path": os.environ["GREENBONE_MIKROTIK_KEY_PATH"],
}
MIKROTIK_TARGET = {
    "name": "Credentialed scan: MikroTik router",
    "hosts": ["192.168.1.1"],
    "zone": "lan",
}

# Retired 2026-10-11 (docs/gvm-coverage-cleanup/plan.md): the hand-picked
# root-key targets (stale pve-test-vm "+100" IPs, a destroyed dns-stack),
# the pve/workstation/Pi targets now covered by per-host gvm-scan fleet
# targets, and the credentials only they used. Deleted (ultimate) if
# present; a no-op once gone.
LEGACY_TASKS_AND_TARGETS = [
    "Credentialed scan: managed Debian services",
    "Credentialed scan: pve hypervisor",
    "Credentialed scan: Linux workstation",
    "Credentialed scan: Raspberry Pis",
]
LEGACY_CREDENTIALS = [
    "Lab root SSH key (Steve)",
    "Workstation openvas SSH key",
    "Raspberry Pi ansible SSH key (Steve)",
]


def find_by_name(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    element = response.find(tag)
    return element.get("id") if element is not None else None


def resolve_id(gmp, getter, name, tag):
    object_id = find_by_name(gmp, getter, tag, name)
    if not object_id:
        raise RuntimeError(f"{tag} {name!r} not found on this gvmd")
    return object_id


def fingerprint(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def task_status(gmp, task_id):
    return gmp.get_task(task_id).findtext("task/status", default="unknown")


def delete_if_present(gmp, kind, name):
    """kind is "task", "target" or "credential". Returns False only when a
    task exists but is active (running/queued) and so was left alone."""
    getter = {"task": gmp.get_tasks, "target": gmp.get_targets, "credential": gmp.get_credentials}[kind]
    deleter = {"task": gmp.delete_task, "target": gmp.delete_target, "credential": gmp.delete_credential}[kind]
    object_id = find_by_name(gmp, getter, kind, name)
    if not object_id:
        return True
    if kind == "task":
        status = task_status(gmp, object_id)
        if status in ACTIVE_TASK_STATUSES:
            print(f"WARN: task {name!r} is {status}, leaving it alone this run")
            return False
    deleter(object_id, ultimate=True)
    print(f"deleted {kind} {name!r} ({object_id})")
    return True


def cleanup_legacy(gmp):
    for name in LEGACY_TASKS_AND_TARGETS:
        if delete_if_present(gmp, "task", name):
            delete_if_present(gmp, "target", name)
    for name in LEGACY_CREDENTIALS:
        delete_if_present(gmp, "credential", name)


def ensure_credential(gmp, name, login, key_path):
    existing = find_by_name(gmp, gmp.get_credentials, "credential", name)
    if existing:
        print(f"credential {name!r} already exists ({existing}), skipping")
        return existing
    response = gmp.create_credential(
        name=name,
        credential_type="usk",
        login=login,
        private_key=Path(key_path).read_text(encoding="utf-8"),
        comment="Managed by setup_credentials.py; do not edit manually in GSA.",
    )
    credential_id = response.get("id")
    print(f"created credential {name!r} ({credential_id})")
    return credential_id


def ensure_target(gmp, name, hosts, credential_id, port_list_id, comment):
    existing = find_by_name(gmp, gmp.get_targets, "target", name)
    if existing:
        print(f"target {name!r} already exists ({existing}), skipping")
        return existing
    response = gmp.create_target(
        name=name,
        hosts=hosts,
        ssh_credential_id=credential_id,
        alive_test=ALIVE_TESTS,
        port_list_id=port_list_id,
        comment=comment,
    )
    target_id = response.get("id")
    print(f"created target {name!r} ({target_id})")
    return target_id


def ensure_task(gmp, name, config_id, target_id, scanner_id, schedule_id):
    existing = find_by_name(gmp, gmp.get_tasks, "task", name)
    if existing:
        gmp.modify_task(existing, schedule_id=schedule_id)
        print(f"task {name!r} already exists ({existing}), ensured schedule {schedule_id!r}")
        return existing
    response = gmp.create_task(
        name=name,
        config_id=config_id,
        target_id=target_id,
        scanner_id=scanner_id,
        schedule_id=schedule_id,
        comment="Managed credentialed task; daily per-zone schedule.",
    )
    task_id = response.get("id")
    print(f"created task {name!r} ({task_id}) scheduled via {schedule_id!r}")
    return task_id


def ensure_schedule(gmp, zone):
    """One recurring daily GVM Schedule per network zone. Re-applies
    icalendar/timezone on every run so a corrected ZONE_SCHEDULE_TIMES
    value lands on already-created schedules too. Hand-builds the
    iCalendar text rather than depending on the `icalendar` package."""
    hhmm = ZONE_SCHEDULE_TIMES.get(zone)
    if hhmm is None:
        raise RuntimeError(
            f"no schedule start time configured for zone {zone!r} -- add it to "
            f"ZONE_SCHEDULE_TIMES in this file before this zone can be scheduled"
        )
    name = f"Daily fleet scan: {zone}"
    hour, minute = hhmm.split(":")
    now = datetime.datetime.now(datetime.timezone.utc)
    icalendar = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//proxmox-homelab//gvm-fleet-schedule//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:gvm-fleet-schedule-{zone}@proxmox-homelab\r\n"
        f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTSTART:{now.strftime('%Y%m%d')}T{hour}{minute}00\r\n"
        "RRULE:FREQ=DAILY\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    comment = f"Credentialed scans for zone {zone!r}, daily at {hhmm} {SCHEDULE_TIMEZONE}."
    existing = find_by_name(gmp, gmp.get_schedules, "schedule", name)
    if existing:
        gmp.modify_schedule(existing, icalendar=icalendar, timezone=SCHEDULE_TIMEZONE, comment=comment)
        print(f"schedule {name!r} ({existing}) updated to daily at {hhmm} {SCHEDULE_TIMEZONE}")
        return existing
    response = gmp.create_schedule(name=name, icalendar=icalendar, timezone=SCHEDULE_TIMEZONE, comment=comment)
    schedule_id = response.get("id")
    print(f"created schedule {name!r} ({schedule_id}) daily at {hhmm} {SCHEDULE_TIMEZONE}")
    return schedule_id


def ensure_zone_tag(gmp, zone, task_ids):
    if not task_ids:
        return None
    name = f"zone:{zone}"
    existing = find_by_name(gmp, gmp.get_tags, "tag", name)
    if existing:
        gmp.modify_tag(existing, resource_action="add", resource_type="task", resource_ids=task_ids)
        print(f"tag {name!r} ({existing}) -- ensured {len(task_ids)} task(s) attached")
        return existing
    response = gmp.create_tag(
        name=name,
        resource_type="task",
        resource_ids=task_ids,
        comment=f"Credentialed scan hosts in network zone {zone!r}.",
    )
    tag_id = response.get("id")
    print(f"created tag {name!r} ({tag_id}) attached to {len(task_ids)} task(s)")
    return tag_id


def load_fleet_targets(fleet_dir):
    """Returns a list of {"name", "host", "zone", "key_path"} dicts, or []
    if GVM_FLEET_DIR has no targets.json -- degrades gracefully rather
    than crashing the whole run over an incomplete rollout."""
    manifest_path = Path(fleet_dir) / "targets.json"
    if not manifest_path.exists():
        print(f"no fleet targets manifest at {manifest_path}, skipping fleet targets")
        return []
    fleet = []
    for entry in json.loads(manifest_path.read_text(encoding="utf-8")):
        key_path = Path(fleet_dir) / f"{entry['name']}.key"
        if not key_path.exists():
            print(f"WARN: fleet target {entry['name']!r} missing key file, skipping")
            continue
        if not entry.get("zone"):
            print(f"WARN: fleet target {entry['name']!r} has no zone, skipping")
            continue
        fleet.append({**entry, "key_path": str(key_path)})
    return fleet


def reconcile_fleet_host(gmp, fleet_target, config_id, scanner_id, port_list_id, schedule_id):
    """Returns the host's task id, or None if it was skipped this run."""
    name = fleet_target["name"]
    object_name = f"Credentialed scan: fleet/{name}"
    login_credential_name = f"fleet-{name}-login"
    legacy_sudo_credential_name = f"fleet-{name}-sudo"
    private_key = Path(fleet_target["key_path"]).read_text(encoding="utf-8")
    fp = fingerprint(fleet_target["host"], private_key, PORT_LIST_NAME, ALIVE_TESTS, RECONCILE_VERSION)
    marker = f"{FP_MARKER}{fp}"

    target_id = find_by_name(gmp, gmp.get_targets, "target", object_name)
    current_comment = ""
    if target_id:
        current_comment = gmp.get_target(target_id).findtext("target/comment", default="")
    if target_id and marker in current_comment:
        print(f"fleet host {name!r} up to date ({marker})")
    else:
        reason = "new" if not target_id else "changed key/IP/settings"
        print(f"fleet host {name!r}: rebuilding GVM objects ({reason})")
        if not delete_if_present(gmp, "task", object_name):
            return None
        delete_if_present(gmp, "target", object_name)
        delete_if_present(gmp, "credential", login_credential_name)
        delete_if_present(gmp, "credential", legacy_sudo_credential_name)
        credential_id = ensure_credential(gmp, login_credential_name, GVM_FLEET_LOGIN, fleet_target["key_path"])
        target_id = ensure_target(
            gmp, object_name, [fleet_target["host"]], credential_id, port_list_id,
            comment=f"Managed by setup_credentials.py; single explicit host. {marker}",
        )
    return ensure_task(gmp, object_name, config_id, target_id, scanner_id, schedule_id)


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        cleanup_legacy(gmp)

        schedule_ids_by_zone = {}
        task_ids_by_zone = {}

        def schedule_for(zone):
            if zone not in schedule_ids_by_zone:
                schedule_ids_by_zone[zone] = ensure_schedule(gmp, zone)
            return schedule_ids_by_zone[zone]

        mikrotik_credential_id = ensure_credential(
            gmp, MIKROTIK_CREDENTIAL["name"], MIKROTIK_CREDENTIAL["login"], MIKROTIK_CREDENTIAL["key_path"],
        )
        mikrotik_target_id = ensure_target(
            gmp, MIKROTIK_TARGET["name"], MIKROTIK_TARGET["hosts"], mikrotik_credential_id, port_list_id,
            comment="Managed by setup_credentials.py; MikroTik RouterOS gvm-scan user.",
        )
        mikrotik_task_id = ensure_task(
            gmp, MIKROTIK_TARGET["name"], config_id, mikrotik_target_id, scanner_id,
            schedule_for(MIKROTIK_TARGET["zone"]),
        )
        task_ids_by_zone.setdefault(MIKROTIK_TARGET["zone"], []).append(mikrotik_task_id)

        for fleet_target in load_fleet_targets(GVM_FLEET_DIR):
            zone = fleet_target["zone"]
            task_id = reconcile_fleet_host(
                gmp, fleet_target, config_id, scanner_id, port_list_id, schedule_for(zone),
            )
            if task_id:
                task_ids_by_zone.setdefault(zone, []).append(task_id)

        for zone, task_ids in task_ids_by_zone.items():
            ensure_zone_tag(gmp, zone, task_ids)

        if START_TASK_NAME:
            task_id = find_by_name(gmp, gmp.get_tasks, "task", START_TASK_NAME)
            if not task_id:
                raise RuntimeError(f"requested credentialed task {START_TASK_NAME!r} not found")
            gmp.start_task(task_id)
            print(f"started task {START_TASK_NAME!r} ({task_id})")

        if STATUS_TASK_NAME:
            task_id = find_by_name(gmp, gmp.get_tasks, "task", STATUS_TASK_NAME)
            if not task_id:
                raise RuntimeError(f"requested credentialed task {STATUS_TASK_NAME!r} not found")
            task = gmp.get_task(task_id)
            status = task.findtext("task/status", default="unknown")
            progress = task.findtext("task/progress", default="unknown")
            print(f"status {STATUS_TASK_NAME!r}: {status}, progress={progress}")

    print("done")


if __name__ == "__main__":
    sys.exit(main())
