"""Tests for the ATT&CK extractor and loader. Run: python3 -m unittest test_attack.py (from this directory)."""
import copy
import gzip
import json
import tempfile
import unittest
from pathlib import Path

import attack_load as load
import extract_attack as extract

HERE = Path(__file__).resolve().parent
REAL_DATASET = HERE / "attack-enterprise-20.0.json.gz"
REAL_MAPPING = HERE.parents[3] / ".." / "docs" / "threat-model" / "attack" / "authentik-stack.yaml"

# A tiny dataset: one technique (T1110.001) with an IdP analytic that needs DC0002 and a Linux analytic that also
# needs DC0002, one mitigation, one other technique with no analytic.
DATASET = {
    "attack_version": "20.0",
    "tactics": [["TA0006", "Credential Access", "credential-access"]],
    "techniques": [["T1110", "Brute Force", ["Linux", "Identity Provider"], ["credential-access"], None],
                   ["T1110.001", "Password Guessing", ["Linux", "Identity Provider"], ["credential-access"], "T1110"],
                   ["T1499", "Endpoint Denial of Service", ["Linux"], ["impact"], None]],
    "mitigations": [["M1032", "Multi-factor Authentication"]],
    "mitigates": [["M1032", "T1110.001"]],
    "data_components": [["DC0002", "User Account Authentication"], ["DC0038", "Application Log Content"]],
    "detections": [["DET0001", "Brute force detection", ["T1110.001"], ["AN0001", "AN0002"]]],
    "analytics": [["AN0001", ["Identity Provider"], [["DC0002", "idp:auth"]]],
                  ["AN0002", ["Linux"], [["DC0002", "linux:auth.log"]]]],
}
MAPPING = {
    "attack_version": "20.0", "process": "p-x", "platforms": ["Linux", "Identity Provider"],
    "sensors": [{"key": "sensor:x:agent", "name": "agent", "evidence": "seen",
                 "provides": [{"data_component": "DC0002", "platforms": ["Linux"], "log_source": "linux:auth.log", "level": "observed"}]}],
    "controls": [{"key": "control:x:mfa", "name": "MFA", "implements": ["M1032"], "strength": "partial", "evidence": "seen"}],
    "assessments": [{"technique": "T1110.001", "applies": True, "basis": "login page", "platforms": ["Identity Provider"]},
                    {"technique": "T1499", "applies": False, "basis": "not reachable"}],
}


class Validation(unittest.TestCase):
    def test_a_good_mapping_is_valid(self):
        self.assertEqual(load.validate_mapping(DATASET, MAPPING), [])

    def test_unknown_ids_and_version_mismatch_are_errors(self):
        bad = copy.deepcopy(MAPPING)
        bad["attack_version"] = "19.0"
        bad["assessments"][0]["technique"] = "T9999"
        bad["controls"][0]["implements"] = ["M9999"]
        bad["sensors"][0]["provides"][0]["data_component"] = "DC9999"
        text = " ".join(load.validate_mapping(DATASET, bad))
        for needle in ("19.0", "T9999", "M9999", "DC9999"):
            self.assertIn(needle, text)

    def test_every_claim_needs_its_reason(self):
        bad = copy.deepcopy(MAPPING)
        bad["assessments"][1]["basis"] = ""
        bad["sensors"][0]["evidence"] = ""
        bad["controls"][0]["strength"] = "strong"
        bad["sensors"][0]["provides"][0]["platforms"] = ["Windows"]
        text = " ".join(load.validate_mapping(DATASET, bad))
        self.assertIn("no basis", text)
        self.assertIn("no evidence", text)
        self.assertIn("full|partial", text)
        self.assertIn("platforms", text)

    def test_an_assessment_cannot_name_a_platform_outside_the_mapping(self):
        bad = copy.deepcopy(MAPPING)
        bad["assessments"][0]["platforms"] = ["Windows"]
        self.assertIn("non-empty subset", " ".join(load.validate_mapping(DATASET, bad)))


