#!/usr/bin/env python3
"""Create the first-pass authenticated Greenbone scan objects, plus the
fleet-wide gvm-scan credentialed targets (docs/lxc-scan-and-monitoring-
rollout/plan.md, gvm-07).

The original CREDENTIALS/TARGETS below deliberately reuse the administrator
SSH keys already trusted by the lab -- a pragmatic first pass that makes no
account, SSH, sudo, or authorized_keys changes on any target. Those private
keys are provided as read-only, short-lived bind mounts by
deploy-greenbone-stack.yml, one file + one env var per credential -- fine
for 4 credentials, unworkable for ~36.

The fleet-wide gvm-scan targets (added 2026-09-29) use a different,
scalable delivery shape instead: a single bind-mounted directory
(GVM_FLEET_DIR, default /tmp/fleet) containing one targets.json manifest
(list of {"name": str, "host": str} -- no secret content, safe to write
without no_log) plus one "<name>.key" (SSH private key) and one
"<name>.sudopass" (plaintext sudo password) file per fleet stack. Each
fleet stack gets its own "usk" login credential (login="gvm-scan") AND its
own "up" elevate-privileges credential (same login, the sudo password) --
GVM's ssh_elevate_credential_id lets Local Security Checks run `sudo`
through a real password, not passwordless/no-creds, per the operator's
2026-09-29 "sudo with credentials" design decision.

The existing CIDR scan program remains anonymous.  Credentialed Targets are
explicit host lists so a root credential can never be applied accidentally to
an arbitrary host discovered on a subnet.
"""
import json
import os
import sys
from pathlib import Path

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]
START_TASK_NAME = os.environ.get("GREENBONE_START_TASK_NAME", "")
STATUS_TASK_NAME = os.environ.get("GREENBONE_STATUS_TASK_NAME", "")

# Fleet-wide gvm-scan targets (gvm-07) -- see module docstring for the
# directory shape. Empty/absent GVM_FLEET_DIR (or a missing targets.json
# inside it) means "no fleet targets this run" -- degrades gracefully, same
# philosophy as known_production_images.json's classify_artifact() and
# harbor_live_usage's None-on-failure semantics: an incomplete rollout
# should never crash the whole program, only skip what isn't ready yet.
GVM_FLEET_DIR = os.environ.get("GVM_FLEET_DIR", "/tmp/fleet")  # nosonar: python:S5443 -- container-internal /tmp inside an isolated `docker compose run --rm` gvm-tools container, not a shared host path; same accepted pattern as this file's existing /tmp/steve.key etc. bind mounts
GVM_FLEET_LOGIN = "gvm-scan"

FULL_CONFIG_NAME = "Full and fast"
SCANNER_NAME = "OpenVAS Default"
PORT_LIST_NAME = "All TCP and Nmap top 100 UDP"
ALIVE_TESTS = "ICMP, TCP-ACK Service & ARP Ping"

# `usk` is Greenbone's GMP credential type for "Username + SSH Key".
# Keep credentials per trust boundary even though the Pi account currently
# shares Steve's key material: their GVM login names and privilege models are
# different and must not be confused.
CREDENTIALS = {
    "lab-root": {
        "name": "Lab root SSH key (Steve)",
        "login": "root",
        "key_path": os.environ["GREENBONE_STEVE_KEY_PATH"],
    },
    "workstation-openvas": {
        "name": "Workstation openvas SSH key",
        "login": "openvas",
        "key_path": os.environ["GREENBONE_OPENVAS_WORKSTATION_KEY_PATH"],
    },
    "raspberry-pi-ansible": {
        "name": "Raspberry Pi ansible SSH key (Steve)",
        "login": "ansible",
        "key_path": os.environ["GREENBONE_STEVE_KEY_PATH"],
    },
    "mikrotik-gvm-scan": {
        "name": "MikroTik gvm-scan SSH key",
        "login": "gvm-scan",
        "key_path": os.environ["GREENBONE_MIKROTIK_KEY_PATH"],
    },
}

