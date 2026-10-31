#!/usr/bin/env python3
"""GitHub Actions runner health for node_exporter's textfile collector.

The runner updates itself daily. When that update fails the service stays up
and GitHub keeps listing the runner as online, but once GitHub requires a newer
version it stops handing the runner jobs, and scheduled workflows queue for
days with nothing to say why (2026-10: stale backup directories made the
update's `mv` fail every day for weeks). The only trace is the runner's own
`_diag/SelfUpdate-<date>-<time>.log.failed` / `.log.succeed` files, so this
turns those into metrics.

Writes /var/lib/node_exporter/textfile/github_runner.prom (atomically):
  github_runner_selfupdate_last_failed_timestamp_seconds
  github_runner_selfupdate_last_succeeded_timestamp_seconds
  github_runner_selfupdate_consecutive_failures    failures since the last success
  github_runner_service_active                     1 when a runner unit is active
  github_runner_metrics_last_run_timestamp_seconds
"""
import calendar
import os
import re
import subprocess
import time
from pathlib import Path

DIAG = Path(os.environ.get("RUNNER_DIAG_DIR", "/opt/actions-runner/_diag"))
OUT = os.environ.get("RUNNER_METRICS_OUT", "/var/lib/node_exporter/textfile/github_runner.prom")
UNIT_GLOB = os.environ.get("RUNNER_UNIT_GLOB", "actions.runner.*.service")
# The runner names the file after the (UTC) time it started: SelfUpdate-20261030-170927.log.failed
_NAME = re.compile(r"^SelfUpdate-(\d{8})-(\d{6})\.log\.(failed|succeed)$")


def parse_updates(names):
    """[(epoch, "failed"|"succeed")] for the self-update logs in `names`, oldest first."""
    out = []
    for name in names:
        m = _NAME.match(name)
        if not m:
            continue
        stamp = time.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        out.append((calendar.timegm(stamp), m.group(3)))
    return sorted(out)


def summarize(updates):
    """(last_failed, last_succeeded, consecutive_failures); 0 means never."""
    last_failed = max((t for t, r in updates if r == "failed"), default=0)
    last_ok = max((t for t, r in updates if r == "succeed"), default=0)
    return last_failed, last_ok, sum(1 for t, r in updates if r == "failed" and t > last_ok)


def service_active(run=subprocess.run):
    """True when at least one runner systemd unit is active."""
    try:
        res = run(["systemctl", "list-units", "--state=active", "--no-legend", "--plain", UNIT_GLOB],
                  capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.strip() for line in res.stdout.splitlines())


def render(last_failed, last_ok, consecutive, active, now):
    rows = [
        ("github_runner_selfupdate_last_failed_timestamp_seconds", "Newest failed runner self-update (0 = never).", last_failed),
        ("github_runner_selfupdate_last_succeeded_timestamp_seconds", "Newest successful runner self-update (0 = never).", last_ok),
        ("github_runner_selfupdate_consecutive_failures", "Failed self-updates since the last success.", consecutive),
        ("github_runner_service_active", "1 when a GitHub Actions runner systemd unit is active.", 1 if active else 0),
        ("github_runner_metrics_last_run_timestamp_seconds", "When this script last ran.", now),
    ]
    return "".join(f"# HELP {n} {h}\n# TYPE {n} gauge\n{n} {v}\n" for n, h, v in rows)


def main():
    names = [p.name for p in DIAG.iterdir()] if DIAG.is_dir() else []
    last_failed, last_ok, consecutive = summarize(parse_updates(names))
    text = render(last_failed, last_ok, consecutive, service_active(), int(time.time()))
    tmp = f"{OUT}.tmp"
    Path(tmp).write_text(text)
    os.replace(tmp, OUT)  # the collector only reads *.prom, and never sees a half-written file


if __name__ == "__main__":
    main()
