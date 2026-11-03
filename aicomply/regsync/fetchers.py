"""How each kind of source is read and made comparable.

Four strategies, picked per source in registry/sources.json:

- `cellar`: EU legislation through the Publications Office SPARQL endpoint.
  Asks which acts amend, correct, consolidate or propose to amend a CELEX
  number. Structured, so a EUR-Lex redesign cannot break it.
- `sru`: Dutch acts in the Basiswettenbestand through the KOOP SRU service.
- `iso`: ISO's own open-data feed of deliverables. Shows a new edition, an
  amendment, a draft of the next edition or a withdrawal the day ISO lists it.
- `html`: everything else (regulator guidance pages). Text is reduced and
  normalised, and must contain an anchor, or the check counts as broken.

Every fetcher returns normalised text or raises FetchError. "Broken" is a
third outcome next to unchanged and changed: a dead scraper must never look
like a quiet source.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from xml.etree import ElementTree

from aicomply import __version__

USER_AGENT = f"AIComply-RegulationSync/{__version__} (+https://github.com/robinbril/aicomply)"
TIMEOUT = 60
MIN_TEXT = 80
BACKOFF = (2, 6)

CELLAR_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
SRU_ENDPOINT = "https://zoekservice.overheid.nl/sru/Search"
ISO_OPEN_DATA = (
    "https://isopublicstorageprod.blob.core.windows.net/opendata/_latest/"
    "iso_deliverables_metadata/json/iso_deliverables_metadata.jsonl"
)


class FetchError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def http_get(url: str, accept: str = "*/*") -> tuple[str, str]:
    """GET with a short bounded backoff on 429/5xx. Returns (final_url, body)."""
    last = None
    for wait in (0, *BACKOFF):
        if wait:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310: fixed https endpoints
                body = resp.read().decode("utf-8", "replace")
                if resp.status != 200:
                    raise FetchError(f"status {resp.status}")
                return resp.geturl(), body
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                last = FetchError(f"status {exc.code}")
                continue
            raise FetchError(f"status {exc.code}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:  # socket.timeout is OSError on 3.9
            last = FetchError(f"network error: {exc}")
    raise last


# --- normalisation ---------------------------------------------------------

_DATES = [
    re.compile(r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b"),
    re.compile(
        r"\b\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|"
        r"november|december|januari|februari|maart|mei|juni|juli|augustus|oktober)\s+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?\b"),
]
_SESSION = re.compile(r"(?<==)[A-Za-z0-9_-]{20,}\b")


_STAMP = re.compile(
    r"(last\s+(updated|modified|reviewed|changed)|published\s+on|updated\s+on|laatst\s+(bijgewerkt|gewijzigd)|"
    r"page\s+last\s+updated|date\s+modified)[^.\n]{0,40}",
    re.IGNORECASE,
)


def normalise(text: str) -> str:
    """Strip page-stamp dates, session tokens and whitespace so the hash only moves on content.

    Only a date next to a "last updated" style marker is removed: those change
    on every edit of the page chrome. A date in the body (an application date
    of an obligation moving by a year) is content and must move the hash.
    """
    text = _STAMP.sub(lambda m: _strip_dates(m.group(0)), text)
    text = _SESSION.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _strip_dates(fragment: str) -> str:
    for pattern in _DATES:
        fragment = pattern.sub("", fragment)
    return fragment


class _TextExtractor(HTMLParser):
    _SKIP = frozenset({"script", "style", "nav", "header", "footer", "noscript", "svg", "form"})

    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return "\n".join(extractor.parts)


# --- fetchers --------------------------------------------------------------


class HtmlFetcher:
    def fetch(self, source: dict) -> str:
        final_url, body = http_get(source["url"], "text/html")
        start, end = urllib.parse.urlsplit(source["url"]).hostname, urllib.parse.urlsplit(final_url).hostname
        if start != end:
            raise FetchError(f"redirected to another host ({start} -> {end}); the page probably moved")
        text = normalise(html_to_text(body))
        if len(text) < MIN_TEXT:
            raise FetchError(f"extraction suspiciously short ({len(text)} chars)")
        anchor = source.get("anchor")
        if anchor and anchor not in text:
            raise FetchError(f"anchor '{anchor}' not found; the page layout probably changed")
        return text


_CELLAR_QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?rel ?celex ?date WHERE {{
  ?act cdm:resource_legal_id_celex "{celex}"^^<http://www.w3.org/2001/XMLSchema#string> .
  ?x ?rel ?act .
  ?x cdm:resource_legal_id_celex ?celex .
  OPTIONAL {{ ?x cdm:work_date_document ?date }}
  VALUES ?rel {{
    cdm:resource_legal_amends_resource_legal
    cdm:resource_legal_corrects_resource_legal
    cdm:resource_legal_proposes_to_amend_resource_legal
    cdm:act_consolidated_consolidates_resource_legal
    cdm:resource_legal_repeals_resource_legal
    cdm:communication_case_new_submits_preliminary_question_resource_legal
  }}
}}
"""
_CELLAR_LABELS = {
    "resource_legal_amends_resource_legal": "amended by",
    "resource_legal_corrects_resource_legal": "corrected by",
    "resource_legal_proposes_to_amend_resource_legal": "amendment proposed in",
    "act_consolidated_consolidates_resource_legal": "consolidated version",
    "resource_legal_repeals_resource_legal": "repealed by",
    "communication_case_new_submits_preliminary_question_resource_legal": "CJEU preliminary question",
}


