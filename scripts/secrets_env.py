#!/usr/bin/env python3
"""Load secrets for one profile from OpenBao and exec a command with them.

Replaces the SOPS decrypt step inside ./with-secrets and ./with-secrets-prod*
when SECRETS_BACKEND=openbao. Standard library only (runs on the workstation
and on the self-hosted CI runner).

  secrets_env.py --profile pve -- terragrunt plan
  secrets_env.py --profile pve --check          # read everything, print counts only
  secrets_env.py --profile pve --list-fields    # no network; field names only

Reads secrets/manifest.json. Exports ONLY the fields the manifest lists for
the profile's entries, in entry order (later entries override earlier ones).
Fails closed: any unreadable entry, or any listed field that is missing or
empty, aborts before the command runs. Secret values are never printed and
never written to disk. The OpenBao token is revoked before exec.

Environment:
  OPENBAO_ADDR        default https://$LAB_IP_OPENBAO:8200
  OPENBAO_CACERT      default <repo>/certs/homelab-root.crt
  OPENBAO_CRED_DIR    default ~/.config/openbao  (<role>.role-id, <role>.secret-id)
  OPENBAO_GITHUB_JWT  GitHub Actions OIDC token, for profiles with auth=jwt-github
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "secrets" / "manifest.json"
DEFAULT_CACERT = REPO_ROOT / "certs" / "homelab-root.crt"


class SecretsError(Exception):
    """Any failure that must stop the wrapped command from running."""


def load_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretsError(f"cannot read manifest {path}: {exc}") from exc


def profile_plan(manifest: dict, profile: str) -> tuple[dict, list[tuple[str, list[str]]]]:
    profiles = manifest.get("profiles", {})
    if profile not in profiles:
        raise SecretsError(
            f"unknown profile '{profile}'; known: {', '.join(sorted(profiles))}"
        )
    prof = profiles[profile]
    entries = manifest.get("entries", {})
    plan = []
    for entry in prof["entries"]:
        if entry not in entries:
            raise SecretsError(f"profile '{profile}' references undefined entry '{entry}'")
        plan.append((entry, list(entries[entry]["fields"])))
    return prof, plan


class OpenBaoClient:
    def __init__(self, addr: str, cacert: str, opener=None):
        self.addr = addr.rstrip("/")
        if opener is None:
            ctx = ssl.create_default_context(cafile=cacert)
            opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))
        self._opener = opener
        self.token: str | None = None

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"{self.addr}/v1/{path}", data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("X-Vault-Token", self.token)
        try:
            with self._opener.open(req, timeout=15) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise SecretsError(f"OpenBao {method} {path}: HTTP {exc.code}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise SecretsError(f"OpenBao {method} {path}: {exc}") from None
        return json.loads(raw) if raw else {}

    def login_approle(self, role_id: str, secret_id: str) -> None:
        resp = self._request("POST", "auth/approle/login", {"role_id": role_id, "secret_id": secret_id})
        self.token = resp["auth"]["client_token"]

    def login_jwt(self, mount: str, role: str, jwt: str) -> None:
        resp = self._request("POST", f"auth/{mount}/login", {"role": role, "jwt": jwt})
        self.token = resp["auth"]["client_token"]

    def read_kv(self, entry: str) -> dict:
        resp = self._request("GET", f"kv/data/{entry}")
        data = (resp.get("data") or {}).get("data")
        if not isinstance(data, dict):
            raise SecretsError(f"entry '{entry}' has no data")
        return data

    def revoke_self(self) -> None:
        if self.token:
            try:
                self._request("POST", "auth/token/revoke-self")
            finally:
                self.token = None


def login(client: OpenBaoClient, prof: dict, cred_dir: Path) -> None:
    auth = prof.get("auth")
    role = prof["role"]
    if auth == "approle":
        try:
            role_id = (cred_dir / f"{role}.role-id").read_text().strip()
            secret_id = (cred_dir / f"{role}.secret-id").read_text().strip()
        except OSError as exc:
            raise SecretsError(
                f"missing AppRole credentials for '{role}' in {cred_dir} ({exc.strerror})"
            ) from None
        client.login_approle(role_id, secret_id)
    elif auth == "jwt-github":
        jwt = os.environ.get("OPENBAO_GITHUB_JWT", "").strip()
        if not jwt:
            raise SecretsError("OPENBAO_GITHUB_JWT is not set")
        client.login_jwt("jwt-github", role, jwt)
    else:
        raise SecretsError(f"unsupported auth '{auth}'")


def collect(client: OpenBaoClient, plan: list[tuple[str, list[str]]]) -> dict[str, str]:
    exported: dict[str, str] = {}
    problems = []
    for entry, fields in plan:
        data = client.read_kv(entry)
        for field in fields:
            value = data.get(field)
            if not isinstance(value, str) or value == "":
                problems.append(f"{entry}:{field}")
                continue
            exported[field] = value
    if problems:
        raise SecretsError("missing or empty fields (fail closed): " + ", ".join(problems))
    return exported


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--list-fields", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = args.command[1:] if args.command[:1] == ["--"] else args.command

    try:
        manifest = load_manifest(Path(args.manifest))
        prof, plan = profile_plan(manifest, args.profile)
        if args.list_fields:
            seen = []
            for _, fields in plan:
                for field in fields:
                    if field not in seen:
                        seen.append(field)
            print("\n".join(seen))
            return 0
        if not args.check and not command:
            raise SecretsError("no command given after --")

        addr = os.environ.get("OPENBAO_ADDR", "").strip()
        if not addr:
            ip = os.environ.get("LAB_IP_OPENBAO", "").strip()
            if not ip:
                raise SecretsError("neither OPENBAO_ADDR nor LAB_IP_OPENBAO is set")
            addr = f"https://{ip}:8200"
        cacert = os.environ.get("OPENBAO_CACERT", "").strip() or str(DEFAULT_CACERT)
        cred_dir = Path(os.environ.get("OPENBAO_CRED_DIR", "").strip() or Path.home() / ".config" / "openbao")

        client = OpenBaoClient(addr, cacert)
        login(client, prof, cred_dir)
        try:
            exported = collect(client, plan)
        finally:
            client.revoke_self()
    except SecretsError as exc:
        print(f"secrets_env: ERROR: {exc}", file=sys.stderr)
        return 1

    if args.check:
        print(f"secrets_env: OK profile={args.profile} entries={len(plan)} fields={len(exported)}")
        return 0

    env = dict(os.environ)
    env.update(exported)
    try:
        os.execvpe(command[0], command, env)
    except OSError as exc:
        print(f"secrets_env: ERROR: cannot exec {command[0]}: {exc.strerror}", file=sys.stderr)
        return 127
    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
