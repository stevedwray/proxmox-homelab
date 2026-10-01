"""Unit tests for publish.py (synthetic results, in-process fake Nextcloud).
python3 -m unittest discover -s terraform/lxc/ansible/files/eval-runner -p "test_*.py"
"""

import csv
import io
import json
import os
import tempfile
import unittest

import mock_nextcloud
import publish
import summarize
from test_summarize import gpqa_rows, ifeval_rows, write_run


class FakeNextcloud:
    """publish.Nextcloud's interface, backed by mock_nextcloud's state and routing."""

    def __init__(self):
        mock_nextcloud.reset()
        self.state = mock_nextcloud.STATE
        self.calls = []

    def ensure_folder(self, rel):
        parts = rel.strip("/").split("/")
        for i in range(1, len(parts) + 1):
            path = "/".join(parts[:i])
            if path not in self.state["folders"]:
                self.state["folders"].append(path)

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        assert path.startswith(mock_nextcloud.OCS_API), path
        code, result = mock_nextcloud.ocs_route(method, path[len(mock_nextcloud.OCS_API):], body or {})
        if code != 200:
            raise publish.NextcloudError(f"{method} {path} -> {code} {result}")
        return result

    def put_file(self, rel, content):
        assert os.path.dirname(rel) in self.state["folders"], rel
        self.state["files"][rel] = content.decode()

    def tables(self, method, path, body=None):
        self.calls.append((method, path))
        code, result = mock_nextcloud.route(method, path.split("?", 1)[0], body or {})
        if code != 200:
            raise publish.NextcloudError(f"{method} {path} -> {code} {result}")
        return result


def make_tree(root):
    """One eval-runner run (with run.json) and two historical sources (one excluded)."""
    run_dir = write_run(root, "glm-5.3-flash-both-20261002T000000Z", ["gpqa", "ifeval"],
                        gpqa_rows=gpqa_rows(["(A)", "", "(B)"]), ifeval_rows=ifeval_rows(["ok", ""]),
                        run_json=False)
    with open(os.path.join(run_dir, "run.json"), "w") as fh:
        json.dump({"run": os.path.basename(run_dir), "note": "reasoning_effort=high", "created_utc": "20261002T000000Z",
                   "fingerprint": "abcd" * 16, "limit": None, "concurrency": 1, "lm_eval_version": "0.4.12",
                   "server": {"model_id": "glm-5.3-flash", "props": {
                       "model_path": "/m/GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf",
                       "build_info": "b11309-a4d880fd5", "n_ctx": 131072,
                       "params": {"temperature": 1.0, "top_p": 0.95}}}}, fh)
    hist = os.path.join(root, summarize.HISTORICAL_DIR)
    os.makedirs(hist)
    write_run(hist, "qwen36-35b-redo", ["gpqa", "ifeval"], gpqa_rows=gpqa_rows(["(A)", ""]),
              ifeval_rows=ifeval_rows(["ok"]), run_json=False)
    write_run(hist, "qwen36-35b", ["ifeval"], ifeval_rows=ifeval_rows(["x"]), run_json=False,
              config={"limit": None, "gen_kwargs": {}, "model_args": {"model": "eval-qwen36", "base_url": "http://f:11434/v1"}})
    return run_dir


