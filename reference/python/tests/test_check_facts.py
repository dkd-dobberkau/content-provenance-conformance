from __future__ import annotations

import json

import cps_canonical
import cps_facts
import vectors
from check_endpoint import Response
from check_facts import check_facts

SITE = "https://example.org"
VECTOR = vectors.VECTORS / "facts" / "01-literal-object"
PAGE = (VECTOR / "input.html").read_text(encoding="utf-8")
DOCUMENT = json.loads((VECTOR / "expected.json").read_text())["documentUrl"]
CLAIM = cps_canonical.find_record(PAGE)["claim"][0]
HEADERS = {"content-type": "application/json", "access-control-allow-origin": "*"}
ANNOTATION_HEADERS = {"content-type": 'application/ld+json; profile="http://www.w3.org/ns/anno.jsonld"', "access-control-allow-origin": "*"}


def site(annotation: dict | None) -> dict[str, Response]:
    listing = {"documents": [{"url": DOCUMENT, "@id": "urn:uuid:x"}]}
    responses = {
        f"{SITE}/.well-known/content-provenance": Response(200, HEADERS, json.dumps(listing)),
        DOCUMENT: Response(200, {"content-type": "text/html"}, PAGE),
    }
    if annotation is not None:
        responses[annotation["id"]] = Response(200, ANNOTATION_HEADERS, json.dumps(annotation))
    return responses


def served_annotation() -> dict:
    """The annotation an implementation serves, with a member Section 3.3 does not define."""
    return {**cps_facts.annotation(CLAIM, DOCUMENT), "created": "2026-11-13T10:00:00Z"}


def run(responses: dict[str, Response]) -> list[str]:
    def fetch(url: str) -> Response:
        return responses.get(url, Response(404, HEADERS, "{}"))

    findings, checked = check_facts(SITE, fetch)
    assert checked == 1
    return [str(finding) for finding in findings]


def test_conforming_fact_with_extra_annotation_members_has_no_findings() -> None:
    assert run(site(served_annotation())) == []


def test_missing_annotation_is_reported() -> None:
    found = run(site(None))

    assert len(found) == 1 and "404" in found[0], found


def test_annotation_quoting_other_words_is_reported() -> None:
    annotation = served_annotation()
    annotation["target"]["selector"][1]["exact"] = "12.4 million"

    found = run(site(annotation))

    assert any("target/selector" in message and "TextQuoteSelector" in message for message in found), found


def test_annotation_with_relative_source_is_reported() -> None:
    annotation = served_annotation()
    annotation["target"]["source"] = "/report"

    assert any("target/source" in message for message in run(site(annotation)))