# Only managed, known hosts belong here.  Do not replace these with CIDRs:
# Greenbone attaches an SSH credential to an entire Target.  Test fixtures,
# pve-test-vm, and deliberately vulnerable targets are intentionally absent.
TARGETS = [
    {
        "name": "Credentialed scan: managed Debian services",
        "credential": "lab-root",
        "hosts": [
            "192.168.10.163",  # ci-runner-01
            "192.168.20.110",  # authentik-stack
            "192.168.20.111",  # step-ca-stack
            "192.168.20.112",  # monitoring-stack
            "192.168.20.113",  # dns-stack
            "192.168.20.114",  # graylog-stack
            "192.168.20.120",  # portainer-stack
            "192.168.30.10",   # proxy-stack / Traefik (Tier A)
            "192.168.40.62",   # net-service-01
            "192.168.40.110",  # harbor-stack
            "192.168.40.111",  # apt-cacher-stack
            "192.168.40.112",  # netbox-stack
        ],
    },
    {
        "name": "Credentialed scan: pve hypervisor",
        "credential": "lab-root",
        "hosts": ["192.168.1.2"],
    },
    {
        "name": "Credentialed scan: Linux workstation",
        "credential": "workstation-openvas",
        "hosts": ["192.168.1.104"],
    },
    {
        "name": "Credentialed scan: Raspberry Pis",
        "credential": "raspberry-pi-ansible",
        "hosts": ["192.168.1.22", "192.168.1.23"],
    },
    {
        "name": "Credentialed scan: MikroTik router",
        "credential": "mikrotik-gvm-scan",
        "hosts": ["192.168.1.1"],
    },
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


def ensure_credential(gmp, name, login, key_path):
    existing = find_by_name(gmp, gmp.get_credentials, "credential", name)
    if existing:
        print(f"credential {name!r} already exists ({existing}), skipping")
        return existing

    private_key = Path(key_path).read_text(encoding="utf-8")
    response = gmp.create_credential(
        name=name,
        credential_type="usk",
        login=login,
        private_key=private_key,
        comment="Managed by setup_credentials.py; do not edit manually in GSA.",
    )
    credential_id = response.get("id")
    print(f"created credential {name!r} ({credential_id})")
    return credential_id


def ensure_elevate_credential(gmp, name, login, password):
    """The "up" (username+password) credential GVM uses for `sudo`
    privilege escalation during a Local Security Check -- separate from
    the "usk" credential used to log in over SSH. See ensure_credential()
    for the login-credential counterpart."""
    existing = find_by_name(gmp, gmp.get_credentials, "credential", name)
    if existing:
        print(f"credential {name!r} already exists ({existing}), skipping")
        return existing

    response = gmp.create_credential(
        name=name,
        credential_type="up",
        login=login,
        password=password,
        comment="Managed by setup_credentials.py; sudo elevate-privileges credential for gvm-scan.",
    )
    credential_id = response.get("id")
    print(f"created elevate credential {name!r} ({credential_id})")
    return credential_id


def ensure_target(gmp, name, hosts, credential_id, port_list_id, elevate_credential_id=None):
    existing = find_by_name(gmp, gmp.get_targets, "target", name)
    if existing:
        print(f"target {name!r} already exists ({existing}), skipping")
        return existing

    kwargs = {}
    if elevate_credential_id is not None:
        # NOT VERIFIED against the actually-installed python-gvm==27.5.*
        # (this program's own pinned version, see
        # terraform/lxc/ansible/files/gvm-bridge/requirements.txt) --
        # ssh_elevate_credential_id is the parameter name GMP's own
        # CREATE_TARGET schema implies (<ssh_credential><elevate_privilege>
        # <credential id=.../></elevate_privilege></ssh_credential>), but
        # python-gvm's high-level wrapper has changed this shape across
        # versions before. FAILS LOUDLY (not silently) if this kwarg name
        # is wrong for the installed version, on purpose: a target created
        # without real privilege escalation wired up would look like it
        # worked while silently never running `sudo` for any check, which
        # is worse than a hard failure here. Verify this against the real
        # installed version before trusting it in production; see
        # docs/lxc-scan-and-monitoring-rollout/plan.md gvm-07's own note.
        kwargs["ssh_elevate_credential_id"] = elevate_credential_id

    try:
        response = gmp.create_target(
            name=name,
            hosts=hosts,
            ssh_credential_id=credential_id,
            alive_test=ALIVE_TESTS,
            port_list_id=port_list_id,
            comment="Managed authenticated target; intentionally explicit hosts only.",
            **kwargs,
        )
    except TypeError as exc:
        raise RuntimeError(
            f"gmp.create_target() rejected ssh_elevate_credential_id -- the installed "
            f"python-gvm version's Targets.create_target() signature doesn't match what "
            f"this program assumed. Check the installed version's actual signature "
            f"(python3 -c \"import gvm, inspect; from gvm.protocols.gmp import Gmp; "
            f"print(inspect.signature(Gmp.create_target))\") and fix ensure_target() "
            f"accordingly before re-running. Original error: {exc}"
        ) from exc
    target_id = response.get("id")
    print(f"created target {name!r} ({target_id})")
    return target_id


def load_fleet_targets(fleet_dir):
    """Returns a list of {"name", "host", "key_path", "sudo_password"}
    dicts for the fleet-wide gvm-scan targets, or [] if GVM_FLEET_DIR
    doesn't exist / has no targets.json yet (e.g. before gvm-04's
    bootstrap has run for any stack) -- degrades gracefully, matching this
    program's existing "skip what isn't ready" philosophy rather than
    crashing the whole run over an incomplete rollout."""
    manifest_path = Path(fleet_dir) / "targets.json"
    if not manifest_path.exists():
        print(f"no fleet targets manifest at {manifest_path}, skipping fleet targets")
        return []
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    fleet = []
    for entry in entries:
        name, host = entry["name"], entry["host"]
        key_path = Path(fleet_dir) / f"{name}.key"
        sudopass_path = Path(fleet_dir) / f"{name}.sudopass"
        if not key_path.exists() or not sudopass_path.exists():
            print(f"WARN: fleet target {name!r} missing key/sudopass file, skipping")
            continue
        fleet.append({
            "name": name,
            "host": host,
            "key_path": str(key_path),
            "sudo_password": sudopass_path.read_text(encoding="utf-8").strip(),
        })
    return fleet


def ensure_task(gmp, name, config_id, target_id, scanner_id):
    existing = find_by_name(gmp, gmp.get_tasks, "task", name)
    if existing:
        print(f"task {name!r} already exists ({existing}), skipping")
        return existing
    response = gmp.create_task(
        name=name,
        config_id=config_id,
        target_id=target_id,
        scanner_id=scanner_id,
        comment="Managed authenticated task; intentionally unscheduled for first-pass validation.",
    )
    task_id = response.get("id")
    print(f"created task {name!r} ({task_id})")
    return task_id


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        credential_ids = {
            key: ensure_credential(gmp, value["name"], value["login"], value["key_path"])
            for key, value in CREDENTIALS.items()
        }
        config_id = resolve_id(gmp, gmp.get_scan_configs, FULL_CONFIG_NAME, "config")
        scanner_id = resolve_id(gmp, gmp.get_scanners, SCANNER_NAME, "scanner")
        port_list_id = resolve_id(gmp, gmp.get_port_lists, PORT_LIST_NAME, "port_list")

        for target in TARGETS:
            target_id = ensure_target(
                gmp,
                target["name"],
                target["hosts"],
                credential_ids[target["credential"]],
                port_list_id,
            )
            ensure_task(
                gmp,
                target["name"],
                config_id,
                target_id,
                scanner_id,
            )

        for fleet_target in load_fleet_targets(GVM_FLEET_DIR):
            fleet_name = fleet_target["name"]
            login_credential_id = ensure_credential(
                gmp, f"fleet-{fleet_name}-login", GVM_FLEET_LOGIN, fleet_target["key_path"],
            )
            elevate_credential_id = ensure_elevate_credential(
                gmp, f"fleet-{fleet_name}-sudo", GVM_FLEET_LOGIN, fleet_target["sudo_password"],
            )
            target_id = ensure_target(
                gmp,
                f"Credentialed scan: fleet/{fleet_name}",
                [fleet_target["host"]],
                login_credential_id,
                port_list_id,
                elevate_credential_id=elevate_credential_id,
            )
            ensure_task(
                gmp,
                f"Credentialed scan: fleet/{fleet_name}",
                config_id,
                target_id,
                scanner_id,
            )

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
