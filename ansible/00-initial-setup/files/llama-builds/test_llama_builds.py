"""Unit tests for llama-builds, with a throwaway local git repo as the
"remote" (no network, no compiler). Run with:
python3 -m unittest discover -s ansible/00-initial-setup/files/llama-builds -p "test_*.py"
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader("llama_builds", os.path.join(HERE, "llama-builds"))
spec = importlib.util.spec_from_loader("llama_builds", loader)
lb = importlib.util.module_from_spec(spec)
loader.exec_module(lb)


def sh(*argv, cwd=None):
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        self.remote = os.path.join(t, "remote")
        os.makedirs(self.remote)
        sh("git", "init", "-q", "-b", "strix-halo-vulkan", cwd=self.remote)
        self.shas = []
        for i in range(3):
            with open(os.path.join(self.remote, "f"), "w") as fh:
                fh.write(str(i))
            sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam" if i else "-qm", f"c{i}", cwd=self.remote) \
                if i else (sh("git", "add", "f", cwd=self.remote),
                           sh("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c0", cwd=self.remote))
            self.shas.append(sh("git", "rev-parse", "HEAD", cwd=self.remote))
        self.root = os.path.join(t, "builds")
        os.makedirs(os.path.join(self.root, "src"))
        sh("git", "init", "-q", os.path.join(self.root, "src"))
        self.cfg = {"root": self.root, "keep": 2, "backends": {
            "fork": {"remote": "fork", "url": self.remote, "branch": "strix-halo-vulkan", "cmake": ["-DGGML_VULKAN=ON"]}}}

    def fake_build(self, sha, day):
        name = lb.build_name(sha, day)
        bdir = os.path.join(self.root, "fork")
        os.makedirs(os.path.join(bdir, name, "bin"))
        with open(os.path.join(bdir, name, "build.json"), "w") as fh:
            json.dump({"name": name, "sha": sha, "built": day}, fh)
        return name


class StatusTest(Fixture):
    def test_status_counts_commits_behind(self):
        old = self.fake_build(self.shas[0], "20261001")
        lb.set_link(os.path.join(self.root, "fork"), "current", old)
        st = lb.status(self.cfg)
        e = st["backends"]["fork"]
        self.assertEqual((e["head"], e["current"]["name"], e["current"]["behind"], e["error"]),
                         (self.shas[2][:9], old, 2, None))
        self.assertIsNone(e["candidate"])
        self.assertIn("fork", "\n".join(lb.status_lines(st)))

    def test_unreachable_remote_is_reported_not_raised(self):
        self.cfg["backends"]["fork"]["url"] = "/nonexistent/repo"
        self.assertTrue(lb.status(self.cfg)["backends"]["fork"]["error"])


class LinkTest(Fixture):
    def test_promote_then_rollback(self):
        bdir = os.path.join(self.root, "fork")
        a, b = self.fake_build(self.shas[0], "20261001"), self.fake_build(self.shas[1], "20261005")
        lb.set_link(bdir, "current", a)
        lb.set_link(bdir, "candidate", b)
        lb.promote(self.cfg, "fork")
        self.assertEqual((lb.link_target(bdir, "current"), lb.link_target(bdir, "previous")), (b, a))
        self.assertTrue(os.readlink(os.path.join(bdir, "current")) == b)  # relative link
        lb.rollback(self.cfg, "fork")
        self.assertEqual((lb.link_target(bdir, "current"), lb.link_target(bdir, "previous")), (a, b))

    def test_promote_needs_a_candidate(self):
        with self.assertRaises(lb.Fail):
            lb.promote(self.cfg, "fork")
        with self.assertRaises(lb.Fail):
            lb.promote(self.cfg, "nope")

    def test_prune_keeps_newest_and_linked(self):
        bdir = os.path.join(self.root, "fork")
        names = [self.fake_build(s, d) for s, d in zip(self.shas, ("20261001", "20261002", "20261003"))]
        old = self.fake_build("f" * 40, "20260901")
        lb.set_link(bdir, "previous", names[0])
        self.assertEqual(lb.prune_plan(lb.list_builds(bdir), [None, None, names[0]], 2), [old])
        lb.prune(self.cfg, "fork")
        self.assertEqual(lb.list_builds(bdir), names)


class BuildTest(Fixture):
    def test_already_built_sha_just_becomes_candidate(self):
        bdir = os.path.join(self.root, "fork")
        name = self.fake_build(self.shas[2], "20261001")
        msg = lb.build(self.cfg, "fork")
        self.assertIn("already built", msg)
        self.assertEqual(lb.link_target(bdir, "candidate"), name)


class PublishTest(Fixture):
    def test_publish_sends_auth_select_set(self):
        import socket
        import threading
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        got = []

        def serve():
            conn, _ = server.accept()
            reader = conn.makefile("rb")
            for _ in range(3):
                n = int(reader.readline()[1:])
                parts = []
                for _ in range(n):
                    size = int(reader.readline()[1:])
                    parts.append(reader.read(size + 2)[:-2].decode())
                got.append(parts)
                conn.sendall(b"+OK\r\n")
            conn.close()
        thread = threading.Thread(target=serve)
        thread.start()
        pw = os.path.join(self.tmp.name, "pw")
        with open(pw, "w") as fh:
            fh.write("secret\n")
        self.cfg["publish"] = {"host": "127.0.0.1", "port": server.getsockname()[1], "db": 1,
                               "key": "framework:llama-builds", "password_file": pw}
        lb.publish(self.cfg, {"checked": "now", "backends": {}})
        thread.join(5)
        server.close()
        self.assertEqual(got[0], ["AUTH", "secret"])
        self.assertEqual(got[1], ["SELECT", "1"])
        self.assertEqual(got[2][:2], ["SET", "framework:llama-builds"])
        self.assertEqual(json.loads(got[2][2])["checked"], "now")
        self.assertEqual(got[2][3:], ["EX", str(lb.STATUS_TTL)])


class RespTest(unittest.TestCase):
    def test_encoding(self):
        self.assertEqual(lb.resp("SET", "k", "vé", "EX", 5),
                         b"*5\r\n$3\r\nSET\r\n$1\r\nk\r\n$3\r\nv\xc3\xa9\r\n$2\r\nEX\r\n$1\r\n5\r\n")


if __name__ == "__main__":
    unittest.main()


class SwapConfigTest(unittest.TestCase):
    """llama-swap entries from the catalogue and the build links."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.tmp.name
        self.root = os.path.join(t, "builds")
        for backend, builds in (("fork", ["20261008-aaaaaaaaa", "20261009-bbbbbbbbb"]),
                                ("upstream", ["20261008-ccccccccc"]), ("upstream-hip", [])):
            os.makedirs(os.path.join(self.root, backend))
            for b in builds:
                os.makedirs(os.path.join(self.root, backend, b, "bin"))
        lb.set_link(os.path.join(self.root, "fork"), "current", "20261008-aaaaaaaaa")
        lb.set_link(os.path.join(self.root, "fork"), "candidate", "20261008-aaaaaaaaa")
        lb.set_link(os.path.join(self.root, "upstream"), "current", "20261008-ccccccccc")
        lb.set_link(os.path.join(self.root, "upstream"), "candidate", "20261008-ccccccccc")
        self.catalog = os.path.join(t, "models.json")
        with open(self.catalog, "w") as fh:
            json.dump({"default": "glm-upstream", "models": [
                {"id": "glm", "name": "GLM", "gguf": "/m/GLM-00001-of-00002.gguf", "backends": ["upstream", "upstream-hip"],
                 "args": ["--chat-template-kwargs", '{"reasoning_effort":"high"}'], "note": "no fork"},
                {"id": "qwen", "name": "Qwen", "gguf": "/m/qwen.gguf", "backends": ["fork", "upstream", "upstream-hip"]},
            ]}, fh)
        self.config = os.path.join(t, "config.yaml")
        self.cfg = {"root": self.root, "backends": {"fork": {}, "upstream": {}, "upstream-hip": {}},
                    "swap": {"models": self.catalog, "config": self.config, "url": "http://127.0.0.1:9",
                             "memgate": "/usr/local/bin/llm-memgate", "api_key_file": "/etc/llamacpp/api-key",
                             "reload_wait": 0}}

    def ids(self):
        return [e for e, _ in lb.swap_entries(self.cfg, lb.load_catalog(self.cfg), size=lambda g: 1000)]

    def test_one_entry_per_built_backend_and_no_candidate_equal_to_current(self):
        # upstream-hip has no build; the candidates equal current
        self.assertEqual(self.ids(), ["glm-upstream", "qwen-fork", "qwen-upstream"])

    def test_a_distinct_candidate_gets_its_own_entry(self):
        lb.set_link(os.path.join(self.root, "fork"), "candidate", "20261009-bbbbbbbbb")
        self.assertEqual(self.ids(), ["glm-upstream", "qwen-fork", "qwen-fork-candidate", "qwen-upstream"])

    def test_entry_names_say_backend_and_build_and_cmd_is_right(self):
        entries = dict(lb.swap_entries(self.cfg, lb.load_catalog(self.cfg), size=lambda g: 97127))
        glm = entries["glm-upstream"]
        self.assertEqual(glm["name"], "GLM · upstream 20261008-ccccccccc")
        self.assertIn("97,127 MiB", glm["description"])
        first, second = glm["cmd"].splitlines()
        self.assertEqual(first, "/usr/local/bin/llm-memgate 97127")
        self.assertIn(os.path.join(self.root, "upstream", "current", "bin", "llama-server"), second)
        self.assertIn("--alias glm-upstream", second)
        self.assertIn("""'{"reasoning_effort":"high"}'""", second)

    def test_rendered_config_is_valid_yaml_with_every_entry_in_the_group(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml not installed")
        doc = yaml.safe_load(lb.render_swap(self.cfg, lb.swap_entries(self.cfg, lb.load_catalog(self.cfg),
                                                                       size=lambda g: 1)))
        self.assertEqual(list(doc["models"]), ["glm-upstream", "qwen-fork", "qwen-upstream"])
        self.assertEqual(doc["routing"]["router"]["settings"]["groups"]["chat"]["members"], list(doc["models"]))
        self.assertNotIn("hooks", doc)
        self.assertTrue(doc["models"]["glm-upstream"]["cmd"].startswith("/usr/local/bin/llm-memgate 1\n"))

    def test_weights_mb_sums_every_shard(self):
        d = self.tmp.name
        for i, size in ((1, 3 * 2 ** 20), (2, 2 ** 20 + 1)):
            with open(os.path.join(d, f"M-0000{i}-of-00002.gguf"), "wb") as fh:
                fh.truncate(size)
        self.assertEqual(lb.weights_mb(os.path.join(d, "M-00001-of-00002.gguf")), 5)

    def test_unchanged_dry_run_and_busy_framework(self):
        size = lambda g: 1  # noqa: E731
        self.assertIn("would write 3 entries", lb.swap_config(self.cfg, dry_run=True, size=size))
        self.assertFalse(os.path.exists(self.config))
        self.cfg["publish"] = {"host": "x", "password_file": "/dev/null"}
        with mock.patch.object(lb, "redis_get", return_value='{"suite": "eval"}'):
            with self.assertRaises(lb.Fail):
                lb.swap_config(self.cfg, size=size)
        with mock.patch.object(lb, "redis_get", return_value=None), \
                mock.patch.object(lb, "running_models", return_value=[]):
            self.assertIn("written: 3 entries", lb.swap_config(self.cfg, size=size))
            self.assertIn("unchanged", lb.swap_config(self.cfg, size=size))

    def test_the_loaded_model_is_loaded_again_after_the_rewrite(self):
        self.cfg.pop("publish", None)
        loaded = []
        with mock.patch.object(lb, "running_models", return_value=["qwen-fork"]), \
                mock.patch.object(lb, "wait_for_swap", return_value=True), \
                mock.patch.object(lb, "wait_port_free", return_value=True), \
                mock.patch.object(lb, "load_model", side_effect=lambda cfg, m: loaded.append(m)):
            msg = lb.swap_config(self.cfg, size=lambda g: 1)
        self.assertEqual(loaded, ["qwen-fork"])
        self.assertIn("qwen-fork loaded again", msg)

    def test_an_old_name_falls_back_to_the_default_and_a_busy_port_loads_nothing(self):
        loaded = []
        with mock.patch.object(lb, "running_models", return_value=["glm-5.3-flash"]), \
                mock.patch.object(lb, "wait_for_swap", return_value=True), \
                mock.patch.object(lb, "wait_port_free", return_value=True), \
                mock.patch.object(lb, "load_model", side_effect=lambda cfg, m: loaded.append(m)):
            msg = lb.swap_config(self.cfg, size=lambda g: 1)
        self.assertEqual(loaded, ["glm-upstream"])
        self.assertIn("glm-5.3-flash has no entry now", msg)
        os.unlink(self.config)
        with mock.patch.object(lb, "running_models", return_value=["glm-upstream"]), \
                mock.patch.object(lb, "wait_for_swap", return_value=True), \
                mock.patch.object(lb, "wait_port_free", return_value=False), \
                mock.patch.object(lb, "load_model", side_effect=lambda cfg, m: loaded.append(m)):
            msg = lb.swap_config(self.cfg, size=lambda g: 1)
        self.assertEqual(loaded, ["glm-upstream"])  # nothing more
        self.assertIn("still holds :8080", msg)


class ShippedCatalogTest(unittest.TestCase):
    def test_catalog_is_consistent(self):
        path = os.path.join(HERE, "..", "llama-swap", "models.json")
        with open(path) as fh:
            catalog = json.load(fh)
        ids = [m["id"] for m in catalog["models"]]
        self.assertEqual(len(ids), len(set(ids)))
        for m in catalog["models"]:
            self.assertTrue(set(m["backends"]) <= set(lb.BACKEND_LABEL), m["id"])
            self.assertTrue(m["gguf"].endswith(".gguf"), m["id"])
        self.assertNotIn("fork", next(m for m in catalog["models"] if m["id"] == "glm-5.3-flash")["backends"])
        default_model, _, backend = catalog["default"].rpartition("-")
        self.assertIn(default_model, ids)
        self.assertIn(backend, lb.BACKEND_LABEL.values())
