from __future__ import annotations

import json
from pathlib import Path

import pytest

import cps_canonical
import cps_facts
import vectors

VECTOR_DIRS = sorted(path for path in (vectors.VECTORS / "facts").iterdir() if path.is_dir())
IDS = [path.name for path in VECTOR_DIRS]


def read(vector: Path, name: str) -> str:
    return (vector / name).read_text(encoding="utf-8")


def expected(vector: Path) -> dict:
    return json.loads(read(vector, "expected.json"))


def claims(vector: Path) -> list[dict]:
    return cps_canonical.find_record(read(vector, "input.html"))["claim"]


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_anchoring_facts_does_not_change_the_canonical_text(vector: Path) -> None:
    assert cps_canonical.canonical_text(read(vector, "input.html")) == cps_canonical.canonical_text(read(vector, "plain.html"))


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_anchors_match_the_hand_written_expectation(vector: Path) -> None:
    assert cps_facts.anchors(read(vector, "input.html")) == expected(vector)["anchors"]


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_every_claim_is_consistent_with_its_document(vector: Path) -> None:
    html = read(vector, "input.html")
    for claim in claims(vector):
        assert cps_facts.claim_problems(claim, html, expected(vector)["documentUrl"]) == []


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_annotation_matches_the_hand_written_expectation(vector: Path) -> None:
    document_url = expected(vector)["documentUrl"]
    for claim in claims(vector):
        fact_id = cps_facts.fact_id(claim, document_url)
        assert cps_facts.annotation(claim, document_url) == expected(vector)["annotations"][fact_id]


def test_quote_missing_from_the_document_is_a_problem() -> None:
    vector = vectors.VECTORS / "facts" / "01-literal-object"
    claim = dict(claims(vector)[0], text="13.0 million EUR")

    problems = cps_facts.claim_problems(claim, read(vector, "input.html"), expected(vector)["documentUrl"])

    assert any("not found in the canonical text" in problem for problem in problems)


def test_anchor_with_other_words_is_a_problem() -> None:
    vector = vectors.VECTORS / "facts" / "01-literal-object"
    html = read(vector, "input.html").replace(
        '<span id="fact-revenue-2025">12.4 million EUR</span> in 2025',
        '12.4 million EUR <span id="fact-revenue-2025">in 2025</span>',
    )

    problems = cps_facts.claim_problems(claims(vector)[0], html, expected(vector)["documentUrl"])

    assert any("element fact-revenue-2025" in problem for problem in problems)


def test_fact_uri_of_another_document_is_a_problem() -> None:
    vector = vectors.VECTORS / "facts" / "01-literal-object"

    problems = cps_facts.claim_problems(claims(vector)[0], read(vector, "input.html"), "https://example.org/other")

    assert any("@id" in problem for problem in problems)
