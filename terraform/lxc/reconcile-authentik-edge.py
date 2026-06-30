#!/usr/bin/env python3
"""Create/update-only Authentik reconciliation for EdgeManifest auth intent."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
import ssl
from typing import Any
from urllib.parse import urljoin
import urllib.error
import urllib.request
from urllib.parse import urlparse


DEFAULT_AUTHENTIK_URL = "https://authentik.lab.gibbsgreatly.xyz"
DEFAULT_TOKEN_ENV = "AUTHENTIK_SUPERUSER_API_TOKEN"
AUTHORIZATION_FLOW_SLUG_ENV = "AUTHENTIK_PROXY_AUTHORIZATION_FLOW_SLUG"
INVALIDATION_FLOW_SLUG_ENV = "AUTHENTIK_PROXY_INVALIDATION_FLOW_SLUG"
OIDC_SIGNING_KEY_NAME_ENV = "AUTHENTIK_OIDC_SIGNING_KEY_NAME"
DEFAULT_OIDC_SIGNING_KEY_NAME = "authentik Self-signed Certificate"
SHARED_OUTPOST_TYPE = "proxy"
DEFAULT_AUTHORIZATION_FLOW_SLUGS = (
    "default-provider-authorization-implicit-consent",
    "default-provider-authorization-explicit-consent",
)
DEFAULT_INVALIDATION_FLOW_SLUGS = (
    "default-provider-invalidation-flow",
    "default-invalidation-flow",
)
DEFAULT_OIDC_SCOPE_NAMES = ("openid", "profile", "email")
# Minimum outpost config — Authentik requires this field on creation.
OUTPOST_DEFAULT_CONFIG = {
    "log_level": "info",
    "authentik_host_insecure": False,
}
FORWARDAUTH_ENDPOINT_PATH = "/outpost.goauthentik.io/auth/traefik"
FORWARDAUTH_ACCEPTED_STATUS = {200, 202, 204, 302, 303, 307, 308, 401, 403}

SCRIPT_DIR = Path(__file__).resolve().parent
DISCOVER_MODULE_PATH = SCRIPT_DIR / "discover-authentik-edge.py"

_DISCOVER_SPEC = importlib.util.spec_from_file_location("discover_authentik_edge", DISCOVER_MODULE_PATH)
if _DISCOVER_SPEC is None or _DISCOVER_SPEC.loader is None:
    raise RuntimeError("failed to load discover-authentik-edge.py")
_DISCOVER = importlib.util.module_from_spec(_DISCOVER_SPEC)
sys.modules["discover_authentik_edge"] = _DISCOVER
_DISCOVER_SPEC.loader.exec_module(_DISCOVER)

RouteIntent = _DISCOVER.RouteIntent
DiscoveryIssue = _DISCOVER.DiscoveryIssue
OWNED_NAME_PREFIX = _DISCOVER.OWNED_NAME_PREFIX
SHARED_FORWARD_OUTPOST = _DISCOVER.SHARED_FORWARD_OUTPOST


@dataclass(frozen=True)
class ReconcileIssue:
    """Machine-readable reconciliation issue."""

    code: str
    message: str
    manifest: str | None = None
    route: str | None = None
    object_kind: str | None = None
    object_name: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class ReconcileAction:
    """Planned or applied reconciliation operation."""

    stack: str
    route: str
    object_kind: str
    object_name: str
    operation: str
    reason: str
    object_id: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class ReconcileResult:
    """Full reconciliation result."""

    apply: bool
    actions: tuple[ReconcileAction, ...]
    issues: tuple[ReconcileIssue, ...]
    stop_conditions: tuple[str, ...]
    request_methods: tuple[str, ...]
    write_count: int

    @property
    def ok(self) -> bool:
        return not self.issues and not self.stop_conditions

    def to_dict(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for action in self.actions:
            counts.setdefault(action.operation, 0)
            counts[action.operation] += 1
        return {
            "status": "passed" if self.ok else "failed",
            "mode": "apply" if self.apply else "dry-run",
            "write_count": self.write_count,
            "action_count": len(self.actions),
            "action_counts": counts,
            "issue_count": len(self.issues),
            "stop_condition_count": len(self.stop_conditions),
            "actions": [action.to_dict() for action in self.actions],
            "issues": [issue.to_dict() for issue in self.issues],
            "stop_conditions": list(self.stop_conditions),
            "request_methods": list(self.request_methods),
        }


@dataclass(frozen=True)
class _Prereqs:
    auth_pk: str | None
    inval_pk: str | None
    signing_pk: str | None
    scope_ids: list[str] | None


class AuthentikApiClient:
    """Minimal Authentik client with read + create/update support."""

    def __init__(self, base_url: str, token: str, verify_tls: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify_tls = verify_tls
        self.request_methods: list[str] = []

    def fetch_applications(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/core/applications/")

    def fetch_proxy_providers(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/providers/proxy/")

    def fetch_oauth2_providers(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/providers/oauth2/")

    def fetch_outposts(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/outposts/instances/")

    def fetch_flows(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/flows/instances/")

    def fetch_certificate_keypairs(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/crypto/certificatekeypairs/")

    def fetch_scope_property_mappings(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/propertymappings/provider/scope/")

    def create_proxy_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(f"{self.base_url}/api/v3/providers/proxy/", "POST", payload)

    def create_oauth2_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(f"{self.base_url}/api/v3/providers/oauth2/", "POST", payload)

    def update_proxy_provider(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            f"{self.base_url}/api/v3/providers/proxy/{provider_id}/",
            "PATCH",
            payload,
        )

    def update_oauth2_provider(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            f"{self.base_url}/api/v3/providers/oauth2/{provider_id}/",
            "PATCH",
            payload,
        )

    def create_application(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(f"{self.base_url}/api/v3/core/applications/", "POST", payload)

    def update_application(self, application_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            f"{self.base_url}/api/v3/core/applications/{application_id}/",
            "PATCH",
            payload,
        )

    def create_outpost(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(f"{self.base_url}/api/v3/outposts/instances/", "POST", payload)

    def update_outpost(self, outpost_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            f"{self.base_url}/api/v3/outposts/instances/{outpost_id}/",
            "PATCH",
            payload,
        )

    def _get_paginated(self, path: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_url: str | None = f"{self.base_url}{path}?page_size=200"
        while next_url:
            payload = self._request_json(next_url, "GET")
            if isinstance(payload, dict) and isinstance(payload.get("results"), list):
                results.extend(item for item in payload["results"] if isinstance(item, dict))
                raw_next = payload.get("next")
                if isinstance(raw_next, str) and raw_next:
                    next_url = urljoin(self.base_url + "/", raw_next)
                else:
                    next_url = None
                continue

            if isinstance(payload, list):
                results.extend(item for item in payload if isinstance(item, dict))
                break

            raise RuntimeError(f"unexpected Authentik response shape for {path}")
        return results

    def _request_json(self, url: str, method: str, payload: dict[str, Any] | None = None) -> Any:
        self.request_methods.append(method)
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

        context = None
        if not self.verify_tls:
            context = ssl.create_default_context()  # nosonar: python:S4423,python:S5527
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE  # nosonar: python:S4830
        else:
            extra_ca = os.environ.get("AUTHENTIK_EXTRA_CA")
            if extra_ca:
                context = ssl.create_default_context()  # nosonar: python:S4423,python:S5527
                context.load_verify_locations(cafile=extra_ca)
        with urllib.request.urlopen(request, context=context) as response:  # nosec B310 — internal Authentik API on private SDN
            raw = response.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create/update-only Authentik reconciliation for stack-owned edge manifests. "
            "Defaults to dry-run plan; use --apply to write."
        )
    )
    parser.add_argument(
        "manifests",
        nargs="*",
        type=Path,
        help=(
            "Optional explicit manifest files to reconcile. "
            "If omitted, discover stacks/*/edge.yaml under --stacks-dir."
        ),
    )
    parser.add_argument(
        "--stacks-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "stacks",
        help="Stacks directory used for discovery mode.",
    )
    parser.add_argument(
        "--authentik-url",
        default=DEFAULT_AUTHENTIK_URL,
        help="Base Authentik URL used for API calls.",
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help="Environment variable name containing the Authentik API token.",
    )
    parser.add_argument(
        "--no-verify-tls",
        action="store_true",
        help="Disable TLS certificate verification.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply create/update actions. Default behavior is dry-run planning only.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    return parser.parse_args()


def _resolve_manifest_paths(args: argparse.Namespace) -> list[Path]:
    if args.manifests:
        return sorted(path.resolve() for path in args.manifests)
    return _DISCOVER.discover_edge_manifests(args.stacks_dir.resolve())


def _resolve_token(token_env: str) -> tuple[str | None, ReconcileIssue | None]:
    token = os.environ.get(token_env, "").strip()
    if token:
        return token, None
    return None, ReconcileIssue(
        code="AKR001",
        message=(
            f"missing Authentik token in environment variable {token_env}. "
            "Run with ./with-secrets so SOPS-backed secrets are injected "
            "(example: ./with-secrets terraform/lxc/reconcile-authentik-edge.py --json)."
        ),
    )


def _resolve_slug_override(env_name: str) -> str | None:
    value = os.environ.get(env_name, "").strip()
    return value or None


def _as_issue(issue: DiscoveryIssue) -> ReconcileIssue:
    return ReconcileIssue(
        code=issue.code,
        message=issue.message,
        manifest=issue.manifest,
        route=issue.route,
        object_kind=issue.object_kind,
        object_name=issue.object_name,
    )


def _as_id(item: dict[str, Any]) -> str | None:
    return _DISCOVER._as_id(item.get("pk") or item.get("id"))


def _existing_by_name(items: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [item for item in items if _DISCOVER._get_name(item) == name]


def _resolve_single_owned_candidate(
    *,
    object_kind: str,
    expected_name: str,
    alternates: list[dict[str, Any]],
    inventory_items: list[dict[str, Any]],
    stack: str,
    route: str,
) -> tuple[dict[str, Any] | None, str | None]:
    by_name = _existing_by_name(inventory_items, expected_name)
    if len(by_name) > 1:
        return None, f"{stack}/{route}: multiple {object_kind} objects named {expected_name}"
    if len(by_name) == 1:
        return by_name[0], None

    alt = [item for item in alternates if item not in by_name]
    if not alt:
        return None, None
    if len(alt) > 1:
        return None, f"{stack}/{route}: multiple candidate {object_kind} objects matched"

    candidate = alt[0]
    candidate_name = _DISCOVER._get_name(candidate)
    if not _DISCOVER._is_owned_object(candidate_name):
        return (
            None,
            (
                f"{stack}/{route}: candidate {object_kind} {candidate_name} is unmanaged "
                "(missing owned prefix); refusing to guess"
            ),
        )
    return candidate, None


def _provider_payload(
    intent: RouteIntent,
    *,
    authorization_flow_pk: str,
    invalidation_flow_pk: str,
) -> dict[str, Any]:
    return {
        "name": intent.provider_name,
        "external_host": f"https://{intent.host}",
        "mode": "forward_single",
        "intercept_header_auth": True,
        "authorization_flow": authorization_flow_pk,
        "invalidation_flow": invalidation_flow_pk,
    }


def _desired_outpost_config() -> dict[str, Any]:
    browser_host = os.environ.get("LAB_FQDN_AUTHENTIK", "").strip()
    if browser_host:
        browser_url = f"https://{browser_host}"
    else:
        parsed = urlparse(DEFAULT_AUTHENTIK_URL)
        browser_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else DEFAULT_AUTHENTIK_URL

    return {
        **OUTPOST_DEFAULT_CONFIG,
        "authentik_host": browser_url,
        "authentik_host_browser": browser_url,
    }


def _oidc_provider_secret(intent: RouteIntent) -> tuple[str | None, ReconcileIssue | None]:
    env_name = _DISCOVER._oidc_client_secret_env(intent)
    if not env_name:
        return None, ReconcileIssue(
            code="AKR005",
            message=f"native OIDC route {intent.stack}/{intent.route} has no repo-managed Authentik mapping",
            manifest=intent.manifest,
            route=intent.route,
            object_kind="provider",
            object_name=intent.provider_name,
        )
    secret = os.environ.get(env_name, "").strip()
    if secret:
        return secret, None
    return None, ReconcileIssue(
        code="AKR006",
        message=f"missing required OIDC client secret in environment variable {env_name}",
        manifest=intent.manifest,
        route=intent.route,
        object_kind="provider",
        object_name=intent.provider_name,
    )


def _oidc_provider_payload(
    intent: RouteIntent,
    *,
    authorization_flow_pk: str,
    invalidation_flow_pk: str,
    client_secret: str,
    signing_key_pk: str,
    property_mapping_ids: list[str],
) -> dict[str, Any]:
    return {
        "name": intent.provider_name,
        "client_type": "confidential",
        "client_id": _DISCOVER._oidc_client_id(intent),
        "client_secret": client_secret,
        "authorization_flow": authorization_flow_pk,
        "invalidation_flow": invalidation_flow_pk,
        "redirect_uris": [
            {"matching_mode": "strict", "url": redirect_uri}
            for redirect_uri in _DISCOVER._oidc_redirect_uris(intent)
        ],
        "sub_mode": "hashed_user_id",
        "issuer_mode": "per_provider",
        "include_claims_in_id_token": True,
        "signing_key": signing_key_pk,
        "property_mappings": property_mapping_ids,
    }


def _resolve_oidc_signing_key_id(
    client: Any,
    *,
    signing_key_name_override: str | None,
) -> tuple[str | None, ReconcileIssue | None]:
    keypairs = client.fetch_certificate_keypairs()

    target_name = signing_key_name_override or DEFAULT_OIDC_SIGNING_KEY_NAME
    preferred = [
        item
        for item in keypairs
        if str(item.get("name", "")) == target_name
    ]
    if preferred:
        key_id = _DISCOVER._as_id(preferred[0].get("pk") or preferred[0].get("id"))
        if key_id:
            return key_id, None

    fallback = [
        item
        for item in keypairs
        if bool(item.get("private_key_available")) and str(item.get("private_key_type", "")).lower() == "rsa"
    ]
    if len(fallback) == 1:
        key_id = _DISCOVER._as_id(fallback[0].get("pk") or fallback[0].get("id"))
        if key_id:
            return key_id, None

    available_names = sorted({str(item.get("name", "")) for item in keypairs if item.get("name")})
    return None, ReconcileIssue(
        code="AKR007",
        message=(
            "missing required Authentik OIDC signing key for RS256 tokens; "
            f"looked for '{target_name}' and did not find a unique RSA keypair. "
            f"available={available_names}"
        ),
        route="oidc",
        object_kind="provider",
    )


def _resolve_oidc_scope_property_mapping_ids(
    client: Any,
    *,
    required_scopes: tuple[str, ...] = DEFAULT_OIDC_SCOPE_NAMES,
) -> tuple[list[str] | None, ReconcileIssue | None]:
    mappings = client.fetch_scope_property_mappings()
    by_scope: dict[str, list[dict[str, Any]]] = {}
    for item in mappings:
        scope_name = str(item.get("scope_name", "")).strip()
        if not scope_name:
            continue
        by_scope.setdefault(scope_name, []).append(item)

    selected: list[str] = []
    missing: list[str] = []
    for scope in required_scopes:
        candidates = by_scope.get(scope, [])
        if not candidates:
            missing.append(scope)
            continue
        mapping_id = _DISCOVER._as_id(candidates[0].get("pk") or candidates[0].get("id"))
        if not mapping_id:
            missing.append(scope)
            continue
        selected.append(mapping_id)

    if missing:
        return None, ReconcileIssue(
            code="AKR008",
            message=(
                "missing required Authentik OIDC scope property mappings: "
                f"required={list(required_scopes)} missing={missing}"
            ),
            route="oidc",
            object_kind="provider",
        )

    return selected, None

def _flow_pk(flow: dict[str, Any]) -> str | None:
    return _DISCOVER._as_id(flow.get("pk") or flow.get("id"))


def _resolve_flow_by_slug(
    *,
    flows: list[dict[str, Any]],
    flow_kind: str,
    designation: str,
    override_slug: str | None,
    default_slugs: tuple[str, ...],
    issue_code: str,
) -> tuple[str | None, ReconcileIssue | None]:
    if override_slug:
        matched = [flow for flow in flows if str(flow.get("slug", "")) == override_slug]
        if not matched:
            return None, ReconcileIssue(
                code=issue_code,
                message=(
                    f"missing required {flow_kind} flow: slug '{override_slug}' from {flow_kind} "
                    f"override was not found (designation={designation})"
                ),
            )
        flow_id = _flow_pk(matched[0])
        if not flow_id:
            return None, ReconcileIssue(
                code=issue_code,
                message=(
                    f"missing required {flow_kind} flow: slug '{override_slug}' resolved but has no id"
                ),
            )
        return flow_id, None

    for slug in default_slugs:
        matched = [flow for flow in flows if str(flow.get("slug", "")) == slug]
        if not matched:
            continue
        flow_id = _flow_pk(matched[0])
        if flow_id:
            return flow_id, None

    designation_slugs = sorted(
        {
            str(flow.get("slug", ""))
            for flow in flows
            if str(flow.get("designation", "")) == designation and flow.get("slug")
        }
    )
    return None, ReconcileIssue(
        code=issue_code,
        message=(
            f"missing required {flow_kind} flow: looked for default slugs {list(default_slugs)} "
            f"(designation={designation}); available designation slugs={designation_slugs}"
        ),
    )


def _resolve_proxy_flow_ids(
    client: Any,
    *,
    authorization_flow_slug_override: str | None,
    invalidation_flow_slug_override: str | None,
) -> tuple[tuple[str, str] | None, tuple[ReconcileIssue, ...]]:
    flows = client.fetch_flows()

    authorization_flow_pk, auth_issue = _resolve_flow_by_slug(
        flows=flows,
        flow_kind="authorization",
        designation="authorization",
        override_slug=authorization_flow_slug_override,
        default_slugs=DEFAULT_AUTHORIZATION_FLOW_SLUGS,
        issue_code="AKR002",
    )
    invalidation_flow_pk, invalidation_issue = _resolve_flow_by_slug(
        flows=flows,
        flow_kind="invalidation",
        designation="invalidation",
        override_slug=invalidation_flow_slug_override,
        default_slugs=DEFAULT_INVALIDATION_FLOW_SLUGS,
        issue_code="AKR003",
    )

    issues = tuple(issue for issue in (auth_issue, invalidation_issue) if issue is not None)
    if issues:
        return None, issues

    assert authorization_flow_pk is not None
    assert invalidation_flow_pk is not None
    return (authorization_flow_pk, invalidation_flow_pk), ()


def _application_payload(intent: RouteIntent, provider_id: str | None) -> dict[str, Any]:
    # launch_url is the public-facing entry point shown in the Authentik app catalogue.
    # Always use the edge route hostname (public FQDN), not _oidc_base_url: for some
    # stacks (Harbor in non-prod) the OIDC redirect_uri uses an internal IP which
    # Authentik rejects as an application launch_url.
    launch_url = f"https://{intent.host}/"
    payload: dict[str, Any] = {
        "name": intent.app_name,
        "slug": intent.app_slug,
        "launch_url": launch_url,
        "meta_launch_url": launch_url,
    }
    if provider_id:
        try:
            payload["provider"] = int(provider_id)
        except (ValueError, TypeError):
            payload["provider"] = provider_id
    return payload


def _patch_from_existing(existing: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key, value in desired.items():
        current = existing.get(key)
        if key in {"launch_url", "meta_launch_url"}:
            current_host = _DISCOVER._normalize_url_host(current)
            desired_host = _DISCOVER._normalize_url_host(value)
            if current_host != desired_host:
                patch[key] = value
            continue
        if key == "external_host":
            current_host = _DISCOVER._normalize_url_host(current)
            desired_host = _DISCOVER._normalize_url_host(value)
            if current_host != desired_host:
                patch[key] = value
            continue
        if current != value:
            patch[key] = value
    return patch


def _resolve_forwardauth_candidates(
    intent: RouteIntent,
    applications: list[dict[str, Any]],
    providers: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    host = intent.host.lower()
    provider_alternates = _DISCOVER._pick_candidates(
        providers,
        [
            lambda item, expected_host=host: _DISCOVER._normalize_url_host(item.get("external_host"))
            == expected_host,
        ],
    )
    provider_obj, provider_stop = _resolve_single_owned_candidate(
        object_kind="provider",
        expected_name=intent.provider_name,
        alternates=provider_alternates,
        inventory_items=providers,
        stack=intent.stack,
        route=intent.route,
    )

    app_alternates = _DISCOVER._pick_candidates(
        applications,
        [
            lambda item, expected_slug=intent.app_slug: str(item.get("slug", "")) == expected_slug,
            lambda item, expected_host=host: _DISCOVER._normalize_url_host(
                item.get("meta_launch_url") or item.get("launch_url")
            )
            == expected_host,
        ],
    )
    app_obj, app_stop = _resolve_single_owned_candidate(
        object_kind="application",
        expected_name=intent.app_name,
        alternates=app_alternates,
        inventory_items=applications,
        stack=intent.stack,
        route=intent.route,
    )

    stops = [msg for msg in (provider_stop, app_stop) if msg]
    return app_obj, provider_obj, stops


def _resolve_oidc_candidates(
    intent: RouteIntent,
    applications: list[dict[str, Any]],
    providers: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    host = intent.host.lower()
    expected_client_id = _DISCOVER._oidc_client_id(intent)

    provider_alternates = _DISCOVER._pick_candidates(
        providers,
        [
            lambda item, expected_host=host: _DISCOVER._provider_matches_host(item, expected_host),
            lambda item, expected_client_id=expected_client_id: bool(expected_client_id)
            and str(item.get("client_id", "")) == expected_client_id,
        ],
    )
    provider_obj, provider_stop = _resolve_single_owned_candidate(
        object_kind="provider",
        expected_name=intent.provider_name,
        alternates=provider_alternates,
        inventory_items=providers,
        stack=intent.stack,
        route=intent.route,
    )

    app_alternates = _DISCOVER._pick_candidates(
        applications,
        [
            lambda item, expected_slug=intent.app_slug: str(item.get("slug", "")) == expected_slug,
            lambda item, expected_host=host: _DISCOVER._normalize_url_host(
                item.get("meta_launch_url") or item.get("launch_url")
            )
            == expected_host,
        ],
    )
    app_obj, app_stop = _resolve_single_owned_candidate(
        object_kind="application",
        expected_name=intent.app_name,
        alternates=app_alternates,
        inventory_items=applications,
        stack=intent.stack,
        route=intent.route,
    )

    stops = [msg for msg in (provider_stop, app_stop) if msg]
    return app_obj, provider_obj, stops


def _resolve_delete_reports(
    intent: RouteIntent,
    applications: list[dict[str, Any]],
    providers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    host = intent.host.lower()

    app_matches = _DISCOVER._pick_candidates(
        applications,
        [
            lambda item, expected_name=intent.app_name: _DISCOVER._get_name(item) == expected_name,
            lambda item, expected_slug=intent.app_slug: str(item.get("slug", "")) == expected_slug,
            lambda item, expected_host=host: _DISCOVER._normalize_url_host(
                item.get("meta_launch_url") or item.get("launch_url")
            )
            == expected_host,
        ],
    )
    provider_matches = _DISCOVER._pick_candidates(
        providers,
        [
            lambda item, expected_name=intent.provider_name: _DISCOVER._get_name(item) == expected_name,
            lambda item, expected_host=host: _DISCOVER._provider_matches_host(item, expected_host),
        ],
    )

    app_matches = [
        item
        for item in app_matches
        if _DISCOVER._get_name(item) != "Traefik Dashboard"
    ]
    provider_matches = [
        item
        for item in provider_matches
        if _DISCOVER._get_name(item) != _DISCOVER.LEGACY_SHARED_FORWARD_PROVIDER
    ]

    stops: list[str] = []
    for object_kind, matches in (("application", app_matches), ("provider", provider_matches)):
        unmanaged = [
            item
            for item in matches
            if not _DISCOVER._is_owned_object(_DISCOVER._get_name(item))
        ]
        if unmanaged:
            names = ", ".join(sorted(_DISCOVER._get_name(item) for item in unmanaged))
            stops.append(
                f"{intent.stack}/{intent.route}: unmanaged {object_kind} objects match route ({names})"
            )

    return app_matches, provider_matches, stops


def _find_single_shared_outpost(
    outposts: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    by_name = [outpost for outpost in outposts if _DISCOVER._get_name(outpost) == SHARED_FORWARD_OUTPOST]
    if len(by_name) > 1:
        return None, f"multiple outposts named {SHARED_FORWARD_OUTPOST}"
    if len(by_name) == 1:
        return by_name[0], None
    return None, None


def _probe_forwardauth_endpoint(
    *,
    base_url: str,
    host: str,
    verify_tls: bool,
) -> tuple[int | None, str | None]:
    endpoint = f"{base_url.rstrip('/')}{FORWARDAUTH_ENDPOINT_PATH}"
    request = urllib.request.Request(
        endpoint,
        method="HEAD",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": host,
            "X-Forwarded-Uri": "/",
            "X-Forwarded-Method": "GET",
            "X-Forwarded-For": os.environ["LAB_IP_PROXY"],
        },
    )

    context = None
    if not verify_tls:
        context = ssl.create_default_context()  # nosonar: python:S4423,python:S5527
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # nosonar: python:S4830
    else:
        extra_ca = os.environ.get("AUTHENTIK_EXTRA_CA")
        if extra_ca:
            context = ssl.create_default_context()  # nosonar: python:S4423,python:S5527
            context.load_verify_locations(cafile=extra_ca)

    # Forward-auth commonly replies with redirects. Do not follow redirects here;
    # the redirect status itself is the signal that the endpoint is serving.
    class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
            return None

    handlers: list[urllib.request.BaseHandler] = [_NoRedirectHandler()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)

    last_error: str | None = None
    for attempt in range(3):
        if attempt > 0:
            time.sleep(0.25)

        try:
            with opener.open(request) as response:
                code = response.getcode()
                return (int(code) if isinstance(code, int) else None), None
        except urllib.error.HTTPError as exc:
            return int(exc.code), None
        except Exception as exc:  # pragma: no cover - integration-path failures only
            last_error = str(exc)

    return None, last_error


def _validate_forwardauth_endpoint_serving(
    client: Any,
    intents: list[RouteIntent],
) -> tuple[ReconcileIssue, ...]:
    base_url = getattr(client, "base_url", None)
    verify_tls = getattr(client, "verify_tls", None)
    if not isinstance(base_url, str) or not isinstance(verify_tls, bool):
        return ()

    issues: list[ReconcileIssue] = []
    hosts = sorted({intent.host for intent in intents if intent.auth_mode == "forwardAuth"})
    for host in hosts:
        status, error = _probe_forwardauth_endpoint(
            base_url=base_url,
            host=host,
            verify_tls=verify_tls,
        )
        if error is not None:
            issues.append(
                ReconcileIssue(
                    code="AKR004",
                    message=(
                        "forward-auth endpoint probe connectivity failure for host "
                        f"{host}: {error}"
                    ),
                    route="forwardAuth",
                    object_kind="outpost",
                    object_name=SHARED_FORWARD_OUTPOST,
                )
            )
            continue
        if status == 404:
            issues.append(
                ReconcileIssue(
                    code="AKR004",
                    message=(
                        "forward-auth endpoint returned 404 for host "
                        f"{host} at {FORWARDAUTH_ENDPOINT_PATH}; outpost is not serving"
                    ),
                    route="forwardAuth",
                    object_kind="outpost",
                    object_name=SHARED_FORWARD_OUTPOST,
                )
            )
            continue
        if status is None or status not in FORWARDAUTH_ACCEPTED_STATUS:
            issues.append(
                ReconcileIssue(
                    code="AKR004",
                    message=f"forward-auth endpoint returned unexpected status {status} for host {host}",
                    route="forwardAuth",
                    object_kind="outpost",
                    object_name=SHARED_FORWARD_OUTPOST,
                )
            )

    return tuple(issues)


def _call_create_provider(client: Any, intent: RouteIntent, payload: dict[str, Any]) -> dict[str, Any]:
    if intent.auth_mode == "forwardAuth":
        return client.create_proxy_provider(payload)
    return client.create_oauth2_provider(payload)


def _call_update_provider(client: Any, intent: RouteIntent, provider_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    if intent.auth_mode == "forwardAuth":
        return client.update_proxy_provider(provider_id, patch)
    return client.update_oauth2_provider(provider_id, patch)


def _handle_delete_reports_for_intent(
    intent: RouteIntent,
    applications: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    actions: list[ReconcileAction],
    consumed: dict[str, set[str]],
    stop_conditions: list[str],
) -> None:
    app_matches, provider_matches, route_stops = _resolve_delete_reports(intent, applications, providers)
    stop_conditions.extend(route_stops)
    _reason = "route auth mode is not Authentik-managed; object would be deleted in cleanup task"
    for app in app_matches:
        app_id = _as_id(app)
        if app_id:
            consumed["application"].add(app_id)
        actions.append(ReconcileAction(
            stack=intent.stack, route=intent.route,
            object_kind="application", object_name=_DISCOVER._get_name(app),
            operation="delete-report", reason=_reason, object_id=app_id,
        ))
    for provider in provider_matches:
        provider_id = _as_id(provider)
        if provider_id:
            consumed["provider"].add(provider_id)
        actions.append(ReconcileAction(
            stack=intent.stack, route=intent.route,
            object_kind="provider", object_name=_DISCOVER._get_name(provider),
            operation="delete-report", reason=_reason, object_id=provider_id,
        ))


def _resolve_intent_provider_payload(
    intent: RouteIntent,
    authorization_flow_pk: str,
    invalidation_flow_pk: str,
    oidc_signing_key_pk: str | None,
    oidc_scope_property_mapping_ids: list[str] | None,
) -> tuple[dict[str, Any] | None, ReconcileIssue | None]:
    if intent.auth_mode == "forwardAuth":
        return _provider_payload(
            intent,
            authorization_flow_pk=authorization_flow_pk,
            invalidation_flow_pk=invalidation_flow_pk,
        ), None
    client_secret, secret_issue = _oidc_provider_secret(intent)
    if secret_issue is not None:
        return None, secret_issue
    assert client_secret is not None
    return _oidc_provider_payload(
        intent,
        authorization_flow_pk=authorization_flow_pk,
        invalidation_flow_pk=invalidation_flow_pk,
        client_secret=client_secret,
        signing_key_pk=oidc_signing_key_pk,
        property_mapping_ids=oidc_scope_property_mapping_ids,
    ), None


def _reconcile_provider_for_intent(
    client: Any,
    intent: RouteIntent,
    provider_obj: dict[str, Any] | None,
    provider_payload: dict[str, Any],
    route_stops: list[str],
    stop_conditions: list[str],
    apply: bool,
    actions: list[ReconcileAction],
    providers: list[dict[str, Any]],
    consumed: dict[str, set[str]],
) -> tuple[dict[str, Any] | None, int, str | None]:
    write_count = 0
    if provider_obj is None:
        actions.append(ReconcileAction(
            stack=intent.stack, route=intent.route,
            object_kind="provider", object_name=intent.provider_name,
            operation="create", reason="owned provider is missing",
        ))
        if apply and not route_stops and not stop_conditions:
            created = _call_create_provider(client, intent, provider_payload)
            write_count += 1
            providers.append(created)
            provider_obj = created
        return provider_obj, write_count, None

    provider_id = _as_id(provider_obj)
    if provider_id:
        consumed["provider"].add(provider_id)
    provider_patch = _patch_from_existing(provider_obj, provider_payload)
    if provider_patch:
        actions.append(ReconcileAction(
            stack=intent.stack, route=intent.route,
            object_kind="provider", object_name=intent.provider_name,
            operation="update", reason="owned provider differs from desired state",
            object_id=provider_id,
        ))
        if apply and not route_stops and not stop_conditions and provider_id:
            updated = _call_update_provider(client, intent, provider_id, provider_patch)
            write_count += 1
            provider_obj.update(updated)
    else:
        actions.append(ReconcileAction(
            stack=intent.stack, route=intent.route,
            object_kind="provider", object_name=intent.provider_name,
            operation="noop", reason="owned provider already matches desired state",
            object_id=provider_id,
        ))
    return provider_obj, write_count, provider_id


def _reconcile_application_for_intent(
    client: Any,
    intent: RouteIntent,
    app_obj: dict[str, Any] | None,
    app_payload: dict[str, Any],
    route_stops: list[str],
    stop_conditions: list[str],
    apply: bool,
    actions: list[ReconcileAction],
    applications: list[dict[str, Any]],
    consumed: dict[str, set[str]],
) -> int:
    write_count = 0
    if app_obj is None:
        actions.append(ReconcileAction(
            stack=intent.stack, route=intent.route,
            object_kind="application", object_name=intent.app_name,
            operation="create", reason="owned application is missing",
        ))
        if apply and not route_stops and not stop_conditions:
            created = client.create_application(app_payload)
            write_count += 1
            applications.append(created)
            created_id = _as_id(created)
            if created_id:
                consumed["application"].add(created_id)
        return write_count

    app_id = _as_id(app_obj)
    app_patch = _patch_from_existing(app_obj, app_payload)
    if app_patch:
        actions.append(ReconcileAction(
            stack=intent.stack, route=intent.route,
            object_kind="application", object_name=intent.app_name,
            operation="update", reason="owned application differs from desired state",
            object_id=app_id,
        ))
        if apply and not route_stops and not stop_conditions and app_id:
            app_slug = app_obj.get("slug") or intent.app_slug
            updated = client.update_application(app_slug, app_patch)
            write_count += 1
            app_obj.update(updated)
    else:
        actions.append(ReconcileAction(
            stack=intent.stack, route=intent.route,
            object_kind="application", object_name=intent.app_name,
            operation="noop", reason="owned application already matches desired state",
            object_id=app_id,
        ))
    return write_count


def _build_outpost_update_patch(
    shared_outpost: dict[str, Any],
    required_provider_ids: set[str],
) -> tuple[dict[str, Any], str]:
    linked = _DISCOVER._provider_references(shared_outpost)
    missing_links = sorted(required_provider_ids - linked)
    desired_links = sorted(linked | required_provider_ids)
    outpost_config = shared_outpost.get("config")
    outpost_config = outpost_config if isinstance(outpost_config, dict) else {}
    desired_config = dict(outpost_config)
    config_changed = False
    for key, value in _desired_outpost_config().items():
        if outpost_config.get(key) != value:
            desired_config[key] = value
            config_changed = True
    patch: dict[str, Any] = {}
    reason_parts: list[str] = []
    if missing_links:
        patch["providers"] = desired_links
        reason_parts.append("shared outpost missing provider links")
    if config_changed:
        patch["config"] = desired_config
        reason_parts.append("shared outpost host config missing required values")
    return patch, "; ".join(reason_parts) if reason_parts else ""


def _reconcile_shared_outpost(
    client: Any,
    outposts: list[dict[str, Any]],
    required_provider_ids: set[str],
    apply: bool,
    stop_conditions: list[str],
    actions: list[ReconcileAction],
    consumed: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], int]:
    write_count = 0
    shared_outpost, outpost_stop = _find_single_shared_outpost(outposts)
    if outpost_stop:
        stop_conditions.append(outpost_stop)
        return outposts, 0
    if shared_outpost is None:
        actions.append(ReconcileAction(
            stack="_shared", route="forwardAuth",
            object_kind="outpost", object_name=SHARED_FORWARD_OUTPOST,
            operation="create", reason="shared forward-auth outpost is missing",
        ))
        if apply and not stop_conditions:
            created = client.create_outpost({
                "name": SHARED_FORWARD_OUTPOST,
                "type": SHARED_OUTPOST_TYPE,
                "providers": sorted(required_provider_ids),
                "config": _desired_outpost_config(),
            })
            write_count += 1
            outposts.append(created)
        return outposts, write_count

    outpost_id = _as_id(shared_outpost)
    if outpost_id:
        consumed["outpost"].add(outpost_id)
    outpost_patch, reason = _build_outpost_update_patch(shared_outpost, required_provider_ids)
    if outpost_patch:
        actions.append(ReconcileAction(
            stack="_shared", route="forwardAuth",
            object_kind="outpost", object_name=SHARED_FORWARD_OUTPOST,
            operation="update", reason=reason, object_id=outpost_id,
        ))
        if apply and not stop_conditions and outpost_id:
            updated = client.update_outpost(outpost_id, outpost_patch)
            write_count += 1
            shared_outpost.update(updated)
    else:
        actions.append(ReconcileAction(
            stack="_shared", route="forwardAuth",
            object_kind="outpost", object_name=SHARED_FORWARD_OUTPOST,
            operation="noop", reason="shared outpost already linked to all managed providers",
            object_id=outpost_id,
        ))
    return outposts, write_count


def _check_app_provider_link(
    app_obj: dict[str, Any] | None,
    provider_id: str | None,
    intent: "RouteIntent",
    consumed: dict[str, set[str]],
    stop_conditions: list[str],
) -> None:
    if app_obj is None:
        return
    app_id = _as_id(app_obj)
    if app_id:
        consumed["application"].add(app_id)
    linked_provider = _DISCOVER._get_provider_id_from_application(app_obj)
    if linked_provider and provider_id and linked_provider != provider_id:
        stop_conditions.append(f"{intent.stack}/{intent.route}: application links a different provider id")


def _detect_unmanaged_orphans(
    applications: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    intents: list[Any],
    consumed: dict[str, set[str]],
    stop_conditions: list[str],
) -> None:
    for item in applications:
        item_id = _as_id(item)
        if not item_id or item_id in consumed["application"]:
            continue
        name = _DISCOVER._get_name(item)
        if _DISCOVER._is_owned_object(name) and any(f"edge-{intent.stack}-" in name for intent in intents):
            stop_conditions.append(f"unmanaged owned application detected: {name}")
    for item in providers:
        item_id = _as_id(item)
        if not item_id or item_id in consumed["provider"]:
            continue
        name = _DISCOVER._get_name(item)
        if _DISCOVER._is_owned_object(name) and any(f"edge-{intent.stack}-" in name for intent in intents):
            stop_conditions.append(f"unmanaged owned provider detected: {name}")


def _process_intent(
    client: Any,
    intent: Any,
    applications: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    actions: list[ReconcileAction],
    issues: list[ReconcileIssue],
    stop_conditions: list[str],
    consumed: dict[str, set[str]],
    required_provider_ids: set[str],
    prereqs: _Prereqs,
    apply: bool,
) -> int:
    if intent.stack == "authentik-stack" and intent.auth_mode == "forwardAuth":
        stop_conditions.append(f"{intent.stack}/{intent.route}: Authentik self-route must not use forwardAuth")
        return 0
    if intent.auth_mode not in {"forwardAuth", "oidc"}:
        _handle_delete_reports_for_intent(intent, applications, providers, actions, consumed, stop_conditions)
        return 0
    if intent.auth_mode == "forwardAuth":
        app_obj, provider_obj, route_stops = _resolve_forwardauth_candidates(intent, applications, providers)
    else:
        if not _DISCOVER._oidc_route_supported(intent):
            issues.append(ReconcileIssue(
                code="AKR005",
                message=f"native OIDC route {intent.stack}/{intent.route} has no repo-managed Authentik mapping",
                manifest=intent.manifest, route=intent.route,
                object_kind="provider", object_name=intent.provider_name,
            ))
            return 0
        app_obj, provider_obj, route_stops = _resolve_oidc_candidates(intent, applications, providers)
    stop_conditions.extend(route_stops)
    provider_payload, payload_issue = _resolve_intent_provider_payload(
        intent, prereqs.auth_pk, prereqs.inval_pk, prereqs.signing_pk, prereqs.scope_ids,
    )
    if payload_issue is not None:
        issues.append(payload_issue)
        return 0
    provider_obj, wc, provider_id = _reconcile_provider_for_intent(
        client, intent, provider_obj, provider_payload, route_stops, stop_conditions, apply, actions, providers, consumed,
    )
    write_count = wc
    provider_id = _as_id(provider_obj) if provider_obj is not None else provider_id
    if provider_id:
        required_provider_ids.add(provider_id)
        consumed["provider"].add(provider_id)
    _check_app_provider_link(app_obj, provider_id, intent, consumed, stop_conditions)
    write_count += _reconcile_application_for_intent(
        client, intent, app_obj, _application_payload(intent, provider_id),
        route_stops, stop_conditions, apply, actions, applications, consumed,
    )
    return write_count


def _resolve_prerequisite_ids(
    client: Any,
    intents: list[Any],
    authorization_flow_slug_override: str | None,
    invalidation_flow_slug_override: str | None,
) -> tuple[_Prereqs | None, tuple[ReconcileIssue, ...] | None]:
    has_managed = any(intent.auth_mode in {"forwardAuth", "oidc"} for intent in intents)
    has_oidc = any(intent.auth_mode == "oidc" for intent in intents)
    auth_pk = inval_pk = None
    if has_managed:
        flow_ids, flow_issues = _resolve_proxy_flow_ids(
            client,
            authorization_flow_slug_override=authorization_flow_slug_override,
            invalidation_flow_slug_override=invalidation_flow_slug_override,
        )
        if flow_issues:
            return None, flow_issues
        assert flow_ids is not None
        auth_pk, inval_pk = flow_ids
    signing_pk: str | None = None
    scope_ids: tuple[str, ...] | None = None
    if has_oidc:
        signing_pk, signing_issue = _resolve_oidc_signing_key_id(
            client,
            signing_key_name_override=_resolve_slug_override(OIDC_SIGNING_KEY_NAME_ENV),
        )
        if signing_issue is not None:
            return None, (signing_issue,)
        assert signing_pk is not None
        raw_scope_ids, scope_mapping_issue = _resolve_oidc_scope_property_mapping_ids(client)
        if scope_mapping_issue is not None:
            return None, (scope_mapping_issue,)
        assert raw_scope_ids is not None
        scope_ids = list(raw_scope_ids)
    return _Prereqs(auth_pk=auth_pk, inval_pk=inval_pk, signing_pk=signing_pk, scope_ids=scope_ids), None


def reconcile_authentik(
    manifest_paths: list[Path],
    client: Any,
    *,
    apply: bool,
    authorization_flow_slug_override: str | None = None,
    invalidation_flow_slug_override: str | None = None,
) -> ReconcileResult:
    intents, validation_issues = _DISCOVER._build_route_intents(manifest_paths)
    if validation_issues:
        return ReconcileResult(
            apply=apply,
            actions=(),
            issues=tuple(_as_issue(issue) for issue in validation_issues),
            stop_conditions=(),
            request_methods=tuple(client.request_methods),
            write_count=0,
        )

    inventory, fetch_issue = _DISCOVER._fetch_authentik_inventory(client)
    if fetch_issue is not None:
        return ReconcileResult(
            apply=apply,
            actions=(),
            issues=(_as_issue(fetch_issue),),
            stop_conditions=(),
            request_methods=tuple(client.request_methods),
            write_count=0,
        )

    assert inventory is not None
    applications = list(inventory.applications)
    providers = list(inventory.providers)
    outposts = list(inventory.outposts)

    actions: list[ReconcileAction] = []
    issues: list[ReconcileIssue] = []
    stop_conditions: list[str] = []
    write_count = 0
    consumed: dict[str, set[str]] = {"application": set(), "provider": set(), "outpost": set()}
    required_provider_ids: set[str] = set()

    prereqs, prereq_issues = _resolve_prerequisite_ids(
        client, intents, authorization_flow_slug_override, invalidation_flow_slug_override,
    )
    if prereq_issues is not None:
        return ReconcileResult(
            apply=apply,
            actions=(),
            issues=prereq_issues,
            stop_conditions=(),
            request_methods=tuple(client.request_methods),
            write_count=0,
        )
    assert prereqs is not None

    intents = sorted(intents, key=lambda item: (item.stack, item.route, item.host))
    for intent in intents:
        write_count += _process_intent(
            client, intent, applications, providers, actions, issues,
            stop_conditions, consumed, required_provider_ids, prereqs, apply,
        )

    has_forwardauth = any(intent.auth_mode == "forwardAuth" for intent in intents)
    if has_forwardauth:
        outposts, wc = _reconcile_shared_outpost(
            client, outposts, required_provider_ids, apply, stop_conditions, actions, consumed,
        )
        write_count += wc

    _detect_unmanaged_orphans(applications, providers, intents, consumed, stop_conditions)

    stop_conditions = sorted(set(stop_conditions))
    if has_forwardauth and not apply:
        issues.extend(_validate_forwardauth_endpoint_serving(client, intents))

    actions.sort(key=lambda a: (a.stack, a.route, a.object_kind, a.object_name, a.operation))
    return ReconcileResult(
        apply=apply,
        actions=tuple(actions),
        issues=tuple(issues),
        stop_conditions=tuple(stop_conditions),
        request_methods=tuple(client.request_methods),
        write_count=write_count,
    )


def _print_reconcile_summary(result: ReconcileResult, args: Any) -> None:
    mode = "apply" if args.apply else "dry-run"
    print(f"Authentik reconciliation {mode} completed.")
    print(f"Actions: {len(result.actions)} (writes={result.write_count})")
    if result.issues:
        print(f"Issues: {len(result.issues)}")
        for issue in result.issues:
            print(f"- [{issue.code}] {issue.message}")
    if result.stop_conditions:
        print(f"Stop conditions: {len(result.stop_conditions)}")
        for stop in result.stop_conditions:
            print(f"- [STOP] {stop}")
    for action in result.actions:
        if action.operation == "noop":
            continue
        print(
            f"- [{action.operation}] {action.stack}/{action.route} "
            f"{action.object_kind} {action.object_name}: {action.reason}"
        )
    if any(action.operation == "delete-report" for action in result.actions):
        print("Note: delete actions are reported only and never applied by this tool.")


def main() -> int:
    args = parse_args()
    manifest_paths = _resolve_manifest_paths(args)

    token, token_issue = _resolve_token(args.token_env)
    if token_issue is not None:
        result = ReconcileResult(
            apply=args.apply,
            actions=(),
            issues=(token_issue,),
            stop_conditions=(),
            request_methods=(),
            write_count=0,
        )
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        else:
            print("Authentik reconciliation failed.")
            print(f"- [{token_issue.code}] {token_issue.message}")
        return 1

    client = AuthentikApiClient(
        base_url=args.authentik_url,
        token=token,
        verify_tls=not args.no_verify_tls,
    )
    result = reconcile_authentik(
        manifest_paths,
        client,
        apply=args.apply,
        authorization_flow_slug_override=_resolve_slug_override(AUTHORIZATION_FLOW_SLUG_ENV),
        invalidation_flow_slug_override=_resolve_slug_override(INVALIDATION_FLOW_SLUG_ENV),
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

    _print_reconcile_summary(result, args)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