class Coverage(unittest.TestCase):
    def _row(self, mapping, tid="T1110.001"):
        return next(r for r in load.coverage(DATASET, mapping) if r["technique"] == tid)

    def test_ssh_logs_are_not_telemetry_for_the_web_login(self):
        # DC0002 is collected, but on Linux; the surface assessed is the Identity Provider login
        row = self._row({**MAPPING, "assessments": [dict(MAPPING["assessments"][0], applies=True)]})
        self.assertEqual(row["telemetry"], "none")
        self.assertEqual(row["analytics"][0]["platforms"], ["Identity Provider"])

    def test_the_same_data_does_cover_the_linux_surface(self):
        linux = {**MAPPING, "assessments": [dict(MAPPING["assessments"][0], platforms=["Linux"])]}
        self.assertEqual(self._row(linux)["telemetry"], "full")

    def test_collecting_it_on_the_right_platform_covers_the_login(self):
        m = copy.deepcopy(MAPPING)
        m["sensors"][0]["provides"][0]["platforms"] = ["Linux", "Identity Provider"]
        self.assertEqual(self._row(m)["telemetry"], "full")

    def test_a_technique_with_no_analytic_says_so(self):
        m = copy.deepcopy(MAPPING)
        m["assessments"][1] = {"technique": "T1499", "applies": True, "basis": "x"}
        self.assertEqual(self._row(m, "T1499")["telemetry"], "no-analytic")

    def test_mitigation_comes_from_a_control_that_implements_it(self):
        self.assertEqual(self._row(MAPPING)["mitigations"], [("control:x:mfa", "partial", "M1032")])

    def test_not_applicable_techniques_carry_no_coverage(self):
        row = self._row(MAPPING, "T1499")
        self.assertFalse(row["applies"])
        self.assertNotIn("telemetry", row)

    def test_missing_data_components_are_ranked_by_what_they_would_help(self):
        rows = load.coverage(DATASET, {**MAPPING, "assessments": [dict(MAPPING["assessments"][0], applies=True)]})
        ranked = load.missing_data_components(DATASET, rows)
        self.assertEqual((ranked[0][0], ranked[0][1]), (1, "DC0002"))


class Statements(unittest.TestCase):
    def test_reference_load_covers_every_layer_and_prunes_old_versions_last(self):
        stmts = load.reference_statements(DATASET)
        text = " ".join(s["statement"] for s in stmts)
        for label in ("AttackTactic", "AttackTechnique", "AttackMitigation", "AttackDataComponent", "AttackDetection",
                      "AttackAnalytic"):
            self.assertIn(f"MERGE (n:{label}", text)
        for rel in ("IN_TACTIC", "SUBTECHNIQUE_OF", "MITIGATES", "DETECTS", "HAS_ANALYTIC", "USES_DATA"):
            self.assertIn(rel, text)
        self.assertTrue(all("DELETE" in s["statement"] for s in stmts[-2:]))
        self.assertNotIn("DELETE", " ".join(s["statement"] for s in stmts[:-2]))

    def test_nothing_from_the_dataset_is_interpolated_into_cypher(self):
        evil = copy.deepcopy(DATASET)
        evil["techniques"][0][1] = "x'}) DETACH DELETE (n) //"
        text = " ".join(s["statement"] for s in load.reference_statements(evil))
        self.assertNotIn("DETACH DELETE (n) //", text)

    def test_reference_nodes_never_carry_homelab(self):
        text = " ".join(s["statement"] for s in load.reference_statements(DATASET) if "MERGE (n:" in s["statement"])
        self.assertNotIn("Homelab", text)

    def test_overlay_requires_the_process_and_scopes_its_prune_to_it(self):
        stmts = load.overlay_statements(MAPPING, "run1")
        self.assertTrue(stmts[0].get("require_rows"))
        prune = " ".join(s["statement"] for s in stmts[-2:])
        for scope in ("endNode(x).key = $process", "startNode(x).process_key = $process", "startNode(x).key = $process",
                      "n.process_key = $process"):
            self.assertIn(scope, prune)
        self.assertTrue(all(s.get("parameters", {}).get("process") == "p-x" for s in stmts[-2:]))

    def test_overlay_never_creates_homelab_nodes(self):
        merges = [s["statement"] for s in load.overlay_statements(MAPPING, "run1") if "MERGE (n:" in s["statement"]]
        self.assertTrue(merges and all("Homelab" not in m for m in merges))

    def test_large_loads_are_batched(self):
        big = copy.deepcopy(DATASET)
        big["data_components"] = [[f"DC{i:04d}", f"c{i}"] for i in range(load.BATCH * 2 + 5)]
        stmts = [s for s in load.reference_statements(big) if "AttackDataComponent {key" in s["statement"] and "MERGE (n:" in s["statement"]]
        self.assertEqual([len(s["parameters"]["rows"]) for s in stmts], [load.BATCH, load.BATCH, 5])


