#!/usr/bin/env python3
"""Reconcile Greenbone's credentialed scan objects -- one per VLAN/zone
(docs/gvm-coverage-cleanup/README.md; operator decision 2026-10-12).

Every scan host in a zone shares that zone's "gvm-scan" SSH keypair
(OpenBao services/greenbone/scan-zones/<zone>), so each zone needs exactly
one credential, one multi-host Target and one Task:

  credential  zone-<zone>-login
  target/task Credentialed scan: <zone>
  schedule    Nightly|Weekly VLAN scan: <zone>   (ZONE_WEEKLY_SLOT; DAILY = nightly)

A GVM Target carries one SSH credential for all of its hosts, which is why
grouping by VLAN requires a shared key per VLAN. Each zone Task caps
concurrently scanned hosts at MAX_HOSTS_PER_TASK (ZONE_MAX_HOSTS overrides it
per zone), because greenbone-stack
(2 cores, memory-gated scan queue) could not keep up with 8 simultaneous
hosts.

Scan hosts and keys come from scripts/gvm_fleet_targets_generate.py,
delivered as one bind-mounted directory (GVM_FLEET_DIR, default
/tmp/fleet): targets.json ([{"zone", "hosts": [ip...], "names": [...]}])
plus one <zone>.key per zone.

The account is unprivileged and there is NO elevate credential: GVM's
elevate-privileges feature is su-based, not sudo (confirmed live
2026-10-11 -- every scan ran `su -l gvm-scan` and reported "SSH Login
Failed For Authenticated Checks").

The MikroTik router keeps its own RouterOS gvm-scan user/key and its own
target and task (GREENBONE_MIKROTIK_KEY_PATH).

Reconciliation: each zone Target's comment carries "managed-fp:<hash>" of
(hosts, key, port list, alive test, max hosts, RECONCILE_VERSION). If it is
missing or differs (a new host in the zone, a rotated key, a changed
setting), the zone's Task, Target and credential are deleted and recreated.
Delete-and-recreate rather than modify_target, because gvmd refuses to change
hosts/credentials on a Target that is in use by a Task. This deletes that
zone's report history in GVM; findings already ingested into OpenSearch
are unaffected. Running Tasks are left alone with a WARN.

Cleanup: every object left over from earlier designs (the per-host
"fleet/<host>" tasks/targets/credentials, their per-zone schedules and
zone:<name> tags, and the original root-key targets) is deleted. Errors on
any single object are logged as WARN, and the run continues but exits 1.
"""
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

from gvm.connections import UnixSocketConnection
from gvm.errors import GvmError
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

# One weekly start per zone, Pacific/Auckland wall clock (a real IANA zone,
# so NZ DST transitions resolve correctly). Monday and Thursday mornings are
# left free for the weekly CIDR full-vuln program (Sunday 22:00-Monday 04:00
# and Wednesday 22:00-Thursday 02:00, setup_schedules.py).
ZONE_WEEKLY_SLOT = {
    # Big four: 72-190 min each, still weekly (docs/gvm-scan-redesign/).
    "lan": ("TU", "00:30"),
    "mgmt_seg": ("WE", "00:30"),
    "infra_seg": ("FR", "00:30"),
    # The quick ten run every night, staggered by their last measured duration plus a
    # buffer (2026-10-22: 7-50 min each, 5.2 h in total, finishing about 04:45).
    "connector_seg": ("DAILY", "22:00"),   # 7 min
    "build_seg": ("DAILY", "22:15"),       # 23 min
    "cse_seg": ("DAILY", "22:45"),         # 20 min
    # (mgmt_seg openbao: DAILY 23:15, 22 min, see SPLIT_HOSTS)
    "game_seg": ("DAILY", "23:45"),        # 28 min
    "apps_seg": ("DAILY", "00:25"),        # 30 min
    "ai_seg": ("DAILY", "01:05"),          # 40 min
    "pentest_seg": ("DAILY", "01:55"),     # 41 min
    "media_seg": ("DAILY", "02:45"),       # 49 min
    "edge_seg": ("DAILY", "03:45"),        # 50 min
}
MIKROTIK_SLOT = ("WE", "05:00")
WEEKDAY_INDEX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
SCHEDULE_TIMEZONE = "Pacific/Auckland"
MAX_HOSTS_PER_TASK = 4
# mgmt_seg's web UIs (authentik, portainer) sit behind several ports and
# hostnames; the web-app probes cache every response in Redis per hostname and
# port, which filled 7GB of an 8GB container with 4 hosts at once (2026-10-13).
# At 2 hosts the same scan held steady near 2.5GB. Changing a zone's value
# changes its fingerprint, so only that zone's target/task is rebuilt.
ZONE_MAX_HOSTS = {"mgmt_seg": 2}