class CollectTest(unittest.TestCase):
    def test_rows_from_runs_and_history(self):
        with tempfile.TemporaryDirectory() as root:
            make_tree(root)
            rows = [r for _, _, _, rs in publish.collect(root) for r in rs]
        by_key = {r["Key"]: r for r in rows}
        self.assertEqual(len(rows), 5)
        glm = by_key["runs/glm-5.3-flash-both-20261002T000000Z/gpqa_diamond_cot_zeroshot"]
        self.assertEqual(glm["Model"], "glm-5.3-flash")
        self.assertEqual(glm["Runtime"], "llama.cpp b11309-a4d880fd5")
        self.assertEqual(glm["Model file / tag"], "GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf")
        self.assertEqual(glm["Note"], "reasoning_effort=high")
        self.assertEqual(glm["Date"], "2026-10-02")
        self.assertEqual((glm["Score %"], glm["Empty answers"], glm["Unparsed"]), (50.0, 1, 1))
        self.assertEqual(glm["Empty %"], 33.3)
        self.assertEqual(glm["Comparable"], "yes")
        bug6 = [r for r in rows if r["Run"] == "qwen36-35b"][0]
        self.assertEqual(bug6["Comparable"], "no")
        self.assertIn("Bug 6", bug6["Why not comparable"])
        self.assertEqual(bug6["Runtime"], "Ollama")
        self.assertTrue(bug6["Key"].startswith("historical/qwen36-35b/ifeval/"))


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        make_tree(self.tmp.name)
        self.files, self.rows = publish.build_files(publish.collect(self.tmp.name), "# findings\n", "NOW")

    def tearDown(self):
        self.tmp.cleanup()

    def test_expected_files(self):
        self.assertIn("leaderboard.md", self.files)
        self.assertIn("leaderboard.csv", self.files)
        self.assertEqual(self.files["findings.md"], b"# findings\n")
        self.assertIn("runs/glm-5.3-flash-both-20261002T000000Z/report.md", self.files)
        self.assertIn("historical/qwen36-35b/manifest.json", self.files)
        self.assertFalse(any("samples_" in name for name in self.files))

    def test_markdown_tables_have_consistent_columns(self):
        for name, content in self.files.items():
            if not name.endswith(".md"):
                continue
            header_cols = None
            for line in content.decode().splitlines():
                if not line.startswith("|"):
                    header_cols = None
                    continue
                cols = line.count("|")
                header_cols = header_cols or cols
                self.assertEqual(cols, header_cols, f"{name}: {line}")

    def test_leaderboard_ranks_and_lists_excluded(self):
        board = self.files["leaderboard.md"].decode()
        self.assertIn("| 1 | glm-5.3-flash | 50.00% |", board)
        self.assertIn("## Not comparable", board)
        self.assertIn("no max_gen_toks=8192", board)

    def test_manifest_follows_convention(self):
        manifest = json.loads(self.files["runs/glm-5.3-flash-both-20261002T000000Z/manifest.json"])
        for key in ("project", "run_id", "started_at", "finished_at", "summary"):
            self.assertIn(key, manifest)
        self.assertEqual(manifest["project"], "eval-runner")

    def test_csv_has_all_columns_and_rows(self):
        reader = list(csv.DictReader(io.StringIO(self.files["leaderboard.csv"].decode())))
        self.assertEqual(len(reader), 5)
        self.assertEqual(list(reader[0].keys()), [t for t, _ in publish.COLUMNS])


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        make_tree(self.tmp.name)
        self.files, self.rows = publish.build_files(publish.collect(self.tmp.name), None, "NOW")
        self.nc = FakeNextcloud()

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_publish_creates_everything(self):
        table_id, counts = publish.publish(self.nc, self.files, self.rows, share_with="steve")
        self.assertEqual(counts, (5, 0, 0))
        state = self.nc.state
        self.assertEqual([t["title"] for t in state["tables"]], [publish.TABLE_TITLE])
        self.assertEqual([c["title"] for c in state["columns"]], [t for t, _ in publish.COLUMNS])
        self.assertEqual(len(state["rows"]), 5)
        self.assertEqual({v["title"] for v in state["views"]}, {v[0] for v in publish.VIEWS})
        view = state["views"][0]
        self.assertEqual(view["filter"][0][0]["operator"], "is-equal")
        self.assertEqual(view["sort"], [{"columnId": view["columnSettings"][2]["columnId"], "mode": "DESC"}])
        self.assertEqual(len(view["columnSettings"]), len(publish.COLUMNS) - 1)
        self.assertEqual([s["receiver"] for s in state["shares"]], ["steve"])
        self.assertIn(f"{publish.FOLDER}/leaderboard.md", state["files"])
        table = state["tables"][0]
        key_id = next(c["id"] for c in state["columns"] if c["title"] == "Key")
        self.assertEqual(table["columnSettings"][0], {"columnId": key_id, "order": 0})
        self.assertEqual([r["mode"] for r in table["sort"]], ["ASC", "DESC"])

    def test_republish_is_idempotent(self):
        publish.publish(self.nc, self.files, self.rows, share_with="steve")
        _, counts = publish.publish(self.nc, self.files, self.rows, share_with="steve")
        self.assertEqual(counts, (0, 0, 5))
        state = self.nc.state
        self.assertEqual((len(state["tables"]), len(state["rows"]), len(state["views"]), len(state["shares"])),
                         (1, 5, 2, 1))

    def test_half_configured_view_is_repaired(self):
        table_id, _ = publish.publish(self.nc, self.files, self.rows)
        self.nc.state["views"][0].pop("filter")
        publish.publish(self.nc, self.files, self.rows)
        self.assertIn("filter", self.nc.state["views"][0])
        self.assertEqual(len(self.nc.state["views"]), len(publish.VIEWS))

    def test_mock_rejects_the_old_string_format(self):
        import mock_nextcloud
        self.assertIsNotNone(mock_nextcloud.view_update_problem({"columns": "[1,2]"}))
        self.assertIsNotNone(mock_nextcloud.view_update_problem({"sort": [{"columnId": 1, "mode": "down"}]}))
        self.assertIsNone(mock_nextcloud.view_update_problem(publish.view_settings(
            {t: i for i, (t, _) in enumerate(publish.COLUMNS)}, "IFEval", True)))

    def test_changed_value_updates_in_place(self):
        publish.publish(self.nc, self.files, self.rows)
        changed = [dict(r) for r in self.rows]
        changed[0]["Note"] = "edited"
        _, counts = publish.publish(self.nc, self.files, changed)
        self.assertEqual(counts, (0, 1, 4))
        self.assertEqual(len(self.nc.state["rows"]), 5)

    def test_numbers_returned_as_floats_are_unchanged(self):
        self.assertTrue(publish._same(198.0, 198))
        self.assertTrue(publish._same("43.94", 43.94))
        self.assertFalse(publish._same(43.0, 43.94))


class ClientTest(unittest.TestCase):
    def test_network_error_becomes_nextcloud_error(self):
        import urllib.error

        def refuse(req, timeout=None):
            raise urllib.error.URLError("connection refused")
        nc = publish.Nextcloud("http://x", "u", "p", opener=refuse)
        with self.assertRaises(publish.NextcloudError):
            nc.tables("GET", "/tables")

    def test_webdav_paths_are_quoted(self):
        nc = publish.Nextcloud("https://nc/", "eval-reports", "p")
        self.assertEqual(nc._dav("Reports/eval-runner/a b.md"),
                         "/remote.php/dav/files/eval-reports/Reports/eval-runner/a%20b.md")


class MainTest(unittest.TestCase):
    def test_dry_run_writes_files(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as out:
            make_tree(root)
            with unittest.mock.patch("builtins.print"):
                rc = publish.main(["--results-root", root, "--dry-run", out, "--findings", "/nonexistent"])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(os.path.join(out, "leaderboard.md")))

    def test_unconfigured_publish_exits_2(self):
        with tempfile.TemporaryDirectory() as root:
            with unittest.mock.patch.dict(os.environ, {}, clear=True), \
                    unittest.mock.patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(publish.main(["--results-root", root, "--findings", "/nonexistent"]), 2)


if __name__ == "__main__":
    unittest.main()
