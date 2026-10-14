#!/usr/bin/env python3
"""Attach weekly recurring GMP Schedules to the vulnerability
("full-vuln") Tasks created by setup_scan_program.py --
docs/greenbone-stack/network-scan-rollout-plan.md Phase 4, extended by
docs/gvm-coverage-cleanup/plan.md (2026-10-11: five new zones).

Original operator instruction, 2026-08-16: schedule only the
vulnerability scans (not Discovery), staggered an hour apart, LAN segment
last, first occurrence 22:00 local time, recurring weekly. The five zones
added 2026-10-11 run on a separate night (Wednesday) with the same
one-hour stagger, so the Sunday night batch doesn't grow.

2026-10-14 (docs/gvm-scan-redesign/): the per-zone Discovery Tasks are now
scheduled weekly too, Thursday night 22:00 onward, 30 minutes apart (measured
discovery runs took 6-41 minutes), so new devices are noticed without the
full-vuln scans doing double duty.

Idempotent: looks up an existing Schedule by exact name first and reuses
it (does not update its icalendar/timezone if already present -- delete
the stale Schedule first if a time ever needs to change).
modify_task(schedule_id=...) runs every time, so a full-vuln Task that
setup_scan_program.py recreated gets its Schedule re-attached.

DURATION is deliberately omitted from every VEVENT -- gvmd defaults it to
PT0S, which never force-stops an in-progress scan on a recurring
schedule (resolved 2026-08-16 by reading gvmd's scheduler source).
"""
import os
import sys
from datetime import datetime
from datetime import timezone as dt_timezone

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]

# Naive local wall-clock times; gvmd applies SCAN_TIMEZONE to them.
SCAN_TIMEZONE = "Pacific/Auckland"

# First occurrence per zone; RRULE:FREQ=WEEKLY repeats it. The first seven
# are unchanged from 2026-08-16 (their Schedules already exist live).
ZONE_FIRST_RUN_LOCAL = {
    "build_seg": datetime(2026, 8, 16, 22, 0, 0),
    "mgmt_seg": datetime(2026, 8, 16, 23, 0, 0),
    "edge_seg": datetime(2026, 8, 17, 0, 0, 0),
    "infra_seg": datetime(2026, 8, 17, 1, 0, 0),
    "ai_seg": datetime(2026, 8, 17, 2, 0, 0),
    "game_seg": datetime(2026, 8, 17, 3, 0, 0),
    "lan": datetime(2026, 8, 17, 4, 0, 0),
    "pentest_seg": datetime(2026, 10, 14, 22, 0, 0),
    "media_seg": datetime(2026, 10, 14, 23, 0, 0),
    "cse_seg": datetime(2026, 10, 15, 0, 0, 0),
    "connector_seg": datetime(2026, 10, 15, 1, 0, 0),
    "apps_seg": datetime(2026, 10, 15, 2, 0, 0),
}

# Weekly Discovery runs: Thursday 2026-10-15 22:00 NZ, then every 30 minutes, so
# the last (lan, the longest at about 41 minutes) ends by about 04:15 Friday.
DISCOVERY_FIRST_RUN_LOCAL = {
    "build_seg": datetime(2026, 10, 15, 22, 0, 0),
    "edge_seg": datetime(2026, 10, 15, 22, 30, 0),
    "mgmt_seg": datetime(2026, 10, 15, 23, 0, 0),
    "infra_seg": datetime(2026, 10, 15, 23, 30, 0),
    "ai_seg": datetime(2026, 10, 16, 0, 0, 0),
    "game_seg": datetime(2026, 10, 16, 0, 30, 0),
    "pentest_seg": datetime(2026, 10, 16, 1, 0, 0),
    "media_seg": datetime(2026, 10, 16, 1, 30, 0),
    "cse_seg": datetime(2026, 10, 16, 2, 0, 0),
    "connector_seg": datetime(2026, 10, 16, 2, 30, 0),
    "apps_seg": datetime(2026, 10, 16, 3, 0, 0),
    "lan": datetime(2026, 10, 16, 3, 30, 0),
}


def find_by_name(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    el = response.find(tag)
    return el.get("id") if el is not None else None


def ensure_schedule(gmp, name, dtstart_local):
    existing = find_by_name(gmp, gmp.get_schedules, "schedule", name)
    if existing:
        print(f"schedule {name!r} already exists ({existing}), skipping")
        return existing

    uid = f"{name.replace(' ', '-').replace(':', '')}@gibbsgreatly.xyz"
    dtstamp = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart = dtstart_local.strftime("%Y%m%dT%H%M%S")
    icalendar = (
        "BEGIN:VCALENDAR\r\n"
        "PRODID:-//Greenbone.net//NONSGML Greenbone Security Manager //EN\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dtstamp}\r\n"
        f"DTSTART:{dtstart}\r\n"
        "RRULE:FREQ=WEEKLY\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    response = gmp.create_schedule(name=name, icalendar=icalendar, timezone=SCAN_TIMEZONE)
    schedule_id = response.get("id")
    print(f"created schedule {name!r} ({schedule_id}), first run {dtstart} {SCAN_TIMEZONE}, weekly")
    return schedule_id


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        for key, dtstart_local in ZONE_FIRST_RUN_LOCAL.items():
            task_name = f"LAN scan: {key} full-vuln"
            schedule_name = f"LAN scan: {key} full-vuln weekly"

            task_id = find_by_name(gmp, gmp.get_tasks, "task", task_name)
            if not task_id:
                raise RuntimeError(f"task {task_name!r} not found -- run setup_scan_program.py first")

            schedule_id = ensure_schedule(gmp, schedule_name, dtstart_local)
            gmp.modify_task(task_id, schedule_id=schedule_id)
            print(f"attached schedule {schedule_name!r} to task {task_name!r}")

        for key, dtstart_local in DISCOVERY_FIRST_RUN_LOCAL.items():
            task_name = f"LAN scan: {key} discovery"
            schedule_name = f"LAN scan: {key} discovery weekly"

            task_id = find_by_name(gmp, gmp.get_tasks, "task", task_name)
            if not task_id:
                raise RuntimeError(f"task {task_name!r} not found -- run setup_scan_program.py first")

            schedule_id = ensure_schedule(gmp, schedule_name, dtstart_local)
            gmp.modify_task(task_id, schedule_id=schedule_id)
            print(f"attached schedule {schedule_name!r} to task {task_name!r}")

    print("done")


if __name__ == "__main__":
    sys.exit(main())