class CellarFetcher:
    """EU acts via the Publications Office (CELLAR) SPARQL endpoint."""

    def fetch(self, source: dict) -> str:
        query = _CELLAR_QUERY.format(celex=source["celex"])
        url = CELLAR_ENDPOINT + "?" + urllib.parse.urlencode({"query": query})
        _, body = http_get(url, "application/sparql-results+json")
        return self.parse(source, body)

    @staticmethod
    def parse(source: dict, body: str) -> str:
        try:
            rows = json.loads(body)["results"]["bindings"]
        except (ValueError, KeyError) as exc:
            raise FetchError(f"CELLAR answer is not SPARQL JSON: {exc}") from exc
        own = source["celex"]
        lines = set()
        for row in rows:
            try:
                rel = row["rel"]["value"].rsplit("#", 1)[-1]
                celex = row["celex"]["value"]
            except (KeyError, TypeError) as exc:
                raise FetchError(f"CELLAR row without rel/celex: {row}") from exc
            # A consolidation of ANOTHER act also "consolidates" this one when this
            # act amended it; only consolidations of this act itself matter here.
            if rel == "act_consolidated_consolidates_resource_legal" and celex[1:].split("-")[0] != own[1:]:
                continue
            date = row.get("date", {}).get("value", "")[:10]
            lines.add(f"{_CELLAR_LABELS.get(rel, rel)} | {celex} | {date}")
        if not lines and source.get("expect_history", True):
            raise FetchError(f"CELLAR returned no history for {own}; the CELEX number may be wrong")
        return f"{own}\n" + "\n".join(sorted(lines))


class SruFetcher:
    """Dutch acts (BWB) via the KOOP SRU service: one line per consolidated state."""

    NS = {"sru": "http://docs.oasis-open.org/ns/search-ws/sruResponse"}

    def fetch(self, source: dict) -> str:
        params = {
            "version": "2.0",
            "operation": "searchRetrieve",
            "x-connection": "BWB",
            "query": f'dcterms.identifier="{source["bwb_id"]}"',
            "maximumRecords": "200",
        }
        _, body = http_get(SRU_ENDPOINT + "?" + urllib.parse.urlencode(params), "application/xml")
        return self.parse(source, body)

    @classmethod
    def parse(cls, source: dict, body: str) -> str:
        try:
            root = ElementTree.fromstring(body)  # nosec B314: government SRU over https
        except ElementTree.ParseError as exc:
            raise FetchError(f"SRU answer is not XML: {exc}") from exc
        count = root.findtext("sru:numberOfRecords", namespaces=cls.NS)
        if count is None or not count.strip().isdigit():
            raise FetchError("SRU answer has no numberOfRecords")
        ids = {el.text for el in root.iter("{http://purl.org/dc/terms/}identifier") if el.text}
        if source["bwb_id"] not in ids:
            raise FetchError(f"SRU answer does not contain {source['bwb_id']}")
        states = set()
        for rec in root.iter("{http://docs.oasis-open.org/ns/search-ws/sruResponse}recordData"):
            start = _first(rec, "geldigheidsperiode_startdatum")
            end = _first(rec, "geldigheidsperiode_einddatum")
            changed = _first(rec, "modified")
            states.add(f"in force {start or '?'} to {end or 'open'} | modified {changed or '?'}")
        return f"{source['bwb_id']}\n" + "\n".join(sorted(states))


def _first(element, local_name: str) -> str:
    for el in element.iter():
        if el.tag.rsplit("}", 1)[-1] == local_name and el.text:
            return el.text.strip()
    return ""


# ISO harmonized stage codes worth naming in a diff.
ISO_STAGES = {
    "00": "preliminary", "10": "proposal", "20": "working draft", "30": "committee draft",
    "40": "enquiry (DIS)", "50": "approval (FDIS)", "60": "published", "90": "under review",
    "95": "withdrawn",
}


class IsoFetcher:
    """ISO deliverables via ISO's open-data feed (one download serves every ISO source)."""

    def __init__(self, feed_text: str | None = None):
        self._feed = feed_text
        self._by_id: dict | None = None

    def _index(self) -> dict:
        if self._by_id is None:
            if self._feed is None:
                _, self._feed = http_get(ISO_OPEN_DATA, "application/x-ndjson")
            self._by_id = {}
            for line in self._feed.splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    self._by_id[item["id"]] = item
                except (ValueError, KeyError, TypeError) as exc:
                    raise FetchError(f"ISO feed is not the expected JSON lines: {exc}") from exc
            if not self._by_id:
                raise FetchError("ISO feed is empty")
        return self._by_id

    def fetch(self, source: dict) -> str:
        index = self._index()
        family = source["family"]
        pattern = re.compile(r"^" + re.escape(family).replace(r"\ ", r"(?:/[A-Z]+)?\s(?:[A-Z]+\s)?") + r"(?:[:/.]|$)")
        hits = {i: d for i, d in index.items() if pattern.match(d.get("reference") or "")}
        # A next edition in development is listed under its own id; follow replacedBy.
        for d in list(hits.values()):
            for nxt in d.get("replacedBy") or []:
                if nxt in index:
                    hits[nxt] = index[nxt]
        if not hits:
            raise FetchError(f"no ISO deliverable matches '{family}'")
        lines = []
        for d in hits.values():
            stage = str(d.get("currentStage") or "")
            label = ISO_STAGES.get(stage[:2], "stage")
            lines.append(
                f"{d['reference']} | {label} {stage[:2]}.{stage[2:]} | edition {d.get('edition')} | "
                f"published {d.get('publicationDate') or '-'}"
            )
        return f"{family}\n" + "\n".join(sorted(lines))


def default_fetchers() -> dict:
    return {"html": HtmlFetcher(), "cellar": CellarFetcher(), "sru": SruFetcher(), "iso": IsoFetcher()}