# Hosts scanned as their own task instead of with their zone, with some ports
# left out of the scan. Each gets its own target, its own credential (a copy of
# the zone key), a port list built from PORT_LIST_NAME minus exclude_ports, and
# its own weekly slot.
# 192.168.20.16 (openbao): the OpenBao UI on 8200 answers EVERY /ui/<anything>
# path with the same ~1MB page and HTTP 200. The web-app probe NVTs request
# thousands of invented paths and the scanner caches each response in Redis,
# which grew Redis from 0.5GB to 12GB in minutes on 2026-10-13 and got the
# scanner OOM-killed three times. Scanned alone without 8200 it takes 21
# minutes, Redis peaks at 351MB and the LSC results are complete.
SPLIT_HOSTS = {
    "mgmt_seg": [
        {"host": "192.168.20.16", "label": "openbao", "exclude_ports": [8200], "slot": ("DAILY", "23:15")},
    ],
}

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

# Bump to force every zone's GVM objects to be rebuilt on the next run.
# "3" = per-zone shared key (2026-10-12).
RECONCILE_VERSION = "3"
FP_MARKER = "managed-fp:"
ACTIVE_TASK_STATUSES = {"Running", "Requested", "Queued", "Stop Requested", "Delete Requested"}

MIKROTIK_CREDENTIAL = {
    "name": "MikroTik gvm-scan SSH key",
    "login": "gvm-scan",
    "key_path": os.environ["GREENBONE_MIKROTIK_KEY_PATH"],
}
MIKROTIK_TARGET = {"name": "Credentialed scan: MikroTik router", "hosts": ["192.168.1.1"]}  # nosonar: python:S1313 -- the lab router's fixed management IP

# Leftovers from earlier designs, deleted if present (a no-op once gone).
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
# Name prefixes of the per-host design (2026-09-29..2026-10-12).
LEGACY_TASK_TARGET_PREFIX = "Credentialed scan: fleet/"
LEGACY_CREDENTIAL_PREFIX = "fleet-"
LEGACY_SCHEDULE_PREFIXES = ["Daily fleet scan: ", "Weekly credentialed scan: "]
LEGACY_TAG_PREFIX = "zone:"


