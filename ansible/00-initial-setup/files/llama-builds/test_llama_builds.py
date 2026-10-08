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
