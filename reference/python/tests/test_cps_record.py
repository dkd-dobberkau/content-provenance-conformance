from __future__ import annotations

import copy

import pytest

import cps_record

COMPLETE = {
    "@context": ["https://schema.org", "https://cms-provenance.org/ns/v1"],
    "@type": "WebPage",
    "@id": "urn:uuid:00000000-0000-4000-8000-000000000001",
    "author": [{"@type": "Person", "@id": "https://example.org/people/ada", "name": "Ada"}],
    "datePublished": "2026-11-13T10:00:00Z",
    "lastSubstantiveRevision": "2026-11-13T11:00:00Z",
    "citation": [{"@type": "WebPage", "url": "https://example.org/source", "name": "Source", "accessDate": "2026-11-13"}],
    "generator": "Example CMS 1.0",
}


def without(member: str) -> dict:
    record = copy.deepcopy(COMPLETE)
    del record[member]
    return record


def changed(**members) -> dict:
    return {**copy.deepcopy(COMPLETE), **members}


def test_complete_record_has_no_problems() -> None:
    assert cps_record.problems(COMPLETE) == []


def test_sources_may_be_omitted() -> None:
    assert cps_record.problems(without("citation")) == []


@pytest.mark.parametrize("member", ["@context", "@type", "@id", "author", "datePublished", "lastSubstantiveRevision", "generator"])
def test_missing_required_member_is_a_problem(member: str) -> None:
    assert any(member in problem for problem in cps_record.problems(without(member)))


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (changed(**{"@context": "https://schema.org"}), "vocabulary"),
        (changed(author=[]), "author"),
        (changed(author=[{"@type": "Person", "name": "Ada"}]), "author 1 has no @id"),
        (changed(author=[COMPLETE["author"][0], {"@type": "Person", "name": "Bob"}]), "author 2 has no @id"),
        (changed(author=[{"@type": "Person", "@id": "ada"}]), "not a URI"),
        (changed(citation=[{"url": "https://example.org/s", "name": "S"}]), "source 1 has no accessDate"),
        (changed(citation=[{"url": "https://example.org/s", "accessDate": "2026-11-13"}]), "source 1 has no name"),
        (changed(datePublished="13 November 2026"), "datePublished"),
        (changed(citation=[{"url": "https://example.org/s", "name": "S", "accessDate": "2026-11-13T10:00:00Z"}]), "accessDate"),
    ],
)
def test_incomplete_record_is_reported(record: dict, expected: str) -> None:
    assert any(expected in problem for problem in cps_record.problems(record)), cps_record.problems(record)