def find_by_name(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    element = response.find(tag)
    return element.get("id") if element is not None else None


def names_with_prefix(getter, tag, prefix):
    response = getter(filter_string=f'name~"{prefix}" rows=-1')
    return sorted({
        el.findtext("name") for el in response.findall(tag)
        if (el.findtext("name") or "").startswith(prefix)
    })


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


def tasks_using_target(gmp, target_id):
    """{task_id: name} for every task that references target_id, including
    trashcan tasks (found live 2026-10-12: a target can stay "in use" after
    its same-named task is deleted)."""
    users = {}
    target = gmp.get_target(target_id, tasks=True)
    for task in target.findall("target/tasks/task"):
        users[task.get("id")] = task.findtext("name") or "?"
    trash = gmp.get_tasks(trash=True, filter_string="rows=-1")
    for task in trash.findall("task"):
        target_el = task.find("target")
        if target_el is not None and target_el.get("id") == target_id:
            users[task.get("id")] = f"{task.findtext('name') or '?'} [trashcan]"
    return users


def delete_target_users(gmp, target_id, target_name):
    """Deletes every task still using a target. False if one is active."""
    for task_id, task_name in tasks_using_target(gmp, target_id).items():
        if not task_name.endswith("[trashcan]") and task_status(gmp, task_id) in ACTIVE_TASK_STATUSES:
            print(f"WARN: task {task_name!r} using target {target_name!r} is active, leaving both alone this run")
            return False
        gmp.delete_task(task_id, ultimate=True)
        print(f"deleted task {task_name!r} ({task_id}) -- it still used target {target_name!r}")
    return True


def delete_if_present(gmp, kind, name):
    """kind: task, target, credential, schedule or tag. Deletes every object
    of that kind with that exact name (duplicates included); for a target,
    first deletes every task still using it. Returns False only when an
    active task was left alone; GMP errors propagate to the caller."""
    getter = {
        "task": gmp.get_tasks, "target": gmp.get_targets, "credential": gmp.get_credentials,
        "schedule": gmp.get_schedules, "tag": gmp.get_tags,
    }[kind]
    deleter = {
        "task": gmp.delete_task, "target": gmp.delete_target, "credential": gmp.delete_credential,
        "schedule": gmp.delete_schedule, "tag": gmp.delete_tag,
    }[kind]
    for _ in range(10):
        object_id = find_by_name(gmp, getter, kind, name)
        if not object_id:
            return True
        if kind == "task" and task_status(gmp, object_id) in ACTIVE_TASK_STATUSES:
            print(f"WARN: task {name!r} is active, leaving it alone this run")
            return False
        if kind == "target" and not delete_target_users(gmp, object_id, name):
            return False
        deleter(object_id, ultimate=True)
        print(f"deleted {kind} {name!r} ({object_id})")
    raise RuntimeError(f"{kind} {name!r} still present after 10 deletions")


def best_effort_delete(gmp, kind, name, failures):
    try:
        if not delete_if_present(gmp, kind, name):
            failures.append(f"{kind} {name!r} (active)")
    except GvmError as exc:
        print(f"WARN: could not delete {kind} {name!r}: {exc}")
        failures.append(f"{kind} {name!r}")


def cleanup_legacy(gmp, failures):
    """Tasks first, then targets, then credentials, so nothing is in use."""
    tasks = LEGACY_TASKS_AND_TARGETS + names_with_prefix(gmp.get_tasks, "task", LEGACY_TASK_TARGET_PREFIX)
    targets = LEGACY_TASKS_AND_TARGETS + names_with_prefix(gmp.get_targets, "target", LEGACY_TASK_TARGET_PREFIX)
    credentials = LEGACY_CREDENTIALS + names_with_prefix(gmp.get_credentials, "credential", LEGACY_CREDENTIAL_PREFIX)
    for kind, names in (("task", tasks), ("target", targets), ("credential", credentials)):
        for name in names:
            best_effort_delete(gmp, kind, name, failures)


def cleanup_legacy_schedules_and_tags(gmp, failures):
    """Run after every task points at its new schedule."""
    for prefix in LEGACY_SCHEDULE_PREFIXES:
        for name in names_with_prefix(gmp.get_schedules, "schedule", prefix):
            best_effort_delete(gmp, "schedule", name, failures)
    for name in names_with_prefix(gmp.get_tags, "tag", LEGACY_TAG_PREFIX):
        best_effort_delete(gmp, "tag", name, failures)


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
    print(f"created target {name!r} ({target_id}) with {len(hosts)} host(s)")
    return target_id


def max_hosts_for(zone):
    return ZONE_MAX_HOSTS.get(zone, MAX_HOSTS_PER_TASK)


def ensure_task(gmp, name, config_id, target_id, scanner_id, schedule_id,
                max_hosts=MAX_HOSTS_PER_TASK):
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
        preferences={"max_hosts": str(max_hosts)},
        comment="Managed credentialed task; weekly, one per VLAN.",
    )
    task_id = response.get("id")
    print(f"created task {name!r} ({task_id}) scheduled via {schedule_id!r}")
    return task_id


def schedule_name(zone, label, slot):
    kind = "Nightly" if slot[0] == "DAILY" else "Weekly"
    return f"{kind} VLAN scan: {zone}" + (f" ({label})" if label else "")


