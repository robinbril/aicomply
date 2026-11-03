import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from aicomply.frameworks import parse_framework
from aicomply.regsync.fetchers import CellarFetcher, FetchError, IsoFetcher, SruFetcher, normalise
from aicomply.regsync.sync import (
    FAILURE_THRESHOLD,
    list_changes,
    open_changes_by_framework,
    review_change,
    run_sync,
)
from tests.helpers import MINI

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
LONG = "Article 1 subject matter. " * 20


class FakeFetcher:
    def __init__(self, text=LONG, error=None):
        self.text, self.error = text, error

    def fetch(self, source):
        if self.error:
            raise FetchError(self.error)
        return self.text


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.reg = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.reg, "changes"))
        with open(os.path.join(self.reg, "sources.json"), "w") as f:
            json.dump({"sources": [{"id": "law", "name": "Test law", "strategy": "html", "frameworks": ["test"], "interval_days": 7}]}, f)
        self.fws = [parse_framework(MINI, "test.yaml")]

    def tearDown(self):
        shutil.rmtree(self.reg)

    def sync(self, fetcher, now, **kw):
        return run_sync(self.reg, self.fws, fetchers={"html": fetcher}, now=now, **kw)

    def state(self):
        with open(os.path.join(self.reg, "state.json")) as f:
            return json.load(f)["law"]

    def test_first_run_sets_baseline_then_unchanged(self):
        self.assertEqual(self.sync(FakeFetcher(), T0).outcomes[0].result, "new")
        self.assertEqual(self.sync(FakeFetcher(), T0 + timedelta(days=7)).outcomes[0].result, "unchanged")
        self.assertEqual(list_changes(self.reg), [])

    def test_interval_is_respected(self):
        self.sync(FakeFetcher(), T0)
        self.assertEqual(self.sync(FakeFetcher(), T0 + timedelta(days=2)).outcomes, [])

    def test_change_writes_frozen_record_with_impacted_controls(self):
        self.sync(FakeFetcher(), T0)
        out = self.sync(FakeFetcher(LONG + " Article 2 new duty."), T0 + timedelta(days=7)).outcomes[0]
        self.assertEqual(out.result, "changed")
        [(name, record)] = list_changes(self.reg)
        self.assertIn("+", record["detection"]["diff"])
        self.assertEqual(len(record["detection"]["impacted_controls"]), 4)
        self.assertEqual(record["review"]["status"], "open")
        self.assertIn("test", open_changes_by_framework(self.reg))

    def test_sync_never_touches_the_catalogue(self):
        before = json.dumps(self.fws, sort_keys=True)
        self.sync(FakeFetcher(), T0)
        self.sync(FakeFetcher(LONG + " changed"), T0 + timedelta(days=7))
        self.assertEqual(json.dumps(self.fws, sort_keys=True), before)

    def test_broken_after_threshold_and_baseline_kept(self):
        self.sync(FakeFetcher(), T0)
        good_hash = self.state()["hash"]
        for i in range(FAILURE_THRESHOLD):
            out = self.sync(FakeFetcher(error="status 404"), T0 + timedelta(days=7 + i)).outcomes[0]
            self.assertEqual(out.result, "broken")
        st = self.state()
        self.assertTrue(st["broken"])
        self.assertEqual(st["hash"], good_hash)

    def test_suspicious_shrink_is_broken_not_changed(self):
        self.sync(FakeFetcher(), T0)
        out = self.sync(FakeFetcher("tiny"), T0 + timedelta(days=7)).outcomes[0]
        self.assertEqual(out.result, "broken")
        self.assertIn("shrink", out.reason)
        self.assertEqual(list_changes(self.reg), [])

    def test_failure_retries_after_a_day_not_the_interval(self):
        self.sync(FakeFetcher(), T0)
        self.sync(FakeFetcher(error="down"), T0 + timedelta(days=7))
        self.assertEqual(len(self.sync(FakeFetcher(), T0 + timedelta(days=8)).outcomes), 1)

    def test_dry_run_writes_nothing(self):
        self.sync(FakeFetcher(), T0, dry_run=True)
        self.assertFalse(os.path.exists(os.path.join(self.reg, "state.json")))

    def test_review_moves_only_the_review_half(self):
        self.sync(FakeFetcher(), T0)
        self.sync(FakeFetcher(LONG + " changed"), T0 + timedelta(days=7))
        [(name, before)] = list_changes(self.reg)
        after = review_change(self.reg, name, "processed", "dpo", "controls checked")
        self.assertEqual(after["detection"], before["detection"])
        self.assertEqual(after["review"]["status"], "processed")
        self.assertEqual(open_changes_by_framework(self.reg), {})
        with self.assertRaises(ValueError):
            review_change(self.reg, name, "deleted", "x", "")


    def test_unexpected_fetcher_error_is_broken_not_a_crash(self):
        class Boom:
            def fetch(self, source):
                raise ConnectionResetError("peer closed")
        self.sync(FakeFetcher(), T0)
        out = run_sync(self.reg, self.fws, fetchers={"html": Boom()}, now=T0 + timedelta(days=7)).outcomes[0]
        self.assertEqual(out.result, "broken")
        self.assertIn("ConnectionResetError", out.reason)
        self.assertEqual(self.state()["failures"], 1)

    def test_interval_tolerates_an_early_scheduler(self):
        self.sync(FakeFetcher(), T0)
        early = T0 + timedelta(days=7) - timedelta(hours=2)
        self.assertEqual(len(self.sync(FakeFetcher(), early).outcomes), 1)

    def test_accept_shrink_records_a_change(self):
        self.sync(FakeFetcher(), T0)
        out = self.sync(FakeFetcher("Repealed. " * 10), T0 + timedelta(days=7), accept_shrink=True).outcomes[0]
        self.assertEqual(out.result, "changed")

    def test_change_record_is_never_overwritten(self):
        self.sync(FakeFetcher(), T0)
        later = T0 + timedelta(days=7)
        self.sync(FakeFetcher(LONG + " b"), later)
        self.sync(FakeFetcher(LONG), later, force=True)
        with self.assertRaises(FileExistsError):
            self.sync(FakeFetcher(LONG + " b"), later, force=True)


