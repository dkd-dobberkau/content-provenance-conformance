from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

from check_endpoint import Response
from check_wikidata import check_claim

WIKI = "https://en.wikipedia.org/wiki/"


def time(value: str, precision: int) -> dict:
    return {"mainsnak": {"datavalue": {"type": "time", "value": {"time": value, "precision": precision}}}, "rank": "normal"}


def item(qid: str) -> dict:
    return {"mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": qid}}}, "rank": "normal"}


ENTITIES = {
    "Louvre": {"id": "Q19675", "claims": {"P571": [time("+1793-08-10T00:00:00Z", 11)], "P131": [item("Q90")]}},
    "Ashmolean Museum": {"id": "Q636400", "claims": {"P571": [time("+1683-00-00T00:00:00Z", 9)]}},
    "Paris": {"id": "Q90", "claims": {}},
    "Lyon": {"id": "Q456", "claims": {}},
}


def fetch(url: str) -> Response:
    query = parse_qs(urlsplit(url).query)
    titles = query.get("titles", [""])[0]
    ids = query.get("ids", [""])[0]
    found = ENTITIES.get(titles) or next((e for e in ENTITIES.values() if e["id"] == ids), None)
    body = {"entities": {found["id"]: found}} if found else {"entities": {"-1": {"missing": ""}}}
    return Response(200, {"content-type": "application/json"}, json.dumps(body))


def claim(subject: str, predicate: str, obj) -> dict:
    return {"@id": "https://example.org/a#fact-x", "subject": subject, "predicate": predicate, "object": obj, "text": "x"}


def test_date_matching_at_the_precision_wikidata_gives_is_confirmed() -> None:
    assert check_claim(claim(WIKI + "Louvre", "https://schema.org/foundingDate", "1793-08-10"), fetch).status == "confirmed"
    assert check_claim(claim(WIKI + "Ashmolean_Museum", "https://schema.org/foundingDate", "1683"), fetch).status == "confirmed"


def test_year_only_statement_confirms_a_full_date_in_that_year() -> None:
    assert check_claim(claim(WIKI + "Ashmolean_Museum", "https://schema.org/foundingDate", "1683-05-24"), fetch).status == "confirmed"


def test_other_date_is_contradicted_with_the_wikidata_value() -> None:
    result = check_claim(claim(WIKI + "Louvre", "https://schema.org/foundingDate", "1792"), fetch)

    assert result.status == "contradicted"
    assert "1793-08-10" in result.detail and "Q19675" in result.detail


def test_item_object_is_compared_by_its_wikidata_id() -> None:
    assert check_claim(claim(WIKI + "Louvre", "https://schema.org/containedInPlace", {"@id": WIKI + "Paris"}), fetch).status == "confirmed"
    assert check_claim(claim(WIKI + "Louvre", "https://schema.org/containedInPlace", {"@id": WIKI + "Lyon"}), fetch).status == "contradicted"


def test_wikidata_uris_and_property_uris_are_understood() -> None:
    result = check_claim(claim("http://www.wikidata.org/entity/Q19675", "http://www.wikidata.org/prop/direct/P571", "1793"), fetch)

    assert result.status == "confirmed"


def test_unknown_subject_unmapped_predicate_or_missing_statement_is_unknown() -> None:
    assert check_claim(claim(WIKI + "Nowhere", "https://schema.org/foundingDate", "1700"), fetch).status == "unknown"
    assert check_claim(claim(WIKI + "Louvre", "https://schema.org/description", "A museum"), fetch).status == "unknown"
    assert check_claim(claim(WIKI + "Paris", "https://schema.org/foundingDate", "1700"), fetch).status == "unknown"


def test_bce_year_is_compared_as_a_negative_year() -> None:
    ENTITIES["Old museum"] = {"id": "Q1", "claims": {"P571": [time("-0530-00-00T00:00:00Z", 9)]}}

    assert check_claim(claim(WIKI + "Old_museum", "https://schema.org/foundingDate", "c. 530 BCE"), fetch).status == "confirmed"
