import json
import os
import tempfile
import unittest
from datetime import date

from aicomply.egress.asar import build_asar
from aicomply.egress.scanner import failing_controls, scan
from aicomply.frameworks import load_frameworks, parse_framework
from aicomply.render.html import render
from aicomply.riskmatrix import build_register, heatmap, likelihood
from aicomply.scoring import score_all
from tests.helpers import FRAMEWORKS, MINI, ROOT

DEMO = os.path.join(ROOT, "examples", "demo-app")


class EgressTest(unittest.TestCase):
    def test_demo_app_destinations(self):
        r = scan(DEMO)
        by = {d["vendor"]: d for d in r["destinations"]}
        self.assertIn("OpenAI", by)
        self.assertIn("email", by["OpenAI"]["data_hints"])
        self.assertIn("Slack", by)  # found through SLACK_WEBHOOK, not a URL
        self.assertIn("Google Fonts", by)
        self.assertEqual(by["PostHog"]["data_hints"], ["email"])
        self.assertEqual(by["Google Analytics / Tag Manager"]["data_hints"], [])
        self.assertTrue(any(s["setting"] == "sendDefaultPii enabled" for s in r["risky_settings"]))

    def test_urls_in_comments_are_not_egress(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.py"), "w") as f:
                f.write("# docs: https://api.openai.com/v1/chat\nx = 1\n")
            self.assertEqual(scan(d)["destinations"], [])

    def test_unknown_host_only_when_called(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.js"), "w") as f:
                f.write('const help = "https://help.vendor-x.io/page";\nfetch("https://collect.vendor-y.io/e", {body: user.email});\n')
            vendors = [x["vendor"] for x in scan(d)["destinations"]]
        self.assertEqual(vendors, ["collect.vendor-y.io"])

    def test_own_hosts_are_first_party(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.js"), "w") as f:
                f.write('fetch("https://api.mycorp.eu/v1/x");\n')
            self.assertEqual(scan(d, own_hosts=["mycorp.eu"])["destinations"], [])

    def test_reads_inside_asar(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "app.asar")
            with open(path, "wb") as f:
                f.write(build_asar({"dist/main.js": b'import Anthropic from "@anthropic-ai/sdk";\nconst prompt = user.email;\n'}))
            r = scan(path)
        [dest] = r["destinations"]
        self.assertEqual(dest["vendor"], "Anthropic")
        self.assertTrue(dest["evidence"][0]["where"].startswith("app.asar!/dist/main.js"))

    def test_secrets_in_evidence_are_masked(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, ".env"), "w") as f:
                f.write("OPENAI_API_KEY=sk-proj-" + "x" * 40 + "\n")
            with open(os.path.join(d, "a.py"), "w") as f:
                f.write('import openai\nkey = "sk-ant-' + "y" * 40 + '"\n')
            r = json.dumps(scan(d))
        self.assertNotIn("x" * 40, r)
        self.assertNotIn("y" * 40, r)
        self.assertIn("***", r)

    def test_large_asar_is_read_and_a_broken_one_is_listed(self):
        with tempfile.TemporaryDirectory() as d:
            big = build_asar({"main.js": b'import OpenAI from "openai";\n' + b"// pad\n" * 4_000_000})
            with open(os.path.join(d, "app.asar"), "wb") as f:
                f.write(big)
            with open(os.path.join(d, "bad.asar"), "wb") as f:
                f.write(b"\x04\x00\x00\x00garbage")
            r = scan(d)
        self.assertGreater(len(big), 25_000_000)
        self.assertEqual([x["vendor"] for x in r["destinations"]], ["OpenAI"])
        self.assertTrue(any(s.startswith("bad.asar") for s in r["skipped"]))

    def test_failing_controls_maps_personal_data_flows(self):
        hits = failing_controls(scan(DEMO))
        self.assertIn("OpenAI", hits["GDPR-PII-TO-EXTERNAL-LLM"])


class MatrixTest(unittest.TestCase):
    def test_likelihood_model(self):
        self.assertEqual(likelihood(None, [])[0], 3)
        self.assertEqual(likelihood({"status": "pass"}, [])[0], 1)
        self.assertEqual(likelihood({"status": "pass"}, ["OpenAI"])[0], 2)
        self.assertEqual(likelihood({"status": "fail", "gap": "absent"}, [])[0], 4)
        self.assertEqual(likelihood({"status": "fail", "gap": "violating"}, [])[0], 5)
        self.assertEqual(likelihood({"status": "fail", "gap": "absent"}, ["OpenAI"])[0], 5)

    def test_register_scores_and_deadlines(self):
        fw = parse_framework(MINI, "test.yaml")
        findings = {"T-CRIT": {"status": "fail", "gap": "violating"}, "T-HIGH": {"status": "pass"}, "T-LOW": {"status": "na"}}
        reg = build_register([fw], findings, {}, score_all([fw], findings), date(2026, 11, 3), {})[0]
        rows = {r["id"]: r for r in reg["rows"]}
        self.assertNotIn("T-LOW", rows)
        self.assertEqual((rows["T-CRIT"]["score"], rows["T-CRIT"]["level"], rows["T-CRIT"]["due"]), (25, "critical", "2026-11-17"))
        self.assertEqual(rows["T-HIGH"]["treatment"], "Monitor")
        self.assertEqual(rows["T-MED"]["status"], "unassessed")
        self.assertEqual(heatmap(reg["rows"])[4][4], 1)
        self.assertEqual(reg["parts"], ["Part A", "Part B"])

    def test_html_has_a_tab_per_framework_and_per_part(self):
        fws = load_frameworks(FRAMEWORKS)
        findings = {}
        scores = score_all(fws, findings)
        reg = build_register(fws, findings, {}, scores, date(2026, 11, 3), {})
        html = render(reg, scores, {"system": "Demo", "date": "2026-11-03", "controls": 1, "assessed": 0}, None, [], [])
        for fw in fws:
            self.assertIn(f'data-panel="fw-{fw["source"]}"', html)
        parts = sum(len({c["part"] for c in fw["controls"]}) for fw in fws)
        self.assertEqual(html.count('class="panel part '), parts + len(fws))
        self.assertNotIn("<script src", html)


if __name__ == "__main__":
    unittest.main()
