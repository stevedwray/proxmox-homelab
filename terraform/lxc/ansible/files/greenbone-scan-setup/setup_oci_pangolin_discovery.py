#!/usr/bin/env python3
"""Create (and, only when explicitly requested, start) a constrained
Greenbone Discovery scan for the OCI Pangolin public edge.

This is intentionally separate from the LAN/VLAN scan program. It assesses
only the public IP and expected edge ports; it does not run vulnerability
NVTs, use credentials, enumerate a CIDR, or attach a recurring schedule.
"""
import os
import sys

from gvm.connections import UnixSocketConnection
from gvm.protocols.gmp import Gmp
from gvm.transforms import EtreeCheckCommandTransform

GVM_SOCKET_PATH = os.environ.get("GVM_SOCKET_PATH", "/run/gvmd/gvmd.sock")
GVM_USERNAME = os.environ["GVM_USERNAME"]
GVM_PASSWORD = os.environ["GVM_PASSWORD"]
START_SCAN = os.environ.get("GREENBONE_START_OCI_PANGOLIN_DISCOVERY", "false").lower() == "true"

TARGET_IP = "192.9.191.163"
TARGET_NAME = "OCI Pangolin public edge discovery"
TASK_NAME = "OCI Pangolin public edge discovery"
PORT_LIST_NAME = "OCI Pangolin public edge ports"
PORT_RANGE = "T:22,80,443,U:51820,21820"
DISCOVERY_CONFIG_NAME = "Discovery"
SCANNER_NAME = "OpenVAS Default"


def find_id(gmp, getter, tag, name):
    response = getter(filter_string=f'name="{name}"')
    element = response.find(tag)
    return element.get("id") if element is not None else None


def require_id(gmp, getter, tag, name):
    result = find_id(gmp, getter, tag, name)
    if not result:
        raise RuntimeError(f"{tag} {name!r} not found")
    return result


def main():
    connection = UnixSocketConnection(path=GVM_SOCKET_PATH)
    with Gmp(connection, transform=EtreeCheckCommandTransform()) as gmp:
        gmp.authenticate(GVM_USERNAME, GVM_PASSWORD)

        config_id = require_id(gmp, gmp.get_scan_configs, "config", DISCOVERY_CONFIG_NAME)
        scanner_id = require_id(gmp, gmp.get_scanners, "scanner", SCANNER_NAME)

        port_list_id = find_id(gmp, gmp.get_port_lists, "port_list", PORT_LIST_NAME)
        if not port_list_id:
            port_list_id = gmp.create_port_list(name=PORT_LIST_NAME, port_range=PORT_RANGE).get("id")
            print(f"created port list {PORT_LIST_NAME!r}")

        target_id = find_id(gmp, gmp.get_targets, "target", TARGET_NAME)
        if not target_id:
            # The scanner is intentionally treated as alive: public ICMP can
            # be filtered even though TCP/UDP edge services are reachable.
            target_id = gmp.create_target(
                name=TARGET_NAME,
                hosts=[TARGET_IP],
                port_list_id=port_list_id,
                alive_test="Consider Alive",
            ).get("id")
            print(f"created target {TARGET_NAME!r}")

        task_id = find_id(gmp, gmp.get_tasks, "task", TASK_NAME)
        if not task_id:
            task_id = gmp.create_task(
                name=TASK_NAME,
                config_id=config_id,
                target_id=target_id,
                scanner_id=scanner_id,
            ).get("id")
            print(f"created task {TASK_NAME!r}")

        if START_SCAN:
            report = gmp.start_task(task_id)
            report_id = report.findtext("report_id")
            print(f"started task {TASK_NAME!r} report={report_id}")
        else:
            print(f"task {TASK_NAME!r} is ready but unscheduled and not started")


if __name__ == "__main__":
    sys.exit(main())
