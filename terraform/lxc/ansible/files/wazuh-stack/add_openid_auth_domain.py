#!/usr/bin/env python3
"""Add an openid_auth_domain block to a Wazuh/OpenSearch security config.yml.

Used by deploy-wazuh-stack.yml's OIDC play. config.yml (the security
plugin's dynamic auth-domain config) has no vendored source in
wazuh-docker -- it's baked into the wazuh-indexer image, not shipped as
an editable file. Rather than guess its baseline shape, the playbook
extracts the LIVE default from the running container and this script
adds the new domain on top of it, preserving everything else untouched.

Usage: add_openid_auth_domain.py <input config.yml> <output config.yml> <openid connect URL>
"""

import sys

import yaml

OPENID_DOMAIN_NAME = "openid_auth_domain"


def main() -> int:
    if len(sys.argv) != 4:
        print(f"usage: {sys.argv[0]} <input> <output> <connect-url>", file=sys.stderr)
        return 2

    input_path, output_path, connect_url = sys.argv[1], sys.argv[2], sys.argv[3]

    with open(input_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    authc = config.setdefault("config", {}).setdefault("dynamic", {}).setdefault("authc", {})

    if OPENID_DOMAIN_NAME in authc:
        # Already present (idempotent re-run) -- nothing to do.
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
        return 0

    # Standard shape per OpenSearch security plugin docs. Left alongside
    # basic_internal_auth_domain (not replacing it) -- API/internal
    # tooling that authenticates with basic auth keeps working; the
    # dashboard's own auth.type: openid setting is what actually routes
    # interactive browser logins through this domain instead.
    authc[OPENID_DOMAIN_NAME] = {
        "http_enabled": True,
        "transport_enabled": False,
        "order": 1,
        "http_authenticator": {
            "type": "openid",
            "challenge": False,
            "config": {
                "subject_key": "sub",
                "roles_key": "roles",
                "openid_connect_url": connect_url,
            },
        },
        "authentication_backend": {
            "type": "noop",
        },
    }

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
