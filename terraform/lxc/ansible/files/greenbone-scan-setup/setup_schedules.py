#!/usr/bin/env python3
"""Phase 4 (partial): attach weekly recurring GMP Schedules to the
vulnerability ("full-vuln") Tasks created by setup_scan_program.py (Phase 2)
-- docs/greenbone-stack/network-scan-rollout-plan.md, Phase 4.

Operator instruction, 2026-08-16: schedule only the vulnerability scans
(not Discovery) to start tonight, staggered an hour apart, LAN segment
last, first occurrence at 22:00 local time, recurring weekly thereafter.
Daily discovery scheduling is a separate, not-yet-requested piece of
Phase 4 -- out of scope for this script.

Idempotent: looks up an existing Schedule by exact name first and reuses
it (does not update its icalendar/timezone if already present -- same
create-only idempotency shape as setup_scan_program.py; re-run after a
genuine time change requires deleting the stale Schedule first, same
"known gap" as that file). modify_task(schedule_id=...) is naturally
idempotent -- setting the same schedule_id twice is a no-op.

Run the same way as setup_scan_program.py:
    docker compose run --rm \
      -v <this file>:/tmp/setup_schedules.py:ro \
      -e GVM_USERNAME=admin -e GVM_PASSWORD=... \
      gvm-tools python3 /tmp/setup_schedules.py

DURATION is deliberately omitted from every VEVENT below. gvmd's own docs
(docs/icalendar-schedules.md in greenbone/gvmd) list DURATION as an
optional, recognized property, and RFC 5545 does not require one on a
VEVENT -- a DTSTART-plus-RRULE-only event is a valid "point in time,
recurring" trigger with no bounded window. This sidesteps an unresolved
question (found no authoritative confirmation either way, live or in
docs) of whether gvmd would treat an elapsed DURATION as a signal to stop
an in-progress scan -- full-and-fast vuln scans routinely run well past
an hour, and the one-hour spacing below is only meant to stagger *start*
times, never to bound how long a scan is allowed to run.
"""
import os
import sys
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]

# Operator's local time zone, confirmed 2026-08-16 ("22:00 local time").
# DTSTART below is a naive (no TZID/Z) local wall-clock time -- per
# python-gvm's Schedules.create_schedule docstring, gvmd applies this
# `timezone` argument to any datetime in the icalendar text that lacks
# its own timezone info.
SCAN_TIMEZONE = "Pacific/Auckland"

# First occurrence -- tonight, 2026-08-16. Order matches
# setup_scan_program.py's ZONES table exactly; LAN deliberately last per
# operator instruction ("finishing with the LAN segment scan"). One hour
# apart, starting 22:00 -- rolls over past midnight for the last few
# zones, which is fine, FIRST_RUN_LOCAL + timedelta(hours=i) handles the
# date rollover automatically.
FIRST_RUN_LOCAL = datetime(2026, 8, 16, 22, 0, 0)
ZONE_ORDER = ["build_seg", "mgmt_seg", "edge_seg", "infra_seg", "ai_seg", "game_seg", "lan"]


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

        for i, key in enumerate(ZONE_ORDER):
            dtstart_local = FIRST_RUN_LOCAL + timedelta(hours=i)
            task_name = f"LAN scan: {key} full-vuln"
            schedule_name = f"LAN scan: {key} full-vuln weekly"

            task_id = find_by_name(gmp, gmp.get_tasks, "task", task_name)
            if not task_id:
                raise RuntimeError(f"task {task_name!r} not found -- run setup_scan_program.py first")

            schedule_id = ensure_schedule(gmp, schedule_name, dtstart_local)
            gmp.modify_task(task_id, schedule_id=schedule_id)
            print(f"attached schedule {schedule_name!r} to task {task_name!r}")

    print("done")


# Known gap, same shape as setup_scan_program.py's: this script is
# create-only, not a reconciler. Re-running after FIRST_RUN_LOCAL or
# ZONE_ORDER changes will NOT update an already-existing Schedule's
# icalendar/timezone -- delete the stale Schedule first (GSA, or
# `gmp.delete_schedule`) if the times ever need to change.
if __name__ == "__main__":
    sys.exit(main())
