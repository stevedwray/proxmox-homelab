import unittest
from types import SimpleNamespace

import github_runner_metrics as m

NAMES = [
    "SelfUpdate-20260620-170934.log.succeed",
    "SelfUpdate-20260906-170926.log.succeed",
    "SelfUpdate-20261007-170928.log.failed",
    "SelfUpdate-20261008-170924.log.failed",
    "SelfUpdate-20261009-170929.log.failed",
    "Runner_20261009-024939-utc.log",        # not a self-update log
    "SelfUpdate-20261010-170930.log.pending",  # not a result we know
    "SelfUpdate-bad.log.failed",
]


class Parsing(unittest.TestCase):
    def test_only_self_update_results_are_read_oldest_first(self):
        ups = m.parse_updates(NAMES)
        self.assertEqual([r for _, r in ups], ["succeed", "succeed", "failed", "failed", "failed"])
        self.assertEqual(ups, sorted(ups))

    def test_filename_time_is_utc(self):
        # 2026-10-07 17:09:28 UTC
        self.assertEqual(m.parse_updates(["SelfUpdate-20261007-170928.log.failed"])[0][0], 1791392968)


class Summary(unittest.TestCase):
    def test_failures_since_the_last_success(self):
        failed, ok, consecutive = m.summarize(m.parse_updates(NAMES))
        self.assertEqual(consecutive, 3)
        self.assertGreater(failed, ok)

    def test_a_later_success_resets_the_streak(self):
        names = NAMES + ["SelfUpdate-20261011-170930.log.succeed"]
        self.assertEqual(m.summarize(m.parse_updates(names))[2], 0)

    def test_no_history_is_zeros(self):
        self.assertEqual(m.summarize([]), (0, 0, 0))

    def test_only_failures_counts_them_all(self):
        names = ["SelfUpdate-20261007-170928.log.failed", "SelfUpdate-20261008-170924.log.failed"]
        self.assertEqual(m.summarize(m.parse_updates(names)), (m.parse_updates(names)[1][0], 0, 2))


class Service(unittest.TestCase):
    def test_active_unit_listed(self):
        run = lambda *a, **k: SimpleNamespace(stdout="actions.runner.x.service loaded active running GitHub Actions Runner\n")
        self.assertTrue(m.service_active(run))

    def test_nothing_listed_is_down(self):
        self.assertFalse(m.service_active(lambda *a, **k: SimpleNamespace(stdout="")))

    def test_missing_systemctl_is_down_not_a_crash(self):
        def boom(*a, **k):
            raise FileNotFoundError("systemctl")
        self.assertFalse(m.service_active(boom))


class Render(unittest.TestCase):
    def test_output_has_every_metric_with_type_lines(self):
        text = m.render(100, 50, 2, True, 999)
        for name in ("last_failed_timestamp_seconds", "last_succeeded_timestamp_seconds", "consecutive_failures"):
            self.assertIn(f"github_runner_selfupdate_{name} ", text)
        self.assertIn("github_runner_service_active 1\n", text)
        self.assertEqual(text.count("# TYPE"), 5)
        self.assertIn("github_runner_selfupdate_consecutive_failures 2\n", text)


if __name__ == "__main__":
    unittest.main()
