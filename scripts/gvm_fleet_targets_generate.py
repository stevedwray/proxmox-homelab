#!/usr/bin/env python3
"""Generate the GVM fleet-targets bind-mount directory for
setup_credentials.py's load_fleet_targets() (docs/lxc-scan-and-monitoring-
rollout/plan.md, gvm-07).

  gvm_fleet_targets_generate.py --out-dir /path/to/tempdir/fleet

For each in-scope stack (see IN_SCOPE_STACKS below -- the operator-
confirmed 2026-09-29 list, corrected during execution to also exclude
pentagi-stack [CTs confirmed destroyed on pve 2026-09-28] and
pentagi-upstream-control [a vanilla-upstream comparison baseline, not a
real production workload, same spirit as the cse-*/harness-target
exclusions]): resolves its static IP from its own stack.yaml (some stacks
hardcode a literal ip_address, others template it as "${lab_ip_X}/24" and
need the matching LAB_IP_X env var -- both forms are real and in use,
confirmed live 2026-09-29 by reading stack.yaml files directly, not
assumed), reads that stack's GVM scan credentials via
gvm_scan_host_secret.py (skipping with a warning, not failing the whole
run, if that stack's OpenBao entry doesn't exist yet -- e.g. gvm-04's
bootstrap hasn't been run for it), and writes:
  <out-dir>/targets.json           -- [{"name": str, "host": str}, ...]
  <out-dir>/<name>.key              -- SSH private key
  <out-dir>/<name>.sudopass         -- plaintext sudo password

Run from deploy-greenbone-stack.yml via delegate_to: localhost, same
process-boundary shape as gvm_scan_host_secret.py itself; requires the
same OPENBAO_ADDR/OPENBAO_CACERT/OPENBAO_CRED_DIR/LAB_IP_OPENBAO env vars
(the with-secrets-prod wrapper already exports LAB_IP_OPENBAO; the others
have working defaults, see gvm_scan_host_secret.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Operator-confirmed scope (2026-09-29): the real production stacks on
# pve, corrected during execution (see module docstring) to drop two more
# that don't actually belong here. This list is data, not a mechanical
# filter -- re-verify it by hand if the fleet changes, same as
# gvm_scan_credentials_bootstrap.py's own exclusion list.
IN_SCOPE_STACKS = [
    "ai-services-stack",
    "apt-cacher-stack",
    "authentik-stack",
    "ci-runner-01",
    "gaming-stack-lab",
    "graylog-stack",
    "greenbone-stack",
    "harbor-stack",
    "mcp-utility-stack",
    "monitoring-stack",
    "netbox-stack",
    "opensearch-stack",
    "pangolin-proxy",
    "portainer-stack",
    "proxy-stack",
    "secpipe-stack",
    "step-ca-stack",
    "technitium-stack",
    "wazuh-stack",
]

_TEMPLATE_RE = re.compile(r"^\$\{lab_ip_([a-z0-9_]+)\}/\d+$")
_LITERAL_RE = re.compile(r"^(\d+\.\d+\.\d+\.\d+)/\d+$")


def resolve_stack_ip(stack: str) -> str | None:
    """Reads terraform/lxc/stacks/<stack>/stack.yaml's ip_address field.
    Handles both forms seen live: a literal IP/prefix, or a
    "${lab_ip_X}/prefix" template resolved via env var LAB_IP_X (upper).
    Returns None (not a guess) if the field is missing or in a form this
    function doesn't recognize -- callers must skip, not invent an IP."""
    stack_yaml = REPO_ROOT / "terraform" / "lxc" / "stacks" / stack / "stack.yaml"
    if not stack_yaml.exists():
        return None
    for line in stack_yaml.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("ip_address:"):
            continue
        value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
        literal_match = _LITERAL_RE.match(value)
        if literal_match:
            return literal_match.group(1)
        template_match = _TEMPLATE_RE.match(value)
        if template_match:
            env_var = f"LAB_IP_{template_match.group(1).upper()}"
            return os.environ.get(env_var) or None
        return None
    return None


def fetch_secret(stack: str) -> dict | None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gvm_scan_host_secret.py"), "--stack", stack],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        print(f"WARN: no GVM scan credentials for {stack!r} yet ({result.stderr.strip()}), skipping", file=sys.stderr)
        return None
    return json.loads(result.stdout)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []
    for stack in IN_SCOPE_STACKS:
        host = resolve_stack_ip(stack)
        if host is None:
            print(f"WARN: could not resolve an IP for {stack!r}, skipping", file=sys.stderr)
            continue
        secret = fetch_secret(stack)
        if secret is None:
            continue
        (out_dir / f"{stack}.key").write_text(secret["GVM_SCAN_SSH_PRIVATE_KEY"], encoding="utf-8")
        (out_dir / f"{stack}.key").chmod(0o644)
        (out_dir / f"{stack}.sudopass").write_text(secret["GVM_SCAN_SUDO_PASSWORD"], encoding="utf-8")
        (out_dir / f"{stack}.sudopass").chmod(0o644)
        manifest.append({"name": stack, "host": host})

    (out_dir / "targets.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {len(manifest)}/{len(IN_SCOPE_STACKS)} fleet targets to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
