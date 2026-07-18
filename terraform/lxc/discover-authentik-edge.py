#!/usr/bin/env python3
"""Read-only Authentik discovery for EdgeManifest auth intent drift reporting."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse
import ssl
import urllib.request

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from edge_manifest import discover_edge_manifests, load_manifest, validate_manifests  # noqa: E402


def _default_authentik_url() -> str:
    configured_host = os.environ.get("LAB_FQDN_AUTHENTIK", "").strip()
    if configured_host:
        if "://" in configured_host:
            return configured_host.rstrip("/")
        return f"https://{configured_host}"
    return "https://authentik.lab.gibbsgreatly.xyz"


DEFAULT_AUTHENTIK_URL = _default_authentik_url()
DEFAULT_TOKEN_ENV = "AUTHENTIK_SUPERUSER_API_TOKEN"
OWNED_NAME_PREFIX = "edge-"
LEGACY_MANAGED_SHARED_FORWARD_OUTPOST = "edge-forwardauth-outpost"
LEGACY_SHARED_FORWARD_PROVIDER = "traefik-forwardauth-provider"
LEGACY_SHARED_EMBEDDED_OUTPOST = "authentik Embedded Outpost"
# Prefer the embedded outpost because it is served directly by the Authentik server.
SHARED_FORWARD_OUTPOST = LEGACY_SHARED_EMBEDDED_OUTPOST

OIDC_ROUTE_CLIENT_IDS: dict[tuple[str, str], tuple[str, str]] = {
    ("harbor-stack", "harbor"): ("HARBOR_OIDC_CLIENT_ID", "harbor"),
    ("monitoring-stack", "grafana"): ("GRAFANA_OAUTH_CLIENT_ID", "grafana"),
    ("portainer-stack", "portainer"): ("PORTAINER_OAUTH_CLIENT_ID", "portainer"),
    ("technitium-stack", "technitium"): ("TECHNITIUM_OIDC_CLIENT_ID", "technitium"),
    ("ai-services-stack", "openwebui"): ("OPENWEBUI_OIDC_CLIENT_ID", "openwebui"),
}
OIDC_ROUTE_CLIENT_SECRETS: dict[tuple[str, str], str] = {
    ("harbor-stack", "harbor"): "HARBOR_OIDC_CLIENT_SECRET",
    ("monitoring-stack", "grafana"): "GRAFANA_OAUTH_CLIENT_SECRET",
    ("portainer-stack", "portainer"): "PORTAINER_OAUTH_CLIENT_SECRET",
    ("technitium-stack", "technitium"): "TECHNITIUM_OIDC_CLIENT_SECRET",
    ("ai-services-stack", "openwebui"): "OPENWEBUI_OIDC_CLIENT_SECRET",
}


@dataclass(frozen=True)
class DiscoveryIssue:
    """Machine-readable discovery issue."""

    code: str
    message: str
    manifest: str | None = None
    route: str | None = None
    object_kind: str | None = None
    object_name: str | None = None

    def to_dict(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class ObjectRef:
    """Stable object identifier for later reconciliation."""

    kind: str
    id: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class RouteDrift:
    """Discovery classification for one route."""

    manifest: str
    stack: str
    route: str
    host: str
    auth_mode: str
    classification: str
    reasons: tuple[str, ...]
    identifiers: tuple[ObjectRef, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest": self.manifest,
            "stack": self.stack,
            "route": self.route,
            "host": self.host,
            "auth_mode": self.auth_mode,
            "classification": self.classification,
            "reasons": list(self.reasons),
            "identifiers": [identifier.to_dict() for identifier in self.identifiers],
        }


@dataclass(frozen=True)
class DiscoveryResult:
    """Full read-only Authentik discovery report."""

    route_results: tuple[RouteDrift, ...]
    unmanaged: tuple[ObjectRef, ...]
    issues: tuple[DiscoveryIssue, ...]
    stop_conditions: tuple[str, ...]
    request_methods: tuple[str, ...]

    @property
    def ok(self) -> bool:
        if self.issues or self.stop_conditions:
            return False
        return all(route.classification == "matching" for route in self.route_results)

    def to_dict(self) -> dict[str, object]:
        buckets = {"matching": 0, "missing": 0, "differing": 0, "ambiguous": 0}
        for route in self.route_results:
            buckets.setdefault(route.classification, 0)
            buckets[route.classification] += 1
        return {
            "status": "passed" if self.ok else "failed",
            "route_count": len(self.route_results),
            "classification_counts": buckets,
            "unmanaged_count": len(self.unmanaged),
            "issue_count": len(self.issues),
            "stop_condition_count": len(self.stop_conditions),
            "route_results": [route.to_dict() for route in self.route_results],
            "unmanaged": [obj.to_dict() for obj in self.unmanaged],
            "issues": [issue.to_dict() for issue in self.issues],
            "stop_conditions": list(self.stop_conditions),
            "request_methods": list(self.request_methods),
        }


@dataclass(frozen=True)
class RouteIntent:
    """Expected auth ownership intent derived from one manifest route."""

    manifest: str
    stack: str
    route: str
    host: str
    auth_mode: str
    app_name: str
    app_slug: str
    provider_name: str
    outpost_name: str


@dataclass
class AuthentikInventory:
    """Fetched Authentik objects for drift classification."""

    applications: list[dict[str, Any]]
    providers: list[dict[str, Any]]
    outposts: list[dict[str, Any]]


@dataclass
class _RouteClassification:
    """Internal classification result for one route intent."""

    classification: str
    reasons: list[str]
    identifiers: list[ObjectRef]
    stop_condition: str | None


class AuthentikApiClient:
    """Minimal read-only Authentik API client."""

    def __init__(self, base_url: str, token: str, verify_tls: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify_tls = verify_tls
        self.request_methods: list[str] = []

    def fetch_applications(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/core/applications/")

    def search_applications(self, query: str) -> list[dict[str, Any]]:
        params = urlencode({"search": query})
        return self._get_paginated(f"/api/v3/core/applications/?{params}")

    def fetch_proxy_providers(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/providers/proxy/")

    def fetch_oauth2_providers(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/providers/oauth2/")

    def fetch_outposts(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/outposts/instances/")

    def _get_paginated(self, path: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        separator = "&" if "?" in path else "?"
        next_url: str | None = f"{self.base_url}{path}{separator}page_size=200"

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

    def _request_json(self, url: str, method: str) -> Any:
        self.request_methods.append(method)
        request = urllib.request.Request(
            url,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
        )
        context = None
        if not self.verify_tls:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        else:
            extra_ca = os.environ.get("AUTHENTIK_EXTRA_CA")
            if extra_ca:
                context = ssl.create_default_context()
                context.load_verify_locations(cafile=extra_ca)

        with urllib.request.urlopen(request, context=context) as response:  # nosec B310 — internal Authentik API on private SDN
            return json.loads(response.read().decode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Authentik discovery for stack-owned edge manifests. "
            "Reports drift only; never writes."
        )
    )
    parser.add_argument(
        "manifests",
        nargs="*",
        type=Path,
        help=(
            "Optional explicit manifest files to discover. "
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
        help="Base Authentik URL used for read-only API calls.",
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help="Environment variable name containing the Authentik API token.",
    )
    parser.add_argument(
        "--no-verify-tls",
        action="store_true",
        help="Disable TLS certificate verification (for self-signed/bootstrap certificates).",
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
    return discover_edge_manifests(args.stacks_dir.resolve())


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def _build_route_intents(manifest_paths: list[Path]) -> tuple[list[RouteIntent], list[DiscoveryIssue]]:
    validation = validate_manifests(manifest_paths)
    if not validation.ok:
        issues = [
            DiscoveryIssue(
                code=issue.code,
                message=issue.message,
                manifest=issue.manifest,
                route=issue.route,
            )
            for issue in validation.issues
        ]
        return [], issues

    intents: list[RouteIntent] = []
    for path in sorted(manifest_paths):
        doc = load_manifest(path)
        manifest = str(path)
        metadata = doc["metadata"]
        stack = str(metadata["stack"])
        for route in doc["spec"]["routes"]:
            route_name = str(route["name"])
            host = str(route["host"])
            auth_mode = str(route["auth"]["mode"])
            name_base = _slugify(f"{stack}-{route_name}")
            intents.append(
                RouteIntent(
                    manifest=manifest,
                    stack=stack,
                    route=route_name,
                    host=host,
                    auth_mode=auth_mode,
                    app_name=f"{OWNED_NAME_PREFIX}{name_base}-app",
                    app_slug=f"{OWNED_NAME_PREFIX}{name_base}",
                    provider_name=f"{OWNED_NAME_PREFIX}{name_base}-provider",
                    outpost_name=SHARED_FORWARD_OUTPOST,
                )
            )
    return intents, []


def _as_id(value: Any) -> str | None:
    if isinstance(value, (int, str)):
        text = str(value).strip()
        return text or None
    return None


def _normalize_url_host(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    parsed = urlparse(text if "://" in text else f"https://{text}")
    host = parsed.hostname or ""
    return host.lower()


def _pick_candidates(items: list[dict[str, Any]], predicates: list[Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for item in items:
        item_id = _as_id(item.get("pk") or item.get("id"))
        if item_id is None:
            continue
        for predicate in predicates:
            if predicate(item):
                if item_id not in seen:
                    selected.append(item)
                    seen.add(item_id)
                break
    return selected


def _get_name(item: dict[str, Any]) -> str:
    raw = item.get("name")
    return raw if isinstance(raw, str) else ""


def _get_provider_id_from_application(app: dict[str, Any]) -> str | None:
    provider = app.get("provider")
    if isinstance(provider, dict):
        return _as_id(provider.get("pk") or provider.get("id"))
    return _as_id(provider)


def _provider_redirect_uris(provider: dict[str, Any]) -> tuple[str, ...]:
    redirect_uris = provider.get("redirect_uris")
    if not isinstance(redirect_uris, list):
        return ()

    values: list[str] = []
    for redirect_uri in redirect_uris:
        if isinstance(redirect_uri, dict):
            url = redirect_uri.get("url")
            if isinstance(url, str) and url.strip():
                values.append(url.strip())
        elif isinstance(redirect_uri, str) and redirect_uri.strip():
            values.append(redirect_uri.strip())
    return tuple(values)


def _provider_matches_host(provider: dict[str, Any], host: str) -> bool:
    external_host = _normalize_url_host(provider.get("external_host"))
    if external_host == host:
        return True
    return any(_normalize_url_host(uri) == host for uri in _provider_redirect_uris(provider))


def _oidc_route_key(intent: RouteIntent) -> tuple[str, str]:
    return (intent.stack, intent.route)


def _oidc_route_supported(intent: RouteIntent) -> bool:
    return _oidc_route_key(intent) in OIDC_ROUTE_CLIENT_IDS


def _oidc_client_id(intent: RouteIntent) -> str | None:
    config = OIDC_ROUTE_CLIENT_IDS.get(_oidc_route_key(intent))
    if config is None:
        return None
    env_name, default_value = config
    return os.environ.get(env_name, "").strip() or default_value


def _oidc_client_secret_env(intent: RouteIntent) -> str | None:
    return OIDC_ROUTE_CLIENT_SECRETS.get(_oidc_route_key(intent))


def _oidc_base_url(intent: RouteIntent) -> str:
    if _oidc_route_key(intent) == ("harbor-stack", "harbor"):
        external_url = os.environ.get("HARBOR_EXTERNAL_URL", "").strip()
        if external_url:
            parsed = urlparse(external_url if "://" in external_url else f"https://{external_url}")
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"

    return f"https://{intent.host}"


def _oidc_redirect_uris(intent: RouteIntent) -> tuple[str, ...]:
    base_url = _oidc_base_url(intent)
    if _oidc_route_key(intent) == ("harbor-stack", "harbor"):
        return (f"{base_url}/c/oidc/callback",)
    if _oidc_route_key(intent) == ("monitoring-stack", "grafana"):
        return (f"{base_url}/login/generic_oauth",)
    if _oidc_route_key(intent) == ("portainer-stack", "portainer"):
        return (base_url,)
    if _oidc_route_key(intent) == ("technitium-stack", "technitium"):
        return (f"{base_url}/sso/callback",)
    if _oidc_route_key(intent) == ("ai-services-stack", "openwebui"):
        return (f"{base_url}/oauth/oidc/callback",)
    return ()


def _provider_references(outpost: dict[str, Any]) -> set[str]:
    providers = outpost.get("providers")
    values: set[str] = set()
    if not isinstance(providers, list):
        return values
    for provider in providers:
        if isinstance(provider, dict):
            provider_id = _as_id(provider.get("pk") or provider.get("id"))
        else:
            provider_id = _as_id(provider)
        if provider_id:
            values.add(provider_id)
    return values


def _is_owned_object(name: str) -> bool:
    return bool(name and name.startswith(OWNED_NAME_PREFIX))


def _dedupe_provider_records(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate provider records returned across provider endpoints."""
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for provider in providers:
        provider_id = _as_id(provider.get("pk") or provider.get("id"))
        provider_name = _get_name(provider)
        key = (provider_id or "", provider_name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(provider)
    return deduped


def _dedupe_application_records(applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for application in applications:
        app_id = _as_id(application.get("pk") or application.get("id"))
        app_name = _get_name(application)
        app_slug = str(application.get("slug", "")).strip()
        key = (app_id or "", app_name, app_slug)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(application)
    return deduped


def _application_search_queries(intent: RouteIntent) -> list[str]:
    host = _normalize_url_host(_oidc_base_url(intent)) if intent.auth_mode == "oidc" else intent.host.lower()
    return [intent.app_slug, intent.app_name, host]


def _augment_inventory_with_targeted_application_searches(
    client: AuthentikApiClient,
    intents: list[RouteIntent],
    inventory: AuthentikInventory,
) -> DiscoveryIssue | None:
    seen_queries: set[str] = set()
    augmented = list(inventory.applications)
    try:
        for intent in intents:
            for query in _application_search_queries(intent):
                if not query or query in seen_queries:
                    continue
                seen_queries.add(query)
                augmented.extend(client.search_applications(query))
    except Exception as exc:
        return DiscoveryIssue(
            code="AKD101",
            message=f"failed to query Authentik application search endpoint: {exc}",
        )
    inventory.applications = _dedupe_application_records(augmented)
    return None


def _fetch_authentik_inventory(
    client: AuthentikApiClient,
) -> tuple[AuthentikInventory | None, DiscoveryIssue | None]:
    """Fetch all relevant Authentik objects read-only. Returns inventory or a stop issue."""
    try:
        applications = client.fetch_applications()
        providers = client.fetch_proxy_providers()
        providers.extend(client.fetch_oauth2_providers())
        providers = _dedupe_provider_records(providers)
        outposts = [
            outpost
            for outpost in client.fetch_outposts()
            if str(outpost.get("type", "")).lower() in {"proxy", ""}
        ]
    except Exception as exc:
        return None, DiscoveryIssue(
            code="AKD100",
            message=f"failed to query Authentik read-only endpoints: {exc}",
        )
    return AuthentikInventory(applications=applications, providers=providers, outposts=outposts), None


def _check_provider_match(
    intent: RouteIntent,
    provider: dict[str, Any] | None,
    host: str,
) -> tuple[str | None, list[str], list[ObjectRef], bool]:
    """Validate a matched proxy provider against the intent. Returns (provider_id, reasons, identifiers, differing)."""
    if provider is None:
        return None, [], [], False
    provider_id = _as_id(provider.get("pk") or provider.get("id"))
    provider_name = _get_name(provider)
    reasons: list[str] = []
    identifiers: list[ObjectRef] = []
    differing = False
    if provider_id:
        identifiers.append(ObjectRef(kind="provider", id=provider_id, name=provider_name))
    if provider_name != intent.provider_name:
        differing = True
        reasons.append(f"provider name differs (expected {intent.provider_name}, found {provider_name})")
    provider_host = _normalize_url_host(provider.get("external_host"))
    if provider_host and provider_host != host:
        differing = True
        reasons.append(f"provider external_host differs (expected {intent.host}, found {provider_host})")
    return provider_id, reasons, identifiers, differing


def _check_app_match(
    intent: RouteIntent,
    app: dict[str, Any] | None,
    host: str,
    provider_id_for_links: str | None,
) -> tuple[list[str], list[ObjectRef], bool]:
    """Validate a matched application against the intent. Returns (reasons, identifiers, differing)."""
    if app is None:
        return [], [], False
    app_id = _as_id(app.get("pk") or app.get("id"))
    app_name = _get_name(app)
    reasons: list[str] = []
    identifiers: list[ObjectRef] = []
    differing = False
    if app_id:
        identifiers.append(ObjectRef(kind="application", id=app_id, name=app_name))
    if app_name != intent.app_name:
        differing = True
        reasons.append(f"application name differs (expected {intent.app_name}, found {app_name})")
    launch_host = _normalize_url_host(app.get("meta_launch_url") or app.get("launch_url"))
    if launch_host and launch_host != host:
        differing = True
        reasons.append(f"application launch host differs (expected {intent.host}, found {launch_host})")
    linked_provider_id = _get_provider_id_from_application(app)
    if provider_id_for_links and linked_provider_id and linked_provider_id != provider_id_for_links:
        differing = True
        reasons.append("application points to a different proxy provider")
    return reasons, identifiers, differing


def _check_outpost_match(
    intent: RouteIntent,
    outpost: dict[str, Any] | None,
    provider_id_for_links: str | None,
) -> tuple[list[str], list[ObjectRef], bool, bool]:
    """Validate a matched outpost against the intent. Returns (reasons, identifiers, differing, missing)."""
    if outpost is None:
        return ["outpost is missing"], [], False, True
    outpost_id = _as_id(outpost.get("pk") or outpost.get("id"))
    outpost_name = _get_name(outpost)
    reasons: list[str] = []
    identifiers: list[ObjectRef] = []
    differing = False
    if outpost_id:
        identifiers.append(ObjectRef(kind="outpost", id=outpost_id, name=outpost_name))
    if outpost_name != intent.outpost_name:
        differing = True
        reasons.append(f"outpost name differs (expected {intent.outpost_name}, found {outpost_name})")
    if provider_id_for_links and provider_id_for_links not in _provider_references(outpost):
        differing = True
        reasons.append("outpost is not linked to expected proxy provider")
    return reasons, identifiers, differing, False


def _resolve_app_provider_candidates(
    intent: RouteIntent,
    inventory: AuthentikInventory,
    host: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool, list[str]]:
    """Pick the single best app and provider for the intent. Returns (app, provider, ambiguous, reasons)."""
    app_candidates = _pick_candidates(
        inventory.applications,
        [
            lambda item, expected_name=intent.app_name: _get_name(item) == expected_name,
            lambda item, expected_slug=intent.app_slug: str(item.get("slug", "")) == expected_slug,
            lambda item, expected_host=host: _normalize_url_host(
                item.get("meta_launch_url") or item.get("launch_url")
            )
            == expected_host,
        ],
    )
    provider_candidates = _pick_candidates(
        inventory.providers,
        [
            lambda item, expected_name=intent.provider_name: _get_name(item) == expected_name,
            lambda item, expected_host=host: _provider_matches_host(item, expected_host),
        ],
    )
    reasons: list[str] = []
    ambiguous = False
    if len(app_candidates) > 1:
        ambiguous = True
        reasons.append("multiple application candidates matched this route")
    if len(provider_candidates) > 1:
        ambiguous = True
        reasons.append("multiple proxy provider candidates matched this route")
    app = app_candidates[0] if len(app_candidates) == 1 else None
    provider = provider_candidates[0] if len(provider_candidates) == 1 else None
    return app, provider, ambiguous, reasons


def _classify_forward_auth_route(
    intent: RouteIntent,
    inventory: AuthentikInventory,
) -> _RouteClassification:
    """Classify a forwardAuth route against the Authentik inventory."""
    host = intent.host.lower()
    app, provider, ambiguous, reasons = _resolve_app_provider_candidates(intent, inventory, host)
    identifiers: list[ObjectRef] = []
    missing = False
    differing = False

    if app is None:
        missing = True
        reasons.append("application is missing")
    if provider is None:
        missing = True
        reasons.append("proxy provider is missing")

    provider_id_for_links, prov_reasons, prov_ids, prov_differing = _check_provider_match(intent, provider, host)
    reasons.extend(prov_reasons)
    identifiers.extend(prov_ids)
    if prov_differing:
        differing = True

    app_reasons, app_ids, app_differing = _check_app_match(intent, app, host, provider_id_for_links)
    reasons.extend(app_reasons)
    identifiers.extend(app_ids)
    if app_differing:
        differing = True

    named_outpost_candidates = _pick_candidates(
        inventory.outposts,
        [
            lambda item, expected_name=intent.outpost_name: _get_name(item) == expected_name,
        ],
    )
    if len(named_outpost_candidates) > 1:
        ambiguous = True
        reasons.append("multiple named outpost candidates matched this route")

    outpost: dict[str, Any] | None
    if len(named_outpost_candidates) == 1:
        outpost = named_outpost_candidates[0]
    else:
        linked_outpost_candidates = _pick_candidates(
            inventory.outposts,
            [
                lambda item, linked_provider=provider_id_for_links: linked_provider is not None
                and linked_provider in _provider_references(item),
            ],
        )
        if len(linked_outpost_candidates) > 1:
            ambiguous = True
            reasons.append("multiple linked outpost candidates matched this route")
        outpost = linked_outpost_candidates[0] if len(linked_outpost_candidates) == 1 else None
    out_reasons, out_ids, out_differing, out_missing = _check_outpost_match(intent, outpost, provider_id_for_links)
    reasons.extend(out_reasons)
    identifiers.extend(out_ids)
    if out_differing:
        differing = True
    if out_missing:
        missing = True

    # Compatibility mode for the existing shared Traefik forward-auth model.
    # If route-owned objects are absent but legacy shared provider/outpost are
    # present and linked, classify as matching to avoid false migration drift.
    if not ambiguous and missing and not differing:
        legacy_provider_candidates = _pick_candidates(
            inventory.providers,
            [
                lambda item: _get_name(item) == LEGACY_SHARED_FORWARD_PROVIDER,
                lambda item: str(item.get("mode", "")).lower() == "forward_domain"
                and bool(item.get("intercept_header_auth", False)),
            ],
        )
        if len(legacy_provider_candidates) == 1:
            legacy_provider = legacy_provider_candidates[0]
            legacy_provider_id = _as_id(legacy_provider.get("pk") or legacy_provider.get("id"))
            legacy_outpost_candidates = _pick_candidates(
                inventory.outposts,
                [
                    lambda item: _get_name(item) == LEGACY_SHARED_EMBEDDED_OUTPOST,
                    lambda item, linked_provider=legacy_provider_id: linked_provider is not None
                    and linked_provider in _provider_references(item),
                ],
            )
            if len(legacy_outpost_candidates) == 1 and legacy_provider_id is not None:
                legacy_outpost = legacy_outpost_candidates[0]
                legacy_outpost_id = _as_id(legacy_outpost.get("pk") or legacy_outpost.get("id"))
                legacy_identifiers = [
                    ObjectRef(
                        kind="provider",
                        id=legacy_provider_id,
                        name=_get_name(legacy_provider),
                    )
                ]
                if legacy_outpost_id is not None:
                    legacy_identifiers.append(
                        ObjectRef(
                            kind="outpost",
                            id=legacy_outpost_id,
                            name=_get_name(legacy_outpost),
                        )
                    )
                return _RouteClassification(
                    classification="matching",
                    reasons=[
                        "route is covered by legacy shared Traefik forward-auth provider/outpost"
                    ],
                    identifiers=legacy_identifiers,
                    stop_condition=None,
                )

    stop_condition: str | None = None
    if ambiguous:
        classification = "ambiguous"
        stop_condition = f"{intent.stack}/{intent.route}: existing object names cannot be mapped safely"
    elif missing:
        classification = "missing"
    elif differing:
        classification = "differing"
    else:
        classification = "matching"
        reasons.append("discovered objects match route auth intent")

    return _RouteClassification(
        classification=classification,
        reasons=reasons,
        identifiers=identifiers,
        stop_condition=stop_condition,
    )


def _check_oidc_provider_match(
    intent: RouteIntent,
    provider: dict[str, Any] | None,
) -> tuple[str | None, list[str], list[ObjectRef], bool]:
    if provider is None:
        return None, [], [], False

    provider_id = _as_id(provider.get("pk") or provider.get("id"))
    provider_name = _get_name(provider)
    reasons: list[str] = []
    identifiers: list[ObjectRef] = []
    differing = False
    if provider_id:
        identifiers.append(ObjectRef(kind="provider", id=provider_id, name=provider_name))
    if provider_name != intent.provider_name:
        differing = True
        reasons.append(f"provider name differs (expected {intent.provider_name}, found {provider_name})")

    expected_client_id = _oidc_client_id(intent)
    actual_client_id = provider.get("client_id") if isinstance(provider.get("client_id"), str) else ""
    if expected_client_id and actual_client_id and actual_client_id != expected_client_id:
        differing = True
        reasons.append(f"provider client_id differs (expected {expected_client_id}, found {actual_client_id})")

    expected_redirects = set(_oidc_redirect_uris(intent))
    actual_redirects = set(_provider_redirect_uris(provider))
    if expected_redirects and not expected_redirects.issubset(actual_redirects):
        differing = True
        reasons.append("provider redirect_uris differ from expected OIDC callback set")

    return provider_id, reasons, identifiers, differing


def _resolve_oidc_candidates(
    intent: RouteIntent,
    inventory: AuthentikInventory,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool, list[str]]:
    host = _normalize_url_host(_oidc_base_url(intent)) or intent.host.lower()
    expected_client_id = _oidc_client_id(intent)
    app_candidates = _pick_candidates(
        inventory.applications,
        [
            lambda item, expected_name=intent.app_name: _get_name(item) == expected_name,
            lambda item, expected_slug=intent.app_slug: str(item.get("slug", "")) == expected_slug,
            lambda item, expected_host=host: _normalize_url_host(
                item.get("meta_launch_url") or item.get("launch_url")
            )
            == expected_host,
        ],
    )
    provider_candidates = _pick_candidates(
        inventory.providers,
        [
            lambda item, expected_name=intent.provider_name: _get_name(item) == expected_name,
            lambda item, expected_host=host: _provider_matches_host(item, expected_host),
            lambda item, expected_client_id=expected_client_id: bool(expected_client_id)
            and str(item.get("client_id", "")) == expected_client_id,
        ],
    )

    reasons: list[str] = []
    ambiguous = False
    if len(app_candidates) > 1:
        ambiguous = True
        reasons.append("multiple application candidates matched this route")
    if len(provider_candidates) > 1:
        ambiguous = True
        reasons.append("multiple OIDC provider candidates matched this route")

    app = app_candidates[0] if len(app_candidates) == 1 else None
    provider = provider_candidates[0] if len(provider_candidates) == 1 else None
    return app, provider, ambiguous, reasons


def _classify_oidc_route(
    intent: RouteIntent,
    inventory: AuthentikInventory,
) -> _RouteClassification:
    if not _oidc_route_supported(intent):
        return _RouteClassification(
            classification="differing",
            reasons=["native OIDC route has no repo-managed Authentik mapping"],
            identifiers=[],
            stop_condition=None,
        )

    app, provider, ambiguous, reasons = _resolve_oidc_candidates(intent, inventory)
    identifiers: list[ObjectRef] = []
    missing = False
    differing = False

    if app is None:
        missing = True
        reasons.append("application is missing")
    if provider is None:
        missing = True
        reasons.append("OIDC provider is missing")

    provider_id_for_links, prov_reasons, prov_ids, prov_differing = _check_oidc_provider_match(intent, provider)
    reasons.extend(prov_reasons)
    identifiers.extend(prov_ids)
    if prov_differing:
        differing = True

    # launch_url is always the public FQDN (intent.host), not _oidc_base_url —
    # for Harbor in non-prod, _oidc_base_url returns an internal IP used only
    # for the OIDC redirect_uri, not for the Authentik app catalogue link.
    expected_launch_host = intent.host.lower()
    app_reasons, app_ids, app_differing = _check_app_match(
        intent,
        app,
        expected_launch_host,
        provider_id_for_links,
    )
    reasons.extend(app_reasons)
    identifiers.extend(app_ids)
    if app_differing:
        differing = True

    stop_condition: str | None = None
    if ambiguous:
        classification = "ambiguous"
        stop_condition = f"{intent.stack}/{intent.route}: existing object names cannot be mapped safely"
    elif missing:
        classification = "missing"
    elif differing:
        classification = "differing"
    else:
        classification = "matching"
        reasons.append("discovered objects match route auth intent")

    return _RouteClassification(
        classification=classification,
        reasons=reasons,
        identifiers=identifiers,
        stop_condition=stop_condition,
    )


def _classify_non_managed_auth_route(
    intent: RouteIntent,
    inventory: AuthentikInventory,
) -> _RouteClassification:
    """Classify a non-forwardAuth route: any matching Authentik objects are unexpected."""
    host = intent.host.lower()
    app_candidates = _pick_candidates(
        inventory.applications,
        [
            lambda item, expected_name=intent.app_name: _get_name(item) == expected_name,
            lambda item, expected_slug=intent.app_slug: str(item.get("slug", "")) == expected_slug,
            lambda item, expected_host=host: _normalize_url_host(
                item.get("meta_launch_url") or item.get("launch_url")
            )
            == expected_host,
        ],
    )
    provider_candidates = _pick_candidates(
        inventory.providers,
        [
            lambda item, expected_name=intent.provider_name: _get_name(item) == expected_name,
            lambda item, expected_host=host: _normalize_url_host(item.get("external_host"))
            == expected_host,
        ],
    )

    reasons: list[str] = []
    ambiguous = False
    stop_condition: str | None = None

    if len(app_candidates) > 1:
        ambiguous = True
        reasons.append("multiple application candidates matched this route")
    if len(provider_candidates) > 1:
        ambiguous = True
        reasons.append("multiple proxy provider candidates matched this route")

    if ambiguous:
        stop_condition = f"{intent.stack}/{intent.route}: existing object names cannot be mapped safely"
        return _RouteClassification(
            classification="ambiguous",
            reasons=reasons,
            identifiers=[],
            stop_condition=stop_condition,
        )

    app: dict[str, Any] | None = app_candidates[0] if len(app_candidates) == 1 else None
    provider: dict[str, Any] | None = provider_candidates[0] if len(provider_candidates) == 1 else None

    if app is not None or provider is not None:
        app_name = _get_name(app) if app is not None else ""
        provider_name = _get_name(provider) if provider is not None else ""
        if app_name == "Traefik Dashboard" and provider_name == LEGACY_SHARED_FORWARD_PROVIDER:
            return _RouteClassification(
                classification="matching",
                reasons=[
                    "legacy shared Traefik forward-auth app/provider are retained for compatibility"
                ],
                identifiers=[],
                stop_condition=None,
            )

    if app is not None or provider is not None:
        return _RouteClassification(
            classification="differing",
            reasons=[
                "route auth mode does not require managed Authentik objects, "
                "but matching objects already exist"
            ],
            identifiers=[],
            stop_condition=None,
        )

    return _RouteClassification(
        classification="matching",
        reasons=["discovered objects match route auth intent"],
        identifiers=[],
        stop_condition=None,
    )


def _classify_route_intent(
    intent: RouteIntent,
    inventory: AuthentikInventory,
) -> _RouteClassification:
    """Dispatch to the appropriate classifier based on auth mode."""
    if intent.auth_mode == "forwardAuth":
        return _classify_forward_auth_route(intent, inventory)
    if intent.auth_mode == "oidc":
        return _classify_oidc_route(intent, inventory)
    return _classify_non_managed_auth_route(intent, inventory)


def _find_unmanaged_owned_objects(
    inventory: AuthentikInventory,
    consumed: dict[str, set[str]],
) -> list[ObjectRef]:
    """Return owned-prefix objects not consumed by any route classification."""
    unmanaged: list[ObjectRef] = []
    for kind, objects in (
        ("application", inventory.applications),
        ("provider", inventory.providers),
        ("outpost", inventory.outposts),
    ):
        consumed_ids = consumed.get(kind, set())
        for item in objects:
            object_id = _as_id(item.get("pk") or item.get("id"))
            if object_id is None or object_id in consumed_ids:
                continue
            name = _get_name(item)
            if _is_owned_object(name):
                unmanaged.append(ObjectRef(kind=kind, id=object_id, name=name))
    return unmanaged


def discover_authentik_drift(
    manifest_paths: list[Path],
    client: AuthentikApiClient,
) -> DiscoveryResult:
    """Orchestrate read-only discovery and classify drift against route auth intent."""
    intents, issues = _build_route_intents(manifest_paths)
    if issues:
        return DiscoveryResult(
            route_results=(),
            unmanaged=(),
            issues=tuple(issues),
            stop_conditions=(),
            request_methods=tuple(client.request_methods),
        )

    inventory, fetch_issue = _fetch_authentik_inventory(client)
    if fetch_issue:
        return DiscoveryResult(
            route_results=(),
            unmanaged=(),
            issues=(fetch_issue,),
            stop_conditions=(),
            request_methods=tuple(client.request_methods),
        )

    search_issue = _augment_inventory_with_targeted_application_searches(client, intents, inventory)
    if search_issue:
        return DiscoveryResult(
            route_results=(),
            unmanaged=(),
            issues=(search_issue,),
            stop_conditions=(),
            request_methods=tuple(client.request_methods),
        )

    route_results: list[RouteDrift] = []
    stop_conditions: list[str] = []

    for intent in intents:
        cls_result = _classify_route_intent(intent, inventory)
        if cls_result.stop_condition:
            stop_conditions.append(cls_result.stop_condition)
        route_results.append(
            RouteDrift(
                manifest=intent.manifest,
                stack=intent.stack,
                route=intent.route,
                host=intent.host,
                auth_mode=intent.auth_mode,
                classification=cls_result.classification,
                reasons=tuple(cls_result.reasons),
                identifiers=tuple(
                    sorted(cls_result.identifiers, key=lambda obj: (obj.kind, obj.name, obj.id))
                ),
            )
        )

    consumed: dict[str, set[str]] = {"application": set(), "provider": set(), "outpost": set()}
    for rd in route_results:
        for obj in rd.identifiers:
            consumed[obj.kind].add(obj.id)
    unmanaged = _find_unmanaged_owned_objects(inventory, consumed)
    unmanaged.sort(key=lambda obj: (obj.kind, obj.name, obj.id))
    route_results.sort(key=lambda route: (route.stack, route.route, route.host))

    return DiscoveryResult(
        route_results=tuple(route_results),
        unmanaged=tuple(unmanaged),
        issues=(),
        stop_conditions=tuple(sorted(set(stop_conditions))),
        request_methods=tuple(client.request_methods),
    )


def _resolve_token(token_env: str) -> tuple[str | None, DiscoveryIssue | None]:
    token = os.environ.get(token_env, "").strip()
    if token:
        return token, None
    return None, DiscoveryIssue(
        code="AKD001",
        message=(
            f"missing Authentik token in environment variable {token_env}. "
            "Run with ./with-secrets so SOPS-backed secrets are injected "
            "(example: ./with-secrets terraform/lxc/discover-authentik-edge.py --json)."
        ),
    )


def main() -> int:
    args = parse_args()
    manifest_paths = _resolve_manifest_paths(args)

    token, token_issue = _resolve_token(args.token_env)
    if token_issue is not None:
        result = DiscoveryResult(
            route_results=(),
            unmanaged=(),
            issues=(token_issue,),
            stop_conditions=(),
            request_methods=(),
        )
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        else:
            print("Authentik discovery failed.")
            print(f"- [{token_issue.code}] {token_issue.message}")
        return 1

    client = AuthentikApiClient(
        base_url=args.authentik_url,
        token=token,
        verify_tls=not args.no_verify_tls,
    )
    result = discover_authentik_drift(manifest_paths, client)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

    if result.ok:
        print("Authentik discovery passed.")
        print(f"Routes checked: {len(result.route_results)}")
        print("Classifications: matching only")
        return 0

    print("Authentik discovery reported drift.")
    print(f"Routes checked: {len(result.route_results)}")
    print(f"Stop conditions: {len(result.stop_conditions)}")
    print(f"Issues: {len(result.issues)}")
    for issue in result.issues:
        print(f"- [{issue.code}] {issue.message}")
    for stop in result.stop_conditions:
        print(f"- [STOP] {stop}")
    for route in result.route_results:
        if route.classification == "matching":
            continue
        print(
            f"- [{route.classification}] {route.stack}/{route.route} ({route.host}): "
            f"{'; '.join(route.reasons)}"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
