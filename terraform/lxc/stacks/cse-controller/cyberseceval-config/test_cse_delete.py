"""Unit tests for cse_tasks.delete_run_dirs: the run dir, its Nextcloud
report folder (found by stamp, or for older runs by start time) and its
Compare row, with WebDAV faked."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[3] / "ansible" / "files" / "framework-lock"))

import cse_tasks  # noqa: E402

BASE = "https://nc/remote.php/dav/files/cse-reports"
ENV = {"NEXTCLOUD_REPORTS_WEBDAV_URL": BASE, "NEXTCLOUD_REPORTS_USER": "cse-reports",
       "NEXTCLOUD_REPORTS_APP_PASSWORD": "x"}
JOB = "3bf79d63-1111-2222-3333-444455556666"
STARTED = "2026-10-07T18:36:01.123456+00:00"


class FakeDav:
    """A Nextcloud folder tree: {path: contents}; folders are paths with children."""

    def __init__(self, files):
        self.files = dict(files)
        self.calls = []

    def children(self, folder):
        prefix = folder + "/"
        return sorted({p[len(prefix):].split("/", 1)[0] for p in self.files if p.startswith(prefix)})

    def __call__(self, method, url, auth, headers=None):
        path = url[len(BASE) + 1:]
        self.calls.append((method, path))
        if method == "PROPFIND":
            names = self.children(path)
            if not names and path not in self.files:
                return 404, b""
            hrefs = [f"/remote.php/dav/files/cse-reports/{path}/"] + [
                f"/remote.php/dav/files/cse-reports/{path}/{n}/" for n in names]
            return 207, "".join(f"<d:response><d:href>{h}</d:href></d:response>" for h in hrefs).encode()
        if method == "GET":
            return (200, self.files[path].encode()) if isinstance(self.files.get(path), str) else (404, b"")
        if method == "DELETE":
            gone = [p for p in self.files if p == path or p.startswith(path + "/")]
            for p in gone:
                del self.files[p]
            return (204 if gone else 404), b""
        return 405, b""


class DeleteRunDirsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runs = Path(self.tmp.name)
        self.sent = []
        for p in (mock.patch.object(cse_tasks, "RUNS_DIR", self.runs),
                  mock.patch.dict(os.environ, ENV),
                  mock.patch.object(cse_tasks.app, "send_task",
                                    side_effect=lambda name, args=None, queue=None: self.sent.append((name, args, queue)))):
            p.start()
            self.addCleanup(p.stop)

    def run_dir(self, **meta):
        d = self.runs / f"panel-{JOB}"
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"benchmark": "mitre", "started_at": STARTED, **meta}))
        return d

    def delete(self, dav):
        with mock.patch.object(cse_tasks, "_dav", dav):
            return cse_tasks.delete_run_dirs.apply(args=[[JOB, "../etc"]]).get()

    def test_stamped_run_loses_its_folder_and_the_emptied_submission_folder(self):
        d = self.run_dir(run_group_stamp="2026-10-07_1836_abcd1234")
        dav = FakeDav({"Reports/cyberseceval/2026-10-07_1836_abcd1234/mitre/results.md": "x"})
        out = self.delete(dav)
        self.assertFalse(d.exists())
        self.assertEqual(dav.files, {})
        self.assertEqual(out["reports"][JOB], "Reports/cyberseceval/2026-10-07_1836_abcd1234/mitre: deleted")
        self.assertEqual(out["skipped"], ["../etc"])
        self.assertEqual(self.sent, [(cse_tasks.COMPARE_FORGET_TASK, [[JOB]], "eval-runner-ctl")])

    def test_suite_mates_keep_the_submission_folder(self):
        self.run_dir(run_group_stamp="2026-10-07_1836_abcd1234")
        dav = FakeDav({"Reports/cyberseceval/2026-10-07_1836_abcd1234/mitre/results.md": "x",
                       "Reports/cyberseceval/2026-10-07_1836_abcd1234/instruct/results.md": "y"})
        self.delete(dav)
        self.assertEqual(list(dav.files), ["Reports/cyberseceval/2026-10-07_1836_abcd1234/instruct/results.md"])

    def test_older_run_is_found_by_its_exact_start_time(self):
        self.run_dir()
        dav = FakeDav({
            # same benchmark, a different run in an earlier submission
            "Reports/cyberseceval/2026-10-07_1700_aaaaaaaa/mitre/results.md": "**Started:** 2026-10-07T17:00:00+00:00",
            "Reports/cyberseceval/2026-10-07_1830_bbbbbbbb/mitre/results.md": f"**Started:** {STARTED}  \n",
            # submitted after this run started: never it
            "Reports/cyberseceval/2026-10-07_1900_cccccccc/mitre/results.md": f"**Started:** {STARTED}",
        })
        out = self.delete(dav)
        self.assertEqual(out["reports"][JOB], "Reports/cyberseceval/2026-10-07_1830_bbbbbbbb/mitre: deleted")
        self.assertEqual(sorted(dav.files), ["Reports/cyberseceval/2026-10-07_1700_aaaaaaaa/mitre/results.md",
                                             "Reports/cyberseceval/2026-10-07_1900_cccccccc/mitre/results.md"])

    def test_no_report_folder_still_deletes_the_run(self):
        d = self.run_dir()
        out = self.delete(FakeDav({}))
        self.assertFalse(d.exists())
        self.assertEqual(out["reports"][JOB], "no report folder found")
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
