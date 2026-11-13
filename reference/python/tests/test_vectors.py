from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import jcs
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import cps_canonical
import vectors

VECTOR_DIRS = vectors.vector_dirs()
IDS = [path.name for path in VECTOR_DIRS]


def read(vector: Path, name: str) -> str:
    return (vector / name).read_text(encoding="utf-8")


def public_key() -> Ed25519PublicKey:
    _, _, public_hex = vectors.test_key()
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))


def test_test_key_matches_rfc8032() -> None:
    private_key, _, public_hex = vectors.test_key()
    assert private_key.public_key().public_bytes_raw().hex() == public_hex


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_canonical_text_matches_hand_written_expectation(vector: Path) -> None:
    assert cps_canonical.canonical_text(read(vector, "input.html")) == read(vector, "expected-text.txt")


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_content_hash_is_sha256_of_the_expected_text(vector: Path) -> None:
    expected = "sha256:" + hashlib.sha256(read(vector, "expected-text.txt").encode("utf-8")).hexdigest()
    assert cps_canonical.content_hash(read(vector, "input.html")) == expected


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_record_canonicalisation_agrees_with_independent_jcs(vector: Path) -> None:
    record = json.loads(read(vector, "record.json"))
    unsigned = {key: value for key, value in record.items() if key != "signature"}
    assert cps_canonical.canonical_record(record) == jcs.canonicalize(unsigned)


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_stored_results_are_reproducible(vector: Path) -> None:
    assert json.loads(read(vector, "expected.json")) == vectors.expected_result(vector)


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_signed_record_verifies_against_the_page(vector: Path) -> None:
    signed = json.loads(read(vector, "expected.json"))["signedRecord"]
    assert cps_canonical.verify(read(vector, "input.html"), signed, public_key())


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_changed_page_text_fails_verification(vector: Path) -> None:
    signed = json.loads(read(vector, "expected.json"))["signedRecord"]
    assert not cps_canonical.verify(inject_into_content(read(vector, "input.html")), signed, public_key())


@pytest.mark.parametrize("vector", VECTOR_DIRS, ids=IDS)
def test_changed_record_fails_verification(vector: Path) -> None:
    signed = copy.deepcopy(json.loads(read(vector, "expected.json"))["signedRecord"])
    signed["cpsConformance"] = 4
    assert not cps_canonical.verify(read(vector, "input.html"), signed, public_key())


def inject_into_content(html: str) -> str:
    """Adds a paragraph right inside the first content root (A.2.1)."""
    for opening in ("data-cps-content>", "<main>", "<body>"):
        if opening in html:
            return html.replace(opening, opening + "<p>Injected claim</p>", 1)
    raise AssertionError("vector has no content root")


def test_text_outside_marked_regions_is_not_covered() -> None:
    page = '<body><header>Header</header><article data-cps-content><p>Signed</p></article></body>'
    changed = page.replace("Header", "Changed header")
    assert cps_canonical.content_hash(page) == cps_canonical.content_hash(changed)


def test_invisible_bytes_do_not_change_the_hash() -> None:
    clean = "<main><p>Signed text</p></main>"
    polluted = "<main><p>Sig​ned­ te⁠xt﻿</p></main>"
    assert cps_canonical.content_hash(clean) == cps_canonical.content_hash(polluted)


def test_non_integer_numbers_are_rejected() -> None:
    with pytest.raises(ValueError):
        cps_canonical.canonical_record({"cpsConformance": 2.5})


def test_record_is_found_by_its_context() -> None:
    html = (
        '<html><head>'
        '<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Organization"}</script>'
        '<script type="application/ld+json">{"@context": ["https://schema.org", "https://cms-provenance.org/ns/v1"], "@id": "urn:x"}</script>'
        '</head><body></body></html>'
    )
    assert cps_canonical.find_record(html) == {
        "@context": ["https://schema.org", "https://cms-provenance.org/ns/v1"],
        "@id": "urn:x",
    }
