#!/usr/bin/env python3
"""Add a wildcard user match to the all_access role in roles_mapping.yml.

Used by deploy-wazuh-stack.yml's OIDC play. OIDC-authenticated users
arrive with an auto-generated username (a hash of the OIDC subject
claim) and empty backend_roles (the openid_auth_domain's
authentication_backend is "noop" -- it doesn't look backend_roles up
anywhere), so the default all_access role (backend_roles: ["admin"]
only) never matches them and every search is rejected with a real
"no permissions for [indices:data/read/search]" security_exception --
confirmed live via an actual browser login, not guessed.

This is the same fix already used elsewhere in this exact file for a
different role (own_index already matches users: ["*"]), applied here
for a single-operator lab already gated by Authentik SSO -- reaching
this login page at all already required real authentication upstream.

Usage: add_all_access_wildcard_user.py <input roles_mapping.yml> <output roles_mapping.yml>
"""

import sys

import yaml

ROLE_NAME = "all_access"
WILDCARD_USER = "*"


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <input> <output>", file=sys.stderr)
        return 2

    input_path, output_path = sys.argv[1], sys.argv[2]

    with open(input_path, "r", encoding="utf-8") as f:
        mapping = yaml.safe_load(f)

    role = mapping.setdefault(ROLE_NAME, {})
    users = role.setdefault("users", [])

    if WILDCARD_USER not in users:
        users.append(WILDCARD_USER)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(mapping, f, default_flow_style=False, sort_keys=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
