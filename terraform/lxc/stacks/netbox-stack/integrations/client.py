"""Idempotent NetBox API client for homelab population."""

import copy
import json
import os
import urllib.request
import urllib.error
import urllib.parse
from collections import defaultdict


class NetBoxClient:
    """Thin wrapper around the NetBox REST API with bounded reconciliation semantics."""

    def __init__(self, url=None, token=None, dry_run=False):
        resolved_url = (
            url
            or os.environ.get("NETBOX_URL")
            or (f"http://{os.environ.get('LAB_IP_NETBOX')}:8080" if os.environ.get("LAB_IP_NETBOX") else None)
        )
        if not resolved_url:
            raise ValueError("NetBox client requires NETBOX_URL or LAB_IP_NETBOX")

        self.url = resolved_url.rstrip("/")
        env_api_token = os.environ.get("NETBOX_API_TOKEN")
        env_super_token = os.environ.get("NETBOX_SUPERUSER_API_TOKEN")
        if token:
            self.token = token
        elif env_api_token:
            self.token = env_api_token
        elif env_super_token:
            self.token = env_super_token
        else:
            raise ValueError(
                "NetBox client requires a token parameter or NETBOX_API_TOKEN / NETBOX_SUPERUSER_API_TOKEN environment variable"
            )
        self.dry_run = dry_run
        self._synthetic_id = -1
        self._planned_objects = defaultdict(dict)
        self._desired_lookups = defaultdict(list)

    def _request(self, method, path, data=None, params=None):
        endpoint = f"{self.url}/api{path}"
        if params:
            endpoint += "?" + urllib.parse.urlencode(params)
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            endpoint,
            data=body,
            method=method,
            headers={
                "Authorization": f"Token {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status == 204:
                    return None
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode() if e.fp else ""
            raise RuntimeError(
                f"{method} {path} → {e.code}: {err_body}"
            ) from e

    def post(self, path, data):
        return self._request("POST", path, data=data)

    def patch(self, path, data):
        return self._request("PATCH", path, data=data)

    def delete(self, path):
        return self._request("DELETE", path)

    def patch_object(self, path, obj, changes):
        """Patch one object by endpoint path and object dict, honoring dry-run mode."""
        if not changes:
            return obj

        merged = {**copy.deepcopy(obj), **changes}
        if self.dry_run:
            self._cache_object(path, merged)
            print(
                f"  would update: {path} → {self._label(merged)} "
                f"(id={merged['id']}) fields={sorted(changes)}"
            )
            return merged

        self.patch(f"{path}{obj['id']}/", changes)
        print(
            f"  updated: {path} → {self._label(merged)} "
            f"(id={merged['id']}) fields={sorted(changes)}"
        )
        return merged

    def delete_object(self, path, obj):
        """Delete one object by endpoint path and object dict, honoring dry-run mode."""
        label = self._label(obj)
        if self.dry_run:
            self._planned_objects[path].pop(obj["id"], None)
            print(f"  would delete: {path} → {label} (id={obj['id']})")
            return

        self.delete(f"{path}{obj['id']}/")
        print(f"  deleted: {path} → {label} (id={obj['id']})")

    def _next_synthetic(self):
        next_id = self._synthetic_id
        self._synthetic_id -= 1
        return next_id

    def _label(self, obj):
        return obj.get("name") or obj.get("display") or obj.get("address") or obj.get("prefix") or obj.get("id")

    def _extract_existing_field(self, obj, key):
        if key in obj:
            return obj.get(key)
        if key.endswith("_id"):
            return obj.get(key[:-3])
        return obj.get(key)

    def _coerce_existing(self, existing, expected):
        if isinstance(expected, dict):
            if not isinstance(existing, dict):
                return existing
            if set(expected).issubset({"id", "name", "slug"}):
                return {key: existing.get(key) for key in expected}
            return {k: self._coerce_existing(existing.get(k), v) for k, v in expected.items()}

        if isinstance(expected, list):
            if not isinstance(existing, list):
                return existing
            return [self._coerce_existing(item, expected[0]) if expected else item for item in existing]

        # Normalize dict wrappers commonly returned by NetBox into the
        # comparable primitive types expected by callers. When the expected
        # value is a string, perform case-insensitive normalization so that
        # NetBox-presented labels/names (which may be Title Case) compare
        # equal to lowercase expected literals such as 'virtual'.
        if isinstance(existing, dict):
            if "id" in existing and isinstance(expected, int):
                return existing["id"]
            if isinstance(expected, str):
                # Prefer canonical keys that NetBox commonly uses for choice
                # style fields.
                if "value" in existing:
                    val = existing.get("value")
                    return val.lower() if isinstance(val, str) else val
                if "slug" in existing:
                    val = existing.get("slug")
                    return val.lower() if isinstance(val, str) else val
                if "name" in existing:
                    val = existing.get("name")
                    return val.lower() if isinstance(val, str) else val
            # For non-string expected types, fall through to nested coercion.
            return {k: self._coerce_existing(v, expected.get(k) if isinstance(expected, dict) else expected)
                    for k, v in existing.items()} if isinstance(expected, dict) else existing

        # If expected is a string, and the existing value is a plain string,
        # compare case-insensitively by normalizing to lowercase.
        if isinstance(expected, str) and isinstance(existing, str):
            return existing.lower()

        return existing

    def _canonical(self, value):
        if isinstance(value, dict):
            return tuple(sorted((k, self._canonical(v)) for k, v in value.items()))
        if isinstance(value, list):
            return tuple(sorted((self._canonical(item) for item in value), key=repr))
        return value

    def _field_matches(self, existing, expected):
        existing_c = self._canonical(self._coerce_existing(existing, expected))
        expected_c = self._canonical(expected)
        # If both sides are plain strings, compare case-insensitively to avoid
        # churn when NetBox returns Title Case labels but expected values are
        # lowercase literals.
        if isinstance(existing_c, str) and isinstance(expected_c, str):
            return existing_c.lower() == expected_c.lower()
        return existing_c == expected_c

    def _object_matches_lookup(self, obj, lookup):
        return all(
            self._field_matches(self._extract_existing_field(obj, key), value)
            for key, value in lookup.items()
        )

    def _cache_object(self, path, obj):
        self._planned_objects[path][obj["id"]] = copy.deepcopy(obj)

    def _merge_live_with_planned(self, path, results):
        merged = []
        seen_ids = set()
        for obj in results:
            planned = self._planned_objects[path].get(obj.get("id"))
            merged_obj = copy.deepcopy(planned) if planned else obj
            merged.append(merged_obj)
            if "id" in merged_obj:
                seen_ids.add(merged_obj["id"])

        for obj_id, obj in self._planned_objects[path].items():
            if obj_id not in seen_ids:
                merged.append(copy.deepcopy(obj))

        return merged

    def _build_patch(self, existing, desired):
        changes = {}
        for field, value in desired.items():
            existing_value = self._extract_existing_field(existing, field)
            if not self._field_matches(existing_value, value):
                changes[field] = value
        return changes

    def _record_desired_lookup(self, path, lookup):
        self._desired_lookups[path].append(copy.deepcopy(lookup))

    def _references_synthetic_value(self, value):
        if isinstance(value, int):
            return value < 0
        if isinstance(value, dict):
            return any(self._references_synthetic_value(item) for item in value.values())
        if isinstance(value, list):
            return any(self._references_synthetic_value(item) for item in value)
        return False

    def _params_reference_synthetic(self, params):
        return any(self._references_synthetic_value(value) for value in params.values())

    def get_or_create(self, path, lookup, defaults=None):
        """Find an existing object by lookup params, or create it.

        Returns (object_dict, created_bool).
        """
        results = self.get(path, **lookup)
        if results["count"] > 0:
            return results["results"][0], False
        payload = {**lookup, **(defaults or {})}
        obj = self.post(path, payload)
        return obj, True

    def live_get(self, path, **params):
        """Always query the live NetBox API, bypassing dry-run synthetic objects."""
        results = self._request("GET", path, params=params)
        return results or {"count": 0, "results": []}

    def get(self, path, **params):
        if not self.dry_run:
            return self._request("GET", path, params=params)

        if self._params_reference_synthetic(params):
            live_results = {"count": 0, "results": []}
        else:
            results = self._request("GET", path, params=params)
            live_results = results or {"count": 0, "results": []}

        combined = self._merge_live_with_planned(path, live_results.get("results", []))
        if params:
            combined = [obj for obj in combined if self._object_matches_lookup(obj, params)]
        return {"count": len(combined), "results": combined}

    def ensure(self, path, lookup, defaults=None, legacy_lookups=None):
        """Create or reconcile an object and log the resulting action."""
        self._record_desired_lookup(path, lookup)
        desired = {**lookup, **(defaults or {})}
        results = self.get(path, **lookup)

        if results["count"] == 0 and legacy_lookups:
            for legacy_lookup in legacy_lookups:
                legacy_results = self.get(path, **legacy_lookup)
                if legacy_results["count"] > 0:
                    results = legacy_results
                    break

        if results["count"] == 0:
            if self.dry_run:
                obj = {"id": self._next_synthetic(), **desired}
                self._cache_object(path, obj)
            else:
                obj = self.post(path, desired)
            print(f"  {'would create' if self.dry_run else 'created'}: {path} → {self._label(obj)} (id={obj['id']})")
            return obj

        obj = results["results"][0]
        changes = self._build_patch(obj, desired)
        if changes:
            if self.dry_run:
                obj = {**copy.deepcopy(obj), **changes}
                self._cache_object(path, obj)
            else:
                self.patch(f"{path}{obj['id']}/", changes)
                obj = {**copy.deepcopy(obj), **changes}
            print(
                f"  {'would update' if self.dry_run else 'updated'}: {path} → "
                f"{self._label(obj)} (id={obj['id']}) fields={sorted(changes)}"
            )
            return obj

        print(f"  exists: {path} → {self._label(obj)} (id={obj['id']})")
        return obj

    def find_stale(self, path, **filters):
        """Return managed objects for a path that are no longer desired."""
        desired_lookups = self._desired_lookups.get(path, [])
        if not desired_lookups:
            return []

        existing = self.get(path, **filters).get("results", [])
        stale = []
        for obj in existing:
            if not any(self._object_matches_lookup(obj, lookup) for lookup in desired_lookups):
                stale.append(obj)
        return stale
