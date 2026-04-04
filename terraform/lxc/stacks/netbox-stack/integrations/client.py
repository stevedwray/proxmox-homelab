"""Idempotent NetBox API client for homelab population."""

import json
import os
import urllib.request
import urllib.error
import urllib.parse


class NetBoxClient:
    """Thin wrapper around the NetBox REST API with get-or-create semantics."""

    def __init__(self, url=None, token=None):
        self.url = (url or os.environ["NETBOX_URL"]).rstrip("/")
        self.token = token or os.environ["NETBOX_SUPERUSER_API_TOKEN"]

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

    def get(self, path, **params):
        return self._request("GET", path, params=params)

    def post(self, path, data):
        return self._request("POST", path, data=data)

    def patch(self, path, data):
        return self._request("PATCH", path, data=data)

    def delete(self, path):
        return self._request("DELETE", path)

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

    def ensure(self, path, lookup, defaults=None):
        """Get-or-create and log the result. Returns the object dict."""
        obj, created = self.get_or_create(path, lookup, defaults)
        action = "created" if created else "exists"
        name = obj.get("name") or obj.get("display") or obj.get("id")
        print(f"  {action}: {path} → {name} (id={obj['id']})")
        return obj
