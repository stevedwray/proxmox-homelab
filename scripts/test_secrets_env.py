"""Unit tests for scripts/secrets_env.py (no network, no OpenBao)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent / "secrets_env.py"
SPEC = importlib.util.spec_from_file_location("secrets_env", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["secrets_env"] = MODULE
SPEC.loader.exec_module(MODULE)

MANIFEST = {
    "entries": {
        "services/a": {"sops_source": "common", "fields": ["A_ONE", "SHARED_X"]},
        "hosts/n1": {"sops_source": "n1", "fields": ["SHARED_X", "HOST_TOKEN"]},
    },
    "profiles": {
        "n1": {"auth": "approle", "role": "deploy-n1", "entries": ["services/a", "hosts/n1"]},
        "ci": {"auth": "jwt-github", "role": "ci-x", "entries": ["services/a"]},
        "broken": {"auth": "approle", "role": "r", "entries": ["services/missing"]},
    },
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Records requests; answers from a dict of path -> (status, body)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def open(self, req, timeout=None):
        path = req.full_url.split("/v1/", 1)[1]
        self.calls.append((req.get_method(), path, req.headers.get("X-vault-token")))
        status, body = self.routes.get(path, (404, {}))
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, None)
        return FakeResponse(json.dumps(body).encode())


def ok_routes(**overrides):
    routes = {
        "auth/approle/login": (200, {"auth": {"client_token": "tok"}}),
        "auth/jwt-github/login": (200, {"auth": {"client_token": "tok"}}),
        "kv/data/services/a": (200, {"data": {"data": {"A_ONE": "1", "SHARED_X": "from-service", "EXTRA": "ignored"}}}),
        "kv/data/hosts/n1": (200, {"data": {"data": {"SHARED_X": "from-host", "HOST_TOKEN": "t"}}}),
        "auth/token/revoke-self": (200, {}),
    }
    routes.update(overrides)
    return routes


class ProfilePlanTests(unittest.TestCase):
    def test_unknown_profile(self):
        with self.assertRaises(MODULE.SecretsError):
            MODULE.profile_plan(MANIFEST, "nope")

    def test_undefined_entry(self):
        with self.assertRaises(MODULE.SecretsError):
            MODULE.profile_plan(MANIFEST, "broken")

    def test_order_preserved(self):
        _, plan = MODULE.profile_plan(MANIFEST, "n1")
        self.assertEqual([e for e, _ in plan], ["services/a", "hosts/n1"])


class CollectTests(unittest.TestCase):
    def client(self, routes):
        opener = FakeOpener(routes)
        c = MODULE.OpenBaoClient("https://x:8200", cacert="", opener=opener)
        c.token = "tok"
        return c, opener

    def test_later_entry_overrides_and_extra_fields_ignored(self):
        c, _ = self.client(ok_routes())
        _, plan = MODULE.profile_plan(MANIFEST, "n1")
        env = MODULE.collect(c, plan)
        self.assertEqual(env, {"A_ONE": "1", "SHARED_X": "from-host", "HOST_TOKEN": "t"})
        self.assertNotIn("EXTRA", env)

    def test_empty_field_fails_closed(self):
        routes = ok_routes(**{"kv/data/services/a": (200, {"data": {"data": {"A_ONE": "", "SHARED_X": "s"}}})})
        c, _ = self.client(routes)
        _, plan = MODULE.profile_plan(MANIFEST, "n1")
        with self.assertRaisesRegex(MODULE.SecretsError, "services/a:A_ONE"):
            MODULE.collect(c, plan)

    def test_missing_field_fails_closed(self):
        routes = ok_routes(**{"kv/data/hosts/n1": (200, {"data": {"data": {"SHARED_X": "h"}}})})
        c, _ = self.client(routes)
        _, plan = MODULE.profile_plan(MANIFEST, "n1")
        with self.assertRaisesRegex(MODULE.SecretsError, "hosts/n1:HOST_TOKEN"):
            MODULE.collect(c, plan)

    def test_unreadable_entry_fails_closed(self):
        routes = ok_routes(**{"kv/data/hosts/n1": (403, {})})
        c, _ = self.client(routes)
        _, plan = MODULE.profile_plan(MANIFEST, "n1")
        with self.assertRaisesRegex(MODULE.SecretsError, "HTTP 403"):
            MODULE.collect(c, plan)


class LoginTests(unittest.TestCase):
    def test_approle_reads_cred_files(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "deploy-n1.role-id").write_text("rid\n")
            Path(d, "deploy-n1.secret-id").write_text("sid\n")
            opener = FakeOpener(ok_routes())
            c = MODULE.OpenBaoClient("https://x:8200", cacert="", opener=opener)
            MODULE.login(c, MANIFEST["profiles"]["n1"], Path(d))
            self.assertEqual(c.token, "tok")
            self.assertEqual(opener.calls[0][:2], ("POST", "auth/approle/login"))

    def test_approle_missing_creds(self):
        with tempfile.TemporaryDirectory() as d:
            c = MODULE.OpenBaoClient("https://x:8200", cacert="", opener=FakeOpener(ok_routes()))
            with self.assertRaisesRegex(MODULE.SecretsError, "missing AppRole credentials"):
                MODULE.login(c, MANIFEST["profiles"]["n1"], Path(d))

    def test_jwt_requires_env(self):
        c = MODULE.OpenBaoClient("https://x:8200", cacert="", opener=FakeOpener(ok_routes()))
        saved = MODULE.os.environ.pop("OPENBAO_GITHUB_JWT", None)
        try:
            with self.assertRaisesRegex(MODULE.SecretsError, "OPENBAO_GITHUB_JWT"):
                MODULE.login(c, MANIFEST["profiles"]["ci"], Path("."))
        finally:
            if saved is not None:
                MODULE.os.environ["OPENBAO_GITHUB_JWT"] = saved


class MainTests(unittest.TestCase):
    def test_list_fields_needs_no_network(self):
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d, "m.json")
            mpath.write_text(json.dumps(MANIFEST))
            out = io.StringIO()
            saved = sys.stdout
            sys.stdout = out
            try:
                rc = MODULE.main(["--profile", "n1", "--manifest", str(mpath), "--list-fields"])
            finally:
                sys.stdout = saved
            self.assertEqual(rc, 0)
            self.assertEqual(out.getvalue().split(), ["A_ONE", "SHARED_X", "HOST_TOKEN"])

    def test_real_manifest_is_consistent(self):
        real = MODULE.REPO_ROOT / "secrets" / "manifest.json"
        if not real.exists():
            self.skipTest("secrets/manifest.json not present yet")
        manifest = MODULE.load_manifest(real)
        for name in manifest["profiles"]:
            MODULE.profile_plan(manifest, name)


if __name__ == "__main__":
    unittest.main()