def build_icalendar(name, day, hhmm, now):
    """Hand-built iCalendar -- the `icalendar` package isn't guaranteed in the
    gvm-tools image. gvmd applies SCHEDULE_TIMEZONE to the naive time.
    Weekly: DTSTART is the next calendar date on the slot's weekday (a date's
    weekday doesn't depend on timezone). DAILY: DTSTART is yesterday, so tonight's
    slot is always the next occurrence whatever the time of day it is applied."""
    hour, minute = hhmm.split(":")
    if day == "DAILY":
        first = now.date() - datetime.timedelta(days=1)
        rrule = "RRULE:FREQ=DAILY\r\n"
    else:
        first = now.date() + datetime.timedelta(days=(WEEKDAY_INDEX[day] - now.weekday()) % 7)
        rrule = "RRULE:FREQ=WEEKLY\r\n"
    uid = name.lower().replace(" ", "-").replace(":", "")
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//proxmox-homelab//gvm-vlan-schedule//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}@proxmox-homelab\r\n"
        f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTSTART:{first.strftime('%Y%m%d')}T{hour}{minute}00\r\n"
        + rrule +
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def ensure_weekly_schedule(gmp, name, day, hhmm):
    """Re-applies icalendar/timezone every run so a corrected slot lands on
    an existing schedule too (day is a weekday code, or DAILY)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    icalendar = build_icalendar(name, day, hhmm, now)
    when = f"every night at {hhmm}" if day == "DAILY" else f"weekly {day} {hhmm}"
    comment = f"{when.capitalize()} {SCHEDULE_TIMEZONE}."
    existing = find_by_name(gmp, gmp.get_schedules, "schedule", name)
    if existing:
        gmp.modify_schedule(existing, icalendar=icalendar, timezone=SCHEDULE_TIMEZONE, comment=comment)
        print(f"schedule {name!r} ({existing}) set to {when}")
        return existing
    response = gmp.create_schedule(name=name, icalendar=icalendar, timezone=SCHEDULE_TIMEZONE, comment=comment)
    schedule_id = response.get("id")
    print(f"created schedule {name!r} ({schedule_id}) {when}")
    return schedule_id


def subtract_ports(ranges, excluded):
    """ranges: [(start, end)]; returns them with every port in excluded removed."""
    for port in excluded:
        remaining = []
        for start, end in ranges:
            if port < start or port > end:
                remaining.append((start, end))
                continue
            if start < port:
                remaining.append((start, port - 1))
            if port < end:
                remaining.append((port + 1, end))
        ranges = remaining
    return ranges


def format_ranges(ranges):
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in sorted(ranges))


def ensure_port_list_without(gmp, base_name, excluded):
    """A port list equal to base_name minus the excluded ports (TCP and UDP)."""
    name = f"{base_name} minus {','.join(str(p) for p in excluded)}"
    existing = find_by_name(gmp, gmp.get_port_lists, "port_list", name)
    if existing:
        return existing
    base_id = resolve_id(gmp, gmp.get_port_lists, base_name, "port_list")
    by_type = {"tcp": [], "udp": []}
    for pr in gmp.get_port_list(base_id).iter("port_range"):
        by_type[(pr.findtext("type") or "").lower()].append((int(pr.findtext("start")), int(pr.findtext("end"))))
    parts = [f"{prefix}:{format_ranges(subtract_ports(by_type[kind], excluded))}"
             for kind, prefix in (("tcp", "T"), ("udp", "U")) if by_type[kind]]
    response = gmp.create_port_list(name=name, port_range=",".join(parts))
    print(f"created port list {name!r} ({response.get('id')})")
    return response.get("id")


def expand_split_hosts(zone_targets):
    """Move SPLIT_HOSTS out of their zone target into targets of their own."""
    expanded = []
    for zone_target in zone_targets:
        remaining = list(zone_target["hosts"])
        extra = []
        for split in SPLIT_HOSTS.get(zone_target["zone"], []):
            if split["host"] in remaining:
                remaining.remove(split["host"])
                extra.append({**zone_target, "hosts": [split["host"]], "names": [split["label"]],
                              "label": split["label"], "exclude_ports": split["exclude_ports"],
                              "slot": split["slot"]})
        expanded.append({**zone_target, "hosts": remaining})
        expanded.extend(extra)
    return expanded


def load_zone_targets(fleet_dir):
    """[{"zone", "hosts", "names", "key_path"}], or [] if GVM_FLEET_DIR has
    no targets.json -- degrades gracefully rather than crashing the run."""
    manifest_path = Path(fleet_dir) / "targets.json"
    if not manifest_path.exists():
        print(f"no zone targets manifest at {manifest_path}, skipping zone targets")
        return []
    zones = []
    for entry in json.loads(manifest_path.read_text(encoding="utf-8")):
        key_path = Path(fleet_dir) / f"{entry['zone']}.key"
        if not key_path.exists():
            print(f"WARN: zone {entry['zone']!r} missing key file, skipping")
            continue
        zones.append({**entry, "key_path": str(key_path)})
    return zones


def reconcile_zone(gmp, zone_target, config_id, scanner_id, port_list_id, schedule_id):
    """Returns the zone's task id, or None if it was left alone this run."""
    zone = zone_target["zone"]
    label = zone_target.get("label")
    excluded = zone_target.get("exclude_ports", [])
    object_name = f"Credentialed scan: {zone}" + (f" ({label})" if label else "")
    credential_name = f"zone-{zone}-{label}-login" if label else f"zone-{zone}-login"
    hosts = sorted(zone_target["hosts"])
    private_key = Path(zone_target["key_path"]).read_text(encoding="utf-8")
    parts = [",".join(hosts), private_key, PORT_LIST_NAME, ALIVE_TESTS,
             str(max_hosts_for(zone)), RECONCILE_VERSION]
    if excluded:
        # Only added when set, so zones without exclusions keep their fingerprint.
        parts.append("exclude:" + ",".join(str(p) for p in excluded))
        port_list_id = ensure_port_list_without(gmp, PORT_LIST_NAME, excluded)
    fp = fingerprint(*parts)
    marker = f"{FP_MARKER}{fp}"

    target_id = find_by_name(gmp, gmp.get_targets, "target", object_name)
    current_comment = ""
    if target_id:
        current_comment = gmp.get_target(target_id).findtext("target/comment", default="")
    if target_id and marker in current_comment:
        print(f"zone {zone!r} up to date ({len(hosts)} hosts, {marker})")
    else:
        reason = "new" if not target_id else "changed hosts/key/settings"
        print(f"zone {zone!r}: rebuilding GVM objects ({reason}, {len(hosts)} hosts)")
        if not delete_if_present(gmp, "task", object_name):
            return None
        if not delete_if_present(gmp, "target", object_name):
            return None
        delete_if_present(gmp, "credential", credential_name)
        credential_id = ensure_credential(gmp, credential_name, GVM_FLEET_LOGIN, zone_target["key_path"])
        target_id = ensure_target(
            gmp, object_name, hosts, credential_id, port_list_id,
            comment=f"Managed by setup_credentials.py; VLAN {zone}: {', '.join(zone_target['names'])}. {marker}",
        )
    return ensure_task(gmp, object_name, config_id, target_id, scanner_id, schedule_id,
                       max_hosts=max_hosts_for(zone))


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        failures = []
        cleanup_legacy(gmp, failures)

        mikrotik_credential_id = ensure_credential(
            gmp, MIKROTIK_CREDENTIAL["name"], MIKROTIK_CREDENTIAL["login"], MIKROTIK_CREDENTIAL["key_path"],
        )
        mikrotik_target_id = ensure_target(
            gmp, MIKROTIK_TARGET["name"], MIKROTIK_TARGET["hosts"], mikrotik_credential_id, port_list_id,
            comment="Managed by setup_credentials.py; MikroTik RouterOS gvm-scan user.",
        )
        ensure_task(
            gmp, MIKROTIK_TARGET["name"], config_id, mikrotik_target_id, scanner_id,
            ensure_weekly_schedule(gmp, "Weekly VLAN scan: MikroTik router", *MIKROTIK_SLOT),
        )

        superseded = []
        for zone_target in expand_split_hosts(load_zone_targets(GVM_FLEET_DIR)):
            zone = zone_target["zone"]
            label = zone_target.get("label")
            slot = zone_target.get("slot") or ZONE_WEEKLY_SLOT.get(zone)
            if not slot:
                print(f"WARN: zone {zone!r} has no ZONE_WEEKLY_SLOT entry, skipping")
                failures.append(f"zone {zone!r} (no slot)")
                continue
            try:
                schedule_id = ensure_weekly_schedule(gmp, schedule_name(zone, label, slot), *slot)
                if slot[0] == "DAILY":
                    superseded.append(f"Weekly VLAN scan: {zone}" + (f" ({label})" if label else ""))
                if reconcile_zone(gmp, zone_target, config_id, scanner_id, port_list_id, schedule_id) is None:
                    failures.append(f"zone {zone!r} (task active)")
            except GvmError as exc:
                print(f"WARN: zone {zone!r} failed: {exc}")
                failures.append(f"zone {zone!r}")

        cleanup_legacy_schedules_and_tags(gmp, failures)
        for name in superseded:  # their tasks now point at the nightly schedule
            if find_by_name(gmp, gmp.get_schedules, "schedule", name):
                best_effort_delete(gmp, "schedule", name, failures)

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

        if failures:
            print(f"FAILED: {len(failures)} item(s): {', '.join(failures)}")
            return 1

    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