class Extract(unittest.TestCase):
    def _bundle(self):
        ref = lambda i: [{"source_name": "mitre-attack", "external_id": i}]
        return {"objects": [
            {"type": "x-mitre-collection", "x_mitre_version": "9.9", "modified": "2026-01-01T00:00:00Z"},
            {"type": "x-mitre-tactic", "id": "tac1", "name": "Credential Access", "x_mitre_shortname": "credential-access",
             "external_references": ref("TA0006")},
            {"type": "attack-pattern", "id": "t1", "name": "Brute Force", "x_mitre_platforms": ["Linux"],
             "kill_chain_phases": [{"kill_chain_name": "mitre-attack", "phase_name": "credential-access"}], "external_references": ref("T1110")},
            {"type": "attack-pattern", "id": "t2", "name": "Password Guessing", "x_mitre_platforms": ["Linux"],
             "kill_chain_phases": [{"kill_chain_name": "mitre-attack", "phase_name": "credential-access"}], "external_references": ref("T1110.001")},
            {"type": "attack-pattern", "id": "t3", "name": "Old", "revoked": True, "external_references": ref("T0001")},
            {"type": "course-of-action", "id": "m1", "name": "MFA", "external_references": ref("M1032")},
            {"type": "x-mitre-data-component", "id": "dc1", "name": "User Account Authentication", "external_references": ref("DC0002")},
            {"type": "x-mitre-analytic", "id": "an1", "x_mitre_platforms": ["Linux"], "external_references": ref("AN0001"),
             "x_mitre_log_source_references": [{"x_mitre_data_component_ref": "dc1", "name": "linux:auth.log"},
                                               {"x_mitre_data_component_ref": "gone", "name": "x"}]},
            {"type": "x-mitre-detection-strategy", "id": "det1", "name": "BF", "x_mitre_analytic_refs": ["an1"], "external_references": ref("DET0001")},
            {"type": "relationship", "relationship_type": "subtechnique-of", "source_ref": "t2", "target_ref": "t1"},
            {"type": "relationship", "relationship_type": "mitigates", "source_ref": "m1", "target_ref": "t2"},
            {"type": "relationship", "relationship_type": "mitigates", "source_ref": "m1", "target_ref": "t3"},
            {"type": "relationship", "relationship_type": "detects", "source_ref": "det1", "target_ref": "t2"},
        ]}

    def test_extracts_live_objects_and_links(self):
        d = extract.extract(self._bundle(), "abc")
        self.assertEqual(d["attack_version"], "9.9")
        self.assertEqual([t[0] for t in d["techniques"]], ["T1110", "T1110.001"])  # the revoked one is gone
        self.assertEqual(d["techniques"][1][4], "T1110")
        self.assertEqual(d["mitigates"], [["M1032", "T1110.001"]])  # not to the revoked technique
        self.assertEqual(d["detections"], [["DET0001", "BF", ["T1110.001"], ["AN0001"]]])
        self.assertEqual(d["analytics"], [["AN0001", ["Linux"], [["DC0002", "linux:auth.log"]]]])  # dangling ref dropped
        self.assertEqual(d["source_sha256"], "abc")

    def test_output_is_byte_identical_for_the_same_input(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "b.json"
            src.write_text(json.dumps(self._bundle()))
            a, b = Path(d) / "a" / "out.gz", Path(d) / "b" / "out.gz"
            a.parent.mkdir(); b.parent.mkdir()
            extract.main([str(src), str(a)])
            extract.main([str(src), str(b)])
            self.assertEqual(a.read_bytes(), b.read_bytes())


@unittest.skipUnless(REAL_DATASET.exists(), "pinned dataset not present")
class RealData(unittest.TestCase):
    """Guards against drift: the committed mapping must stay valid against the committed dataset."""

    @classmethod
    def setUpClass(cls):
        cls.ds = load.load_dataset(REAL_DATASET)

    def test_dataset_is_the_pinned_version_and_complete(self):
        self.assertEqual(self.ds["attack_version"], "20.0")
        self.assertGreater(len(self.ds["techniques"]), 600)
        self.assertTrue(any("Containers" in t[2] for t in self.ds["techniques"]))
        self.assertTrue(any("Identity Provider" in t[2] for t in self.ds["techniques"]))
        self.assertEqual(len(self.ds["source_sha256"]), 64)

    def test_every_dangling_free(self):
        ids = {t[0] for t in self.ds["techniques"]}
        self.assertTrue(all(t in ids for _m, t in self.ds["mitigates"]))

    def test_authentik_mapping_is_valid_against_it(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        mapping = yaml.safe_load(Path(REAL_MAPPING).resolve().read_text())
        self.assertEqual(load.validate_mapping(self.ds, mapping), [])
        rows = load.coverage(self.ds, mapping)
        self.assertEqual(len(rows), len(mapping["assessments"]))


if __name__ == "__main__":
    unittest.main()
