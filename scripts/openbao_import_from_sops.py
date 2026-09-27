#!/usr/bin/env python3
"""One-time import of the current SOPS secrets into OpenBao KV v2 (cutover, Phase 5).

  openbao_import_from_sops.py --dry-run     # decrypt + map + verify; print entry/field NAMES only
  openbao_import_from_sops.py               # write every entry (create-only, cas=0)

Requires an explicit write token in BAO_TOKEN (never read from a token file)
and LAB_IP_OPENBAO or OPENBAO_ADDR. Decrypts terraform/secrets.<src>.enc.yaml
with sops (SOPS_AGE_KEY_FILE defaults to ~/.config/sops/age/keys.txt).

Fails before writing anything if: any SOPS key is not mapped to exactly one
manifest entry with that sops_source, or any manifest field is missing/empty
in its SOPS source. Existing entries are never overwritten (cas=0); they are
reported as "exists" and compared by SHA-256 only.
Secret values are never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "secrets" / "manifest.json"
CACERT = REPO_ROOT / "certs" / "homelab-root.crt"


def decrypt(source: str) -> dict[str, str]:
    path = REPO_ROOT / "terraform" / f"secrets.{source}.enc.yaml"
    env = dict(os.environ)
    env.setdefault("SOPS_AGE_KEY_FILE", str(Path.home() / ".config" / "sops" / "age" / "keys.txt"))
    out = subprocess.run(
        ["sops", "--decrypt", "--output-type", "json", str(path)],
        check=True, capture_output=True, env=env,
    ).stdout
    data = json.loads(out)
    return {k: v for k, v in data.items() if k != "sops"}


def build_entries(manifest: dict, decrypted: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    problems = []
    mapped: dict[str, set[str]] = {src: set() for src in decrypted}
    entries: dict[str, dict[str, str]] = {}
    for entry, spec in manifest["entries"].items():
        src = spec["sops_source"]
        values = decrypted[src]
        entries[entry] = {}
        for field in spec["fields"]:
            if field in mapped[src]:
                problems.append(f"{src}:{field} mapped to more than one entry")
            mapped[src].add(field)
            value = values.get(field)
            if not isinstance(value, str) or value == "":
                problems.append(f"{entry}:{field} missing or empty in secrets.{src}.enc.yaml")
                continue
            entries[entry][field] = value
    for src, values in decrypted.items():
        for key in sorted(set(values) - mapped[src]):
            problems.append(f"secrets.{src}.enc.yaml:{key} is not mapped to any manifest entry")
    if problems:
        raise SystemExit("import aborted, nothing written:\n  " + "\n  ".join(problems))
    return entries


def digest(data: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    manifest = json.loads(MANIFEST.read_text())
    sources = sorted({spec["sops_source"] for spec in manifest["entries"].values()})
    decrypted = {src: decrypt(src) for src in sources}
    entries = build_entries(manifest, decrypted)

    if args.dry_run:
        for entry, data in entries.items():
            print(f"{entry}: {', '.join(sorted(data))}")
        print(f"dry-run OK: {len(entries)} entries, {sum(len(d) for d in entries.values())} fields")
        return 0

    token = os.environ.get("BAO_TOKEN", "").strip()
    if not token:
        print("ERROR: set BAO_TOKEN to an explicit write token (see plan, cutover step)", file=sys.stderr)
        return 1
    addr = os.environ.get("OPENBAO_ADDR", "").strip() or f"https://{os.environ['LAB_IP_OPENBAO']}:8200"
    ctx = ssl.create_default_context(cafile=str(CACERT))
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))

    def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        req = urllib.request.Request(
            f"{addr}/v1/{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
        )
        req.add_header("X-Vault-Token", token)
        req.add_header("Content-Type", "application/json")
        try:
            with opener.open(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            return exc.code, {}

    failed = 0
    for entry, data in entries.items():
        status, existing = call("GET", f"kv/data/{entry}")
        if status == 200:
            current = (existing.get("data") or {}).get("data") or {}
            same = digest({k: current.get(k) for k in data}) == digest(data)
            print(f"exists   {entry}  ({'matches SOPS' if same else 'DIFFERS from SOPS -- resolve by hand'})")
            failed += 0 if same else 1
            continue
        status, _ = call("POST", f"kv/data/{entry}", {"options": {"cas": 0}, "data": data})
        print(f"{'created ' if status in (200, 204) else 'FAILED  '} {entry}  ({len(data)} fields, HTTP {status})")
        failed += 0 if status in (200, 204) else 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
