from __future__ import annotations

import json

from check_endpoint import Response
from check_mx import check_mx, mx_report

DOCUMENT = "https://example.org/report"
RECORD = {
    "@context": ["https://schema.org", "https://cms-provenance.org/ns/v1"],
    "@type": "WebPage",
    "author": [{"@type": "Person", "@id": "https://orcid.org/0000-0001-2345-6789", "name": "Ada Lovelace"}],
    "datePublished": "2026-05-14T09:00:00Z",
    "dateModified": "2026-11-13T10:30:00Z",
    "maintainedDate": "2026-11-01T12:00:00Z",
}
LEVEL_2_TAGS = {
    "description": "The search engine description.",
    "author": "Ada Lovelace",
    "mx:canonicalUri": DOCUMENT,
    "mx:summary": "What the report says.",
    "mx:conformsTo": "https://github.com/dkd-dobberkau/content-provenance-spec/blob/draft-0.4/specification.md",
    "mx:trainingDataPolicy": "Permitted with attribution.",
    "mx:created": "2026-05-14",
    "mx:modified": "2026-11-13",
    "mx:maintainedDate": "2026-11-01",
}


def page(tags: dict[str, str], canonical: str | None = DOCUMENT, record: dict | None = RECORD) -> str:
    head = ["<title>Report</title>"]
    if canonical is not None:
        head.append(f'<link rel="canonical" href="{canonical}">')
    head += [f'<meta name="{name}" content="{content}">' for name, content in tags.items()]
    if record is not None:
        head.append(f'<script type="application/ld+json">{json.dumps(record)}</script>')
    return f"<!DOCTYPE html><html><head>{''.join(head)}</head><body><p>Text</p></body></html>"


def test_all_four_level_2_tags_reach_level_2() -> None:
    report = mx_report(DOCUMENT, page(LEVEL_2_TAGS))

    assert report.level == 2
    assert report.missing == []
    assert report.problems == []


def test_a_missing_level_2_tag_leaves_level_1() -> None:
    tags = {name: value for name, value in LEVEL_2_TAGS.items() if name != "mx:trainingDataPolicy"}

    report = mx_report(DOCUMENT, page(tags))

    assert report.level == 1
    assert report.missing == ["mx:trainingDataPolicy"]


def test_without_level_1_fields_the_page_has_no_level() -> None:
    tags = {name: value for name, value in LEVEL_2_TAGS.items() if name != "description"}

    report = mx_report(DOCUMENT, page(tags))

    assert report.level == 0
    assert "description" in report.missing


def test_canonical_link_and_canonical_uri_must_agree() -> None:
    report = mx_report(DOCUMENT, page(LEVEL_2_TAGS, canonical="https://example.org/other"))

    assert any("rel=canonical" in problem for problem in report.problems)


def test_mx_tags_must_agree_with_the_provenance_record() -> None:
    tags = {**LEVEL_2_TAGS, "mx:created": "2026-05-15", "mx:maintainedDate": "2026-10-01", "author": "Grace Hopper"}

    problems = mx_report(DOCUMENT, page(tags)).problems

    assert any("mx:created" in problem for problem in problems)
    assert any("mx:maintainedDate" in problem for problem in problems)
    assert any("author" in problem for problem in problems)


def test_canonical_uri_must_name_the_listed_document() -> None:
    report = mx_report(DOCUMENT, page({**LEVEL_2_TAGS, "mx:canonicalUri": "https://example.org/other"}, canonical=None))

    assert any("Audit Endpoint" in problem for problem in report.problems)


def test_entities_in_content_are_decoded() -> None:
    report = mx_report(DOCUMENT, page({**LEVEL_2_TAGS, "mx:summary": "Fish &amp; chips"}))

    assert report.tags["mx:summary"] == "Fish & chips"


def test_site_check_walks_the_audit_endpoint() -> None:
    listing = {"documents": [{"url": DOCUMENT, "@id": "urn:uuid:x"}]}
    responses = {
        "https://example.org/.well-known/content-provenance": Response(200, {"content-type": "application/json"}, json.dumps(listing)),
        DOCUMENT: Response(200, {"content-type": "text/html"}, page(LEVEL_2_TAGS)),
    }

    reports = check_mx("https://example.org", lambda url: responses.get(url, Response(404, {}, "")))

    assert [(report.url, report.level) for report in reports] == [(DOCUMENT, 2)]
