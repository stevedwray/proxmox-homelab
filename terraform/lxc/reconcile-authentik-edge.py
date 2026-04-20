#!/usr/bin/env python3
"""Create/update-only Authentik reconciliation for EdgeManifest auth intent."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
import ssl
from typing import Any
from urllib.parse import urljoin
import urllib.request


DEFAULT_AUTHENTIK_URL = "https://authentik.lab.gibbsgreatly.xyz"
DEFAULT_TOKEN_ENV = "AUTHENTIK_SUPERUSER_API_TOKEN"
COOKIE_DOMAIN = ".lab.gibbsgreatly.xyz"
SHARED_OUTPOST_TYPE = "proxy"

SCRIPT_DIR = Path(__file__).resolve().parent
DISCOVER_MODULE_PATH = SCRIPT_DIR / "discover-authentik-edge.py"

_DISCOVER_SPEC = importlib.util.spec_from_file_location("discover_authentik_edge", DISCOVER_MODULE_PATH)
if _DISCOVER_SPEC is None or _DISCOVER_SPEC.loader is None:
    raise RuntimeError("failed to load discover-authentik-edge.py")
_DISCOVER = importlib.util.module_from_spec(_DISCOVER_SPEC)
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

    def fetch_outposts(self) -> list[dict[str, Any]]:
        return self._get_paginated("/api/v3/outposts/instances/")

    def create_proxy_provider(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(f"{self.base_url}/api/v3/providers/proxy/", "POST", payload)

    def update_proxy_provider(self, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json(
            f"{self.base_url}/api/v3/providers/proxy/{provider_id}/",
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
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE

        with urllib.request.urlopen(request, context=context) as response:
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


def _provider_payload(intent: RouteIntent) -> dict[str, Any]:
    return {
        "name": intent.provider_name,
        "external_host": f"https://{intent.host}",
        "cookie_domain": COOKIE_DOMAIN,
    }


def _application_payload(intent: RouteIntent, provider_id: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": intent.app_name,
        "slug": intent.app_slug,
        "meta_launch_url": f"https://{intent.host}/",
    }
    if provider_id:
        payload["provider"] = provider_id
    return payload


def _patch_from_existing(existing: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key, value in desired.items():
        current = existing.get(key)
        if key == "meta_launch_url":
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
            lambda item, expected_host=host: _DISCOVER._normalize_url_host(item.get("external_host"))
            == expected_host,
        ],
    )

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


def reconcile_authentik(
    manifest_paths: list[Path],
    client: Any,
    *,
    apply: bool,
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
    stop_conditions: list[str] = []
    write_count = 0
    consumed: dict[str, set[str]] = {"application": set(), "provider": set(), "outpost": set()}
    required_provider_ids: set[str] = set()
    has_forwardauth = False

    intents = sorted(intents, key=lambda item: (item.stack, item.route, item.host))
    for intent in intents:
        if intent.stack == "authentik-stack" and intent.auth_mode == "forwardAuth":
            stop_conditions.append(
                f"{intent.stack}/{intent.route}: Authentik self-route must not use forwardAuth"
            )
            continue

        if intent.auth_mode != "forwardAuth":
            app_matches, provider_matches, route_stops = _resolve_delete_reports(
                intent,
                applications,
                providers,
            )
            stop_conditions.extend(route_stops)
            for app in app_matches:
                app_id = _as_id(app)
                if app_id:
                    consumed["application"].add(app_id)
                actions.append(
                    ReconcileAction(
                        stack=intent.stack,
                        route=intent.route,
                        object_kind="application",
                        object_name=_DISCOVER._get_name(app),
                        operation="delete-report",
                        reason="route auth mode is not forwardAuth; object would be deleted in cleanup task",
                        object_id=app_id,
                    )
                )
            for provider in provider_matches:
                provider_id = _as_id(provider)
                if provider_id:
                    consumed["provider"].add(provider_id)
                actions.append(
                    ReconcileAction(
                        stack=intent.stack,
                        route=intent.route,
                        object_kind="provider",
                        object_name=_DISCOVER._get_name(provider),
                        operation="delete-report",
                        reason="route auth mode is not forwardAuth; object would be deleted in cleanup task",
                        object_id=provider_id,
                    )
                )
            continue

        has_forwardauth = True
        app_obj, provider_obj, route_stops = _resolve_forwardauth_candidates(intent, applications, providers)
        stop_conditions.extend(route_stops)

        provider_payload = _provider_payload(intent)
        provider_id: str | None = None

        if provider_obj is None:
            actions.append(
                ReconcileAction(
                    stack=intent.stack,
                    route=intent.route,
                    object_kind="provider",
                    object_name=intent.provider_name,
                    operation="create",
                    reason="owned provider is missing",
                )
            )
            if apply and not route_stops and not stop_conditions:
                created = client.create_proxy_provider(provider_payload)
                write_count += 1
                providers.append(created)
                provider_obj = created
        else:
            provider_id = _as_id(provider_obj)
            if provider_id:
                consumed["provider"].add(provider_id)
            provider_patch = _patch_from_existing(provider_obj, provider_payload)
            if provider_patch:
                actions.append(
                    ReconcileAction(
                        stack=intent.stack,
                        route=intent.route,
                        object_kind="provider",
                        object_name=intent.provider_name,
                        operation="update",
                        reason="owned provider differs from desired state",
                        object_id=provider_id,
                    )
                )
                if apply and not route_stops and not stop_conditions and provider_id:
                    updated = client.update_proxy_provider(provider_id, provider_patch)
                    write_count += 1
                    provider_obj.update(updated)
            else:
                actions.append(
                    ReconcileAction(
                        stack=intent.stack,
                        route=intent.route,
                        object_kind="provider",
                        object_name=intent.provider_name,
                        operation="noop",
                        reason="owned provider already matches desired state",
                        object_id=provider_id,
                    )
                )

        provider_id = _as_id(provider_obj) if provider_obj is not None else provider_id
        if provider_id:
            required_provider_ids.add(provider_id)
            consumed["provider"].add(provider_id)

        if app_obj is not None:
            app_id = _as_id(app_obj)
            if app_id:
                consumed["application"].add(app_id)
            linked_provider = _DISCOVER._get_provider_id_from_application(app_obj)
            if linked_provider and provider_id and linked_provider != provider_id:
                stop_conditions.append(
                    f"{intent.stack}/{intent.route}: application links a different provider id"
                )

        app_payload = _application_payload(intent, provider_id)
        if app_obj is None:
            actions.append(
                ReconcileAction(
                    stack=intent.stack,
                    route=intent.route,
                    object_kind="application",
                    object_name=intent.app_name,
                    operation="create",
                    reason="owned application is missing",
                )
            )
            if apply and not route_stops and not stop_conditions:
                created = client.create_application(app_payload)
                write_count += 1
                applications.append(created)
                created_id = _as_id(created)
                if created_id:
                    consumed["application"].add(created_id)
        else:
            app_id = _as_id(app_obj)
            app_patch = _patch_from_existing(app_obj, app_payload)
            if app_patch:
                actions.append(
                    ReconcileAction(
                        stack=intent.stack,
                        route=intent.route,
                        object_kind="application",
                        object_name=intent.app_name,
                        operation="update",
                        reason="owned application differs from desired state",
                        object_id=app_id,
                    )
                )
                if apply and not route_stops and not stop_conditions and app_id:
                    updated = client.update_application(app_id, app_patch)
                    write_count += 1
                    app_obj.update(updated)
            else:
                actions.append(
                    ReconcileAction(
                        stack=intent.stack,
                        route=intent.route,
                        object_kind="application",
                        object_name=intent.app_name,
                        operation="noop",
                        reason="owned application already matches desired state",
                        object_id=app_id,
                    )
                )

    if has_forwardauth:
        shared_outpost, outpost_stop = _find_single_shared_outpost(outposts)
        if outpost_stop:
            stop_conditions.append(outpost_stop)
        elif shared_outpost is None:
            actions.append(
                ReconcileAction(
                    stack="_shared",
                    route="forwardAuth",
                    object_kind="outpost",
                    object_name=SHARED_FORWARD_OUTPOST,
                    operation="create",
                    reason="shared forward-auth outpost is missing",
                )
            )
            if apply and not stop_conditions:
                payload = {
                    "name": SHARED_FORWARD_OUTPOST,
                    "type": SHARED_OUTPOST_TYPE,
                    "providers": sorted(required_provider_ids),
                }
                created = client.create_outpost(payload)
                write_count += 1
                outposts.append(created)
        else:
            outpost_id = _as_id(shared_outpost)
            if outpost_id:
                consumed["outpost"].add(outpost_id)
            linked = _DISCOVER._provider_references(shared_outpost)
            missing_links = sorted(required_provider_ids - linked)
            if missing_links:
                desired_links = sorted(linked | required_provider_ids)
                actions.append(
                    ReconcileAction(
                        stack="_shared",
                        route="forwardAuth",
                        object_kind="outpost",
                        object_name=SHARED_FORWARD_OUTPOST,
                        operation="update",
                        reason="shared outpost missing provider links",
                        object_id=outpost_id,
                    )
                )
                if apply and not stop_conditions and outpost_id:
                    updated = client.update_outpost(outpost_id, {"providers": desired_links})
                    write_count += 1
                    shared_outpost.update(updated)
            else:
                actions.append(
                    ReconcileAction(
                        stack="_shared",
                        route="forwardAuth",
                        object_kind="outpost",
                        object_name=SHARED_FORWARD_OUTPOST,
                        operation="noop",
                        reason="shared outpost already linked to all managed providers",
                        object_id=outpost_id,
                    )
                )

    for item in applications:
        item_id = _as_id(item)
        if not item_id or item_id in consumed["application"]:
            continue
        name = _DISCOVER._get_name(item)
        if _DISCOVER._is_owned_object(name):
            stop_conditions.append(f"unmanaged owned application detected: {name}")
    for item in providers:
        item_id = _as_id(item)
        if not item_id or item_id in consumed["provider"]:
            continue
        name = _DISCOVER._get_name(item)
        if _DISCOVER._is_owned_object(name):
            stop_conditions.append(f"unmanaged owned provider detected: {name}")

    stop_conditions = sorted(set(stop_conditions))
    if stop_conditions:
        # Applies must fail closed; do not permit partial writes after stop detection.
        # Writes are prevented by guarded apply branches above.
        pass

    actions.sort(key=lambda action: (action.stack, action.route, action.object_kind, action.object_name, action.operation))
    return ReconcileResult(
        apply=apply,
        actions=tuple(actions),
        issues=(),
        stop_conditions=tuple(stop_conditions),
        request_methods=tuple(client.request_methods),
        write_count=write_count,
    )


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
    result = reconcile_authentik(manifest_paths, client, apply=args.apply)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return 0 if result.ok else 1

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

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
