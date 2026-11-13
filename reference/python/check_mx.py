"""Checks the MX meta tags of a site and compares them with its provenance Records.

    uv run python check_mx.py https://example.org/
    uv run python check_mx.py https://project.ddev.site/ --insecure   # local dev certificates

MX (Machine Experience) is a separate vocabulary drafted for The Gathering;
see Section 5 of the specification. For every Document the Audit Endpoint
lists, this reports the MX level the page's head reaches and checks that MX
and CPS say the same thing. It is a bridge check, not part of CPS conformance.

Levels, as read from the MX drafts of 24 October 2026:
  Level 1: title, description and author (native HTML), mx:created, mx:modified
           (MX Core Metadata note §8)
  Level 2: Level 1 plus mx:canonicalUri, mx:summary, mx:conformsTo and
           mx:trainingDataPolicy (MX Carrier Formats note §3.2.2)
Missing fields only lower the level. Contradictions are findings: a canonical
link that disagrees with mx:canonicalUri, or MX tags that disagree with the
Record or the Audit Endpoint. Exits with 1 if there is a finding.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

import html5lib

import cps_canonical
from check_endpoint import AUDIT_PATH, Fetch, http_fetch
from check_facts import document_urls

LEVEL_1 = ["title", "description", "author", "mx:created", "mx:modified"]
LEVEL_2 = ["mx:canonicalUri", "mx:summary", "mx:conformsTo", "mx:trainingDataPolicy"]
# MX field -> Record field; MX dates are calendar dates, the Record carries date-times.
DATES = {"mx:created": "datePublished", "mx:modified": "dateModified", "mx:maintainedDate": "maintainedDate"}


@dataclass
class MxReport:
    url: str
    level: int
    tags: dict[str, str]
    missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def check_mx(base_url: str, fetch: Fetch) -> list[MxReport]:
    reports = []
    for document_url in document_urls(base_url.rstrip("/") + AUDIT_PATH, fetch):
        response = fetch(document_url)
        if response.status != 200:
            reports.append(MxReport(document_url, 0, {}, problems=[f"answered with status {response.status}, expected 200"]))
            continue
        reports.append(mx_report(document_url, response.body))
    return reports


def mx_report(document_url: str, html: str) -> MxReport:
    """The MX level of one Document, what is missing for the next one, and contradictions."""
    tags, canonical = _head(html)
    missing_1 = [name for name in LEVEL_1 if not tags.get(name)]
    missing_2 = [name for name in LEVEL_2 if not tags.get(name)]
    level = 0 if missing_1 else 1 if missing_2 else 2
    report = MxReport(document_url, level, tags, missing_1 or missing_2)

    canonical_uri = tags.get("mx:canonicalUri")
    if canonical_uri and canonical and canonical != canonical_uri:
        report.problems.append(f"link rel=canonical {canonical!r} and mx:canonicalUri {canonical_uri!r} disagree (MX Core Metadata §7a.1)")
    if canonical_uri and canonical_uri != document_url:
        report.problems.append(f"mx:canonicalUri {canonical_uri!r} is not the URL the Audit Endpoint lists")
    report.problems.extend(_record_disagreements(tags, cps_canonical.find_record(html)))
    return report


def _record_disagreements(tags: dict[str, str], record: dict[str, Any] | None) -> list[str]:
    if record is None:
        return []
    problems = []
    for name, record_field in DATES.items():
        stated, recorded = tags.get(name), record.get(record_field)
        if stated and isinstance(recorded, str) and stated != recorded[:10]:
            problems.append(f"{name} {stated!r} disagrees with the Record's {record_field} {recorded!r}")
    authors = record.get("author", [])
    names = ", ".join(person.get("name", "") for person in (authors if isinstance(authors, list) else [authors]) if isinstance(person, dict) and person.get("name"))
    if tags.get("author") and names and tags["author"] != names:
        problems.append(f"author {tags['author']!r} disagrees with the Record's authors {names!r}")
    return problems


def _head(html: str) -> tuple[dict[str, str], str | None]:
    """Meta tags by name (plus the title) and the canonical link of a page."""
    document = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=False)
    tags: dict[str, str] = {}
    canonical = None
    for element in document.iter():
        if not isinstance(element.tag, str):
            continue
        if element.tag == "title" and element.text:
            tags.setdefault("title", element.text.strip())
        elif element.tag == "meta" and element.get("name"):
            tags.setdefault(element.get("name"), (element.get("content") or "").strip())
        elif element.tag == "link" and "canonical" in (element.get("rel") or "").split():
            canonical = canonical or element.get("href")
    return tags, canonical


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="base URL of the site")
    parser.add_argument("--insecure", action="store_true", help="skip TLS certificate checks (local development only)")
    arguments = parser.parse_args()

    reports = check_mx(arguments.site, http_fetch(arguments.insecure, user_agent="cps-check-mx/0.4"))
    for report in reports:
        missing = f"  (next level needs: {', '.join(report.missing)})" if report.missing else ""
        print(f"MX L{report.level}  {report.url}{missing}")
        for problem in report.problems:
            print(f"    finding: {problem}")
    findings = sum(len(report.problems) for report in reports)
    levels = ", ".join(f"{sum(1 for r in reports if r.level == level)} at L{level}" for level in (2, 1, 0))
    print(f"\n{len(reports)} documents: {levels}; {findings} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
