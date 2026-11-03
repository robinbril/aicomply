import json
import os
import tempfile
import unittest

from aicomply.frameworks import load_frameworks, parse_framework, validate
from aicomply.scoring import CRITICAL_CAP, band, exit_code, load_findings, score_all, score_framework
from tests.helpers import FRAMEWORKS, MINI


def findings(**statuses):
    return {k.replace("_", "-"): {"status": v, "gap": "absent"} for k, v in statuses.items()}


class ScoringTest(unittest.TestCase):
    def setUp(self):
        self.fw = parse_framework(MINI, "test.yaml")

    def test_all_pass_scores_100_and_na_drops_out(self):
        r = score_framework(self.fw, findings(T_CRIT="pass", T_HIGH="pass", T_MED="pass", T_LOW="na"))
        self.assertEqual(r["score"], 100.0)
        self.assertEqual(r["band"], "Compliant")

    def test_failed_critical_caps_at_39(self):
        r = score_framework(self.fw, findings(T_CRIT="fail", T_HIGH="pass", T_MED="pass", T_LOW="pass"))
        self.assertEqual(r["raw_score"], round(100 * 6 / 11, 1))
        self.assertEqual(r["score"], CRITICAL_CAP)
        self.assertEqual(band(r["score"]), "Critical fail")

    def test_planned_is_not_a_verdict_and_scores_as_fail(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "f.json")
            with open(path, "w") as f:
                json.dump([
                    {"id": "T-CRIT", "status": "planned", "roadmap_ref": {"path": "ROADMAP.md", "quote": "we will"}},
                    {"id": "T-HIGH", "status": "pass"},
                ], f)
            loaded = load_findings(path)
        self.assertEqual(loaded["T-CRIT"]["status"], "fail")
        r = score_framework(self.fw, loaded)
        self.assertEqual(r["score"], min(r["raw_score"], CRITICAL_CAP))
        self.assertTrue(r["capped"])

    def test_no_partial_credit_anywhere(self):
        # The only weights a control can earn are 0 and its full weight.
        r = score_framework(self.fw, findings(T_CRIT="pass", T_HIGH="fail", T_MED="fail", T_LOW="fail"))
        self.assertEqual(r["raw_score"], round(100 * 5 / 11, 1))

    def test_unassessed_controls_count_as_fail(self):
        r = score_framework(self.fw, findings(T_CRIT="pass"))
        self.assertEqual(r["counts"]["unassessed"], 3)
        self.assertEqual(r["raw_score"], round(100 * 5 / 11, 1))
        # A framework with no verdicts at all is not "out of scope", it is 0.
        self.assertEqual(score_framework(self.fw, {})["score"], 0.0)

    def test_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "f.json")
            with open(path, "w") as f:
                json.dump([{"id": "T-CRIT", "status": "fail"}, {"id": "T-CRIT", "status": "pass"}], f)
            with self.assertRaises(ValueError):
                load_findings(path)

    def test_legacy_shapes_parse(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "f.json")
            with open(path, "w") as f:
                json.dump({"T-CRIT": "fail", "T-HIGH": {"result": "pass"}}, f)
            loaded = load_findings(path)
        self.assertEqual(loaded["T-CRIT"]["status"], "fail")
        self.assertEqual(loaded["T-HIGH"]["status"], "pass")

    def test_exit_code(self):
        bad = score_all([self.fw], findings(T_CRIT="fail"))
        good = score_all([self.fw], findings(T_CRIT="pass", T_HIGH="pass"))
        self.assertEqual(exit_code(bad), 1)
        self.assertEqual(exit_code(good), 0)


class CatalogueTest(unittest.TestCase):
    def test_shipped_catalogue_is_clean(self):
        fws = load_frameworks(FRAMEWORKS)
        self.assertEqual(validate(fws), [])
        self.assertGreaterEqual(len(fws), 15)

    def test_every_framework_has_parts_for_the_matrix_tabs(self):
        for fw in load_frameworks(FRAMEWORKS):
            parts = {c["part"] for c in fw["controls"]}
            self.assertGreaterEqual(len(parts), 2, fw["file"])

    def test_validate_catches_bad_weight_and_duplicate_id(self):
        bad = MINI.replace("weight: 3", "weight: 4")
        fws = [parse_framework(bad, "a.yaml"), parse_framework(MINI, "b.yaml")]
        problems = "\n".join(validate(fws))
        self.assertIn("does not match severity", problems)
        self.assertIn("already used", problems)

    def test_block_scalar_is_reported_not_dropped(self):
        bad = MINI.replace('requirement: "r"', "requirement: |", 1)
        self.assertTrue(any("block scalar" in p for p in validate([parse_framework(bad, "a.yaml")])))


if __name__ == "__main__":
    unittest.main()
