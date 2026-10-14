import unittest

import vuln_triage as v

TRACKER = {
    "vim": {"CVE-1": {"releases": {"trixie": {"status": "open", "urgency": "not yet assigned"}}},
            "CVE-2": {"releases": {"trixie": {"status": "open", "urgency": "low"}}},
            "CVE-3": {"releases": {"trixie": {"status": "open", "urgency": "medium"}}}},
    "python-urllib3": {"CVE-4": {"releases": {"trixie": {"status": "resolved", "fixed_version": "2.3.0-3+deb13u1"}}}},
    "zlib": {"CVE-5": {"releases": {"trixie": {"status": "resolved", "fixed_version": "0"}}},
             "CVE-6": {"releases": {"bookworm": {"status": "open"}}}},
}


class Triage(unittest.TestCase):
    def test_classes(self):
        pairs = [("vim", "CVE-1", 27, "1", "Debian GNU/Linux"), ("vim", "CVE-2", 3, "1", "Debian GNU/Linux"),
                 ("vim", "CVE-3", 2, "1", "Debian GNU/Linux"), ("urllib3", "CVE-4", 21, "1.26.20", "Debian GNU/Linux"),
                 ("zlib1g", "CVE-5", 27, "1", "Debian GNU/Linux"), ("zlib1g", "CVE-6", 1, "1", "Debian GNU/Linux"),
                 ("zlib1g", "CVE-7", 1, "1", "Debian GNU/Linux"), ("gawk", "CVE-8", 1, "1", "Amazon Linux")]
        got = {(r[0], r[1]): r[4] for r in v.triage(pairs, TRACKER)}
        self.assertEqual(got[("vim", "CVE-1")], "unassigned")
        self.assertEqual(got[("vim", "CVE-2")], "open-low")
        self.assertEqual(got[("vim", "CVE-3")], "open-triaged")
        self.assertEqual(got[("urllib3", "CVE-4")], "fix-available")
        self.assertEqual(got[("zlib1g", "CVE-5")], "no-fix-needed")
        self.assertEqual(got[("zlib1g", "CVE-6")], "untracked")       # tracked, but not for this release
        self.assertEqual(got[("zlib1g", "CVE-7")], "untracked")       # not in the tracker at all
        self.assertEqual(got[("gawk", "CVE-8")], "non-debian")

    def test_summary_counts_hosts_as_findings(self):
        rows = [("a", "c1", 5, "1", "unassigned"), ("a", "c2", 3, "1", "unassigned")]
        self.assertEqual(v.summarize(rows), {"unassigned": {"findings": 8, "pairs": 2}})


if __name__ == "__main__":
    unittest.main()