class FetcherParseTest(unittest.TestCase):
    def test_normalise_strips_stamps_and_sessions_but_keeps_body_dates(self):
        a = normalise("Last updated 3 November 2026. Applies from 2 August 2026 ?sid=ABCDEFGHIJKLMNOPQRSTUVWX")
        b = normalise("Last updated 4 november 2026. Applies from 2 August 2026 ?sid=ZZZZZZZZZZZZZZZZZZZZZZZZ")
        c = normalise("Last updated 4 november 2026. Applies from 2 December 2027")
        self.assertEqual(a, b)
        self.assertNotEqual(b, c)

    def test_cellar_keeps_own_consolidations_only(self):
        body = json.dumps({"results": {"bindings": [
            {"rel": {"value": "http://x#resource_legal_amends_resource_legal"}, "celex": {"value": "32026R1744"}, "date": {"value": "2026-07-08"}},
            {"rel": {"value": "http://x#act_consolidated_consolidates_resource_legal"}, "celex": {"value": "02024R1689-20260727"}},
            {"rel": {"value": "http://x#act_consolidated_consolidates_resource_legal"}, "celex": {"value": "02018R1139-20260802"}},
        ]}})
        text = CellarFetcher.parse({"celex": "32024R1689"}, body)
        self.assertIn("amended by | 32026R1744 | 2026-07-08", text)
        self.assertIn("02024R1689-20260727", text)
        self.assertNotIn("02018R1139", text)

    def test_cellar_rejects_garbage(self):
        with self.assertRaises(FetchError):
            CellarFetcher.parse({"celex": "x"}, "<html>challenge</html>")

    def test_sru_requires_the_right_identifier(self):
        xml = """<searchRetrieveResponse xmlns="http://docs.oasis-open.org/ns/search-ws/sruResponse"
          xmlns:dcterms="http://purl.org/dc/terms/"><numberOfRecords>1</numberOfRecords><records><record><recordData>
          <dcterms:identifier>BWBR0040940</dcterms:identifier><dcterms:modified>2026-09-01</dcterms:modified>
          <geldigheidsperiode_startdatum>2026-09-01</geldigheidsperiode_startdatum></recordData></record></records>
          </searchRetrieveResponse>"""
        self.assertIn("in force 2026-09-01", SruFetcher.parse({"bwb_id": "BWBR0040940"}, xml))
        with self.assertRaises(FetchError):
            SruFetcher.parse({"bwb_id": "BWBR0000001"}, xml)

    def test_iso_follows_family_and_next_edition(self):
        feed = "\n".join(json.dumps(x) for x in [
            {"id": 1, "reference": "ISO/IEC 25059:2023", "currentStage": 9092, "edition": 1, "publicationDate": "2023-06-28", "replacedBy": [2]},
            {"id": 2, "reference": "ISO/IEC FDIS 25059", "currentStage": 5000, "edition": 2, "publicationDate": None, "replacedBy": None},
            {"id": 3, "reference": "ISO/IEC 250590:2030", "currentStage": 6060, "edition": 1, "publicationDate": None, "replacedBy": None},
        ])
        text = IsoFetcher(feed).fetch({"family": "ISO/IEC 25059"})
        self.assertIn("under review 90.92", text)
        self.assertIn("ISO/IEC FDIS 25059 | approval (FDIS) 50.00", text)
        self.assertNotIn("250590", text)


if __name__ == "__main__":
    unittest.main()
