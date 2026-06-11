#!/usr/bin/env python3
"""Read-only production MikroTik preflight for pve canaries."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIKROTIK_CLIENT_DIR = REPO_ROOT / "terraform" / "lxc" / "stacks" / "netbox-stack" / "integrations"
sys.path.insert(0, str(MIKROTIK_CLIENT_DIR))

from mikrotik_client import MikrotikClient  # type: ignore


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    warning: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the production pve uplink is trunked correctly on the MikroTik "
            "and that the mgmt DNS/ICMP ACLs match the current 192.168.x.0/24 design."
        )
    )
    parser.add_argument(
        "--save-evidence",
        metavar="PATH",
        help="Write the output to PATH, or to a timestamped file if PATH is a directory.",
    )
    parser.add_argument(
        "--pve-host",
        default=os.environ.get("PROXMOX_HOST", ""),
        help="Production Proxmox host to inspect over SSH. Defaults to PROXMOX_HOST.",
    )
    parser.add_argument(
        "--pve-uplink-if",
        default=os.environ.get("PVE_UPLINK_INTERFACE", "enp7s0"),
        help="Interface name on the pve host that carries the MikroTik trunk. Default: enp7s0.",
    )
    parser.add_argument(
        "--required-vlans",
        default="10,20,30,40",
        help="Comma-separated VLAN IDs that must be tagged on the active pve uplink port.",
    )
    parser.add_argument(
        "--internal-name",
        default=os.environ.get("LAB_FQDN_TRAEFIK", "traefik.lab.gibbsgreatly.xyz"),
        help="Internal lab DNS name to resolve through the mgmt gateway.",
    )
    parser.add_argument(
        "--public-name",
        default="github.com",
        help="Public DNS name to resolve through the mgmt gateway.",
    )
    return parser.parse_args()


def write_evidence(target: str | None, content: str) -> str | None:
    if not target:
        return None
    path = Path(target)
    if path.is_dir():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = path / f"preflight-production-mikrotik-{stamp}.txt"
    path.write_text(content, encoding="utf-8")
    return str(path)


def run_command(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def ssh_read_mac(host: str, interface: str) -> tuple[bool, str]:
    cmd = [
        "ssh",
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        f"root@{host}",
        f"cat /sys/class/net/{shlex.quote(interface)}/address",
    ]
    result = run_command(cmd, timeout=20)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip() or "ssh failed"
    return True, result.stdout.strip().lower()


def normalize_mac(value: str) -> str:
    return value.strip().lower()


def vlan_id_matches(vlan_expr: str, wanted: int) -> bool:
    for token in (part.strip() for part in vlan_expr.split(",")):
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            try:
                start = int(start_text)
                end = int(end_text)
            except ValueError:
                continue
            if start <= wanted <= end:
                return True
            continue
        try:
            if int(token) == wanted:
                return True
        except ValueError:
            continue
    return False


def parse_csv_numbers(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def first_bridge_port_for_mac(host_table: list[dict], mac: str) -> str | None:
    candidates: list[dict] = []
    for row in host_table:
        if normalize_mac(str(row.get("mac-address", ""))) != mac:
            continue
        if str(row.get("local", "")).lower() == "true":
            continue
        candidates.append(row)
    for row in candidates:
        if str(row.get("vid", "")) == "1":
            return str(row.get("on-interface") or row.get("interface") or "")
    if candidates:
        row = candidates[0]
        return str(row.get("on-interface") or row.get("interface") or "")
    return None


def find_gateway_interface(address_rows: list[dict], cidr: str) -> str | None:
    for row in address_rows:
        if str(row.get("address")) == cidr:
            return str(row.get("interface") or row.get("actual-interface") or "")
    return None


def has_firewall_rule(
    rows: list[dict],
    *,
    in_interface: str,
    protocol: str,
    src_address: str,
    dst_address: str,
    dst_port: str | None = None,
) -> bool:
    for row in rows:
        if str(row.get("chain")) != "input":
            continue
        if str(row.get("action")) != "accept":
            continue
        if str(row.get("in-interface")) != in_interface:
            continue
        if str(row.get("protocol")) != protocol:
            continue
        if str(row.get("src-address")) != src_address:
            continue
        if str(row.get("dst-address")) != dst_address:
            continue
        if dst_port is not None and str(row.get("dst-port")) != dst_port:
            continue
        if dst_port is None and "dst-port" in row and str(row.get("dst-port")) not in {"", "0"}:
            continue
        return True
    return False


def dig_query(server: str, name: str, *, tcp: bool = False) -> tuple[bool, str, bool]:
    if shutil.which("dig") is None:
        return False, "dig not installed on operator workstation", True
    cmd = ["dig", f"@{server}", "+short", "+time=3", "+tries=1", name]
    if tcp:
        cmd.insert(1, "+tcp")
    result = run_command(cmd, timeout=10)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip() or "dig failed", False
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip() and not line.startswith(";")]
    if not lines:
        return False, "no answer", False
    return True, lines[0], False


def main() -> int:
    args = parse_args()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    branch_result = run_command(["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"])
    git_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

    results: list[CheckResult] = []

    target_node = os.environ.get("TF_VAR_proxmox_node", "")
    if target_node == "pve":
        results.append(CheckResult("target guard", True, "TF_VAR_proxmox_node=pve"))
    else:
        results.append(CheckResult("target guard", False, f"expected TF_VAR_proxmox_node=pve, got {target_node!r}"))

    pve_host = args.pve_host.strip()
    if not pve_host:
        results.append(CheckResult("pve host selection", False, "PROXMOX_HOST is not set"))
    else:
        results.append(CheckResult("pve host selection", True, f"using pve host {pve_host}"))

    required_vlans = parse_csv_numbers(args.required_vlans)

    ok_mac, uplink_mac_or_err = ssh_read_mac(pve_host, args.pve_uplink_if) if pve_host else (False, "no pve host")
    uplink_mac = uplink_mac_or_err if ok_mac else ""
    if ok_mac:
        results.append(CheckResult("pve uplink MAC", True, f"{args.pve_uplink_if} -> {uplink_mac}"))
    else:
        results.append(CheckResult("pve uplink MAC", False, f"failed to read {args.pve_uplink_if} on {pve_host}: {uplink_mac_or_err}"))

    client = None
    mikrotik_error = None
    try:
        client = MikrotikClient(
            host=os.environ.get("MIKROTIK_HOST"),
            port=int(os.environ.get("MIKROTIK_PORT", "443")),
            user=os.environ.get("MIKROTIK_USER"),
            password=os.environ.get("MIKROTIK_PASSWORD"),
        )
    except Exception as exc:
        mikrotik_error = str(exc)

    if client is None:
        results.append(CheckResult("mikrotik api", False, mikrotik_error or "failed to initialize client"))
        host_table: list[dict] = []
        bridge_vlans: list[dict] = []
        address_rows: list[dict] = []
        firewall_rows: list[dict] = []
    else:
        try:
            host_table = client.get("/interface/bridge/host")
            bridge_vlans = client.get("/interface/bridge/vlan")
            address_rows = client.get("/ip/address")
            firewall_rows = client.get("/ip/firewall/filter")
            results.append(CheckResult("mikrotik api", True, f"queried {client.base_url} via read-only credentials"))
        except Exception as exc:
            results.append(CheckResult("mikrotik api", False, f"query failed: {exc}"))
            host_table = []
            bridge_vlans = []
            address_rows = []
            firewall_rows = []

    learned_port = first_bridge_port_for_mac(host_table, uplink_mac) if uplink_mac and host_table else None
    if learned_port:
        results.append(CheckResult("uplink bridge-port discovery", True, f"router learns {uplink_mac} on {learned_port}"))
    else:
        results.append(CheckResult("uplink bridge-port discovery", False, f"router does not learn {uplink_mac or 'unknown mac'} on any bridge port"))

    for vlan in required_vlans:
        row = next((item for item in bridge_vlans if vlan_id_matches(str(item.get("vlan-ids", "")), vlan)), None)
        if row is None:
            results.append(CheckResult(f"trunk vlan {vlan}", False, f"no bridge/vlan row found for VLAN {vlan}"))
            continue
        tagged = [part.strip() for part in str(row.get("tagged") or row.get("current-tagged") or "").split(",") if part.strip()]
        if learned_port and learned_port in tagged:
            results.append(CheckResult(f"trunk vlan {vlan}", True, f"{learned_port} tagged for VLAN {vlan}"))
        else:
            results.append(CheckResult(f"trunk vlan {vlan}", False, f"{learned_port or 'unknown port'} missing from tagged ports {tagged} for VLAN {vlan}"))

    gateway_expectations = {
        "build gateway": (f"{os.environ.get('LAB_GW_BUILD', '192.168.10.1')}/24", "vlan10-build"),
        "mgmt gateway": (f"{os.environ.get('LAB_GW_MGMT', '192.168.20.1')}/24", "vlan20-mgmt"),
        "edge gateway": (f"{os.environ.get('LAB_GW_EDGE', '192.168.30.1')}/24", "vlan30-edge"),
        "infra gateway": (f"{os.environ.get('LAB_GW_INFRA', '192.168.40.1')}/24", "vlan40-infra"),
    }
    for label, (cidr, iface) in gateway_expectations.items():
        actual_iface = find_gateway_interface(address_rows, cidr)
        if actual_iface == iface:
            results.append(CheckResult(label, True, f"{cidr} present on {iface}"))
        elif actual_iface:
            results.append(CheckResult(label, False, f"{cidr} present on {actual_iface}, expected {iface}"))
        else:
            results.append(CheckResult(label, False, f"{cidr} missing from MikroTik /ip/address"))

    mgmt_subnet = os.environ.get("LAB_SUBNET_MGMT_CIDR", "192.168.20.0/24")
    mgmt_gateway = os.environ.get("LAB_GW_MGMT", "192.168.20.1")
    mgmt_acl_checks = [
        ("mgmt icmp acl", {"protocol": "icmp", "dst_port": None}),
        ("mgmt dns udp acl", {"protocol": "udp", "dst_port": "53"}),
        ("mgmt dns tcp acl", {"protocol": "tcp", "dst_port": "53"}),
    ]
    for label, spec in mgmt_acl_checks:
        if has_firewall_rule(
            firewall_rows,
            in_interface="vlan20-mgmt",
            protocol=spec["protocol"],
            src_address=mgmt_subnet,
            dst_address=mgmt_gateway,
            dst_port=spec["dst_port"],
        ):
            results.append(CheckResult(label, True, f"accept rule present for {mgmt_subnet} -> {mgmt_gateway} on vlan20-mgmt"))
        else:
            results.append(CheckResult(label, False, f"missing accept rule for {mgmt_subnet} -> {mgmt_gateway} on vlan20-mgmt"))

    internal_ok, internal_detail, internal_warn = dig_query(mgmt_gateway, args.internal_name)
    results.append(
        CheckResult(
            "mgmt gateway internal dns",
            internal_ok,
            f"{args.internal_name} -> {internal_detail}" if internal_ok else f"{args.internal_name}: {internal_detail}",
            warning=internal_warn,
        )
    )
    public_ok, public_detail, public_warn = dig_query(mgmt_gateway, args.public_name)
    results.append(
        CheckResult(
            "mgmt gateway public dns",
            public_ok,
            f"{args.public_name} -> {public_detail}" if public_ok else f"{args.public_name}: {public_detail}",
            warning=public_warn,
        )
    )

    lines: list[str] = []
    lines.append("======================================================================")
    lines.append("PRODUCTION MIKROTIK PREFLIGHT")
    lines.append(f"Run:    {now}")
    lines.append(f"Branch: {git_branch}")
    lines.append(f"pve:    {pve_host or 'unset'}")
    lines.append(f"uplink: {args.pve_uplink_if}")
    lines.append("======================================================================")
    for result in results:
        level = "PASS" if result.ok else ("WARN" if result.warning else "FAIL")
        lines.append(f"[{level}] {result.name}: {result.detail}")

    fail_count = sum(1 for result in results if not result.ok and not result.warning)
    warn_count = sum(1 for result in results if result.warning)
    pass_count = sum(1 for result in results if result.ok)
    lines.append("----------------------------------------------------------------------")
    lines.append(f"Checks passed: {pass_count}")
    lines.append(f"Warnings:      {warn_count}")
    lines.append(f"Checks failed: {fail_count}")
    lines.append(f"Verdict: {'PASS' if fail_count == 0 else 'FAIL'}")
    output = "\n".join(lines)
    print(output)

    written = write_evidence(args.save_evidence, output)
    if written:
        print(f"Evidence written to: {written}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
