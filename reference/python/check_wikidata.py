"""Compares the Facts of a site with the statements in Wikidata.

    uv run python check_wikidata.py https://example.org/
    uv run python check_wikidata.py https://project.ddev.site/ --insecure   # local dev certificates

For every Fact listed by the Audit Endpoint, resolves the subject (a Wikidata
entity URI or a Wikipedia article URL) to a Wikidata item, maps the predicate
to Wikidata properties and compares the object: dates at the precision
Wikidata gives, items by their Q-ID. Reports each Fact as confirmed,
contradicted or unknown. This is an editorial aid, not part of conformance:
Wikidata is a source, not an arbiter. Exits with 1 if a Fact is contradicted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlencode

import cps_canonical
import cps_facts
from check_endpoint import AUDIT_PATH, Fetch, http_fetch
from check_facts import document_urls

API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "cps-check-wikidata/0.4 (https://github.com/dkd-dobberkau/content-provenance-conformance)"
# schema.org terms with a Wikidata counterpart; any property URI is used as it is.
PROPERTIES = {
    "https://schema.org/foundingDate": ["P571"],
    "https://schema.org/datePublished": ["P577"],
    "https://schema.org/birthDate": ["P569"],
    "https://schema.org/deathDate": ["P570"],
    "https://schema.org/parent": ["P22", "P25"],
    "https://schema.org/containedInPlace": ["P131", "P276"],
    "https://schema.org/location": ["P276", "P131"],
    "https://schema.org/founder": ["P112"],
    "https://schema.org/author": ["P50"],
}
WIKIDATA_ENTITY = re.compile(r"^https?://www\.wikidata\.org/(?:entity|wiki)/(Q\d+)$")
WIKIDATA_PROPERTY = re.compile(r"^https?://www\.wikidata\.org/(?:prop/direct|entity|wiki/Property:?)/?(P\d+)$")
WIKIPEDIA_ARTICLE = re.compile(r"^https?://([a-z-]+)\.wikipedia\.org/wiki/([^#?]+)$")
YEAR, MONTH, DAY = 9, 10, 11


@dataclass(frozen=True)
class Result:
    fact: str
    status: str  # "confirmed", "contradicted", "unknown"
    detail: str = ""


def check_claim(claim: dict[str, Any], fetch: Fetch, cache: dict[str, dict | None] | None = None) -> Result:
    cache = {} if cache is None else cache
    fact = str(claim.get("@id", "?"))
    subject = _entity(str(claim.get("subject", "")), fetch, cache)
    if subject is None:
        return Result(fact, "unknown", "subject has no Wikidata item")
    properties = _properties(cps_facts.predicate_uri(str(claim.get("predicate", ""))))
    if not properties:
        return Result(fact, "unknown", f"no Wikidata property for {claim.get('predicate')}")
    statements = [s for p in properties for s in subject.get("claims", {}).get(p, []) if s.get("rank") != "deprecated"]
    values = [s.get("mainsnak", {}).get("datavalue") for s in statements]
    values = [v for v in values if isinstance(v, dict)]
    if not values:
        return Result(fact, "unknown", f"{subject['id']} has no statement for {'/'.join(properties)}")

    obj = claim.get("object")
    if isinstance(obj, dict):
        target = _entity(str(obj.get("@id", "")), fetch, cache)
        if target is None:
            return Result(fact, "unknown", "object has no Wikidata item")
        ids = [v["value"].get("id") for v in values if v.get("type") == "wikibase-entityid"]
        expected = f"{target['id']} for {subject['id']}/{'/'.join(properties)}"
        return Result(fact, "confirmed", expected) if target["id"] in ids else Result(fact, "contradicted", f"Wikidata has {', '.join(ids)}, not {expected}")

    stated = _parse_date(str(obj))
    times = [v["value"] for v in values if v.get("type") == "time"]
    if stated is None or not times:
        return Result(fact, "unknown", "object is not a date Wikidata states")
    if any(_same_date(stated, _parse_wikidata_time(t)) for t in times):
        return Result(fact, "confirmed", f"{subject['id']}/{'/'.join(properties)}")
    found = ", ".join(_format(_parse_wikidata_time(t)) for t in times)
    return Result(fact, "contradicted", f"Wikidata has {found} for {subject['id']}/{'/'.join(properties)}, not {obj}")


def _entity(uri: str, fetch: Fetch, cache: dict[str, dict | None]) -> dict | None:
    """The Wikidata item a Wikidata entity URI or a Wikipedia article URL names."""
    if uri in cache:
        return cache[uri]
    entity = WIKIDATA_ENTITY.match(uri)
    article = WIKIPEDIA_ARTICLE.match(uri)
    if entity:
        params = {"action": "wbgetentities", "format": "json", "props": "claims", "ids": entity.group(1)}
    elif article:
        title = unquote(article.group(2)).replace("_", " ")
        params = {"action": "wbgetentities", "format": "json", "props": "claims", "sites": f"{article.group(1)}wiki", "titles": title, "redirects": "yes"}
    else:
        cache[uri] = None
        return None
    response = fetch(f"{API}?{urlencode(params)}")
    found = None
    if response.status == 200:
        entities = json.loads(response.body).get("entities", {})
        found = next((e for e in entities.values() if "missing" not in e and "id" in e), None)
    cache[uri] = found
    return found


def _properties(predicate: str) -> list[str]:
    match = WIKIDATA_PROPERTY.match(predicate)
    return [match.group(1)] if match else PROPERTIES.get(predicate, [])


def _parse_date(text: str) -> tuple[int, int, int, int] | None:
    """(year, month, day, precision) of "1683", "1793-08", "1793-08-10" or "c. 530 BCE"."""
    bce = re.fullmatch(r"(?:c\.\s*)?(\d{1,4})\s*BCE", text.strip())
    if bce:
        return -int(bce.group(1)), 0, 0, YEAR
    match = re.fullmatch(r"(-?\d{1,4})(?:-(\d{2})(?:-(\d{2}))?)?", text.strip())
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2) or 0), int(match.group(3) or 0)
    return year, month, day, DAY if day else MONTH if month else YEAR


def _parse_wikidata_time(value: dict) -> tuple[int, int, int, int]:
    match = re.match(r"([+-])(\d+)-(\d{2})-(\d{2})", value["time"])
    year = int(match.group(2)) * (-1 if match.group(1) == "-" else 1)
    return year, int(match.group(3)), int(match.group(4)), int(value.get("precision", YEAR))


def _same_date(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Equal at the coarser of the two precisions; Wikidata below year precision never matches."""
    precision = min(a[3], b[3])
    if precision < YEAR:
        return False
    return a[0] == b[0] and (precision < MONTH or a[1] == b[1]) and (precision < DAY or a[2] == b[2])


def _format(date: tuple[int, int, int, int]) -> str:
    year = f"{abs(date[0])} BCE" if date[0] < 0 else str(date[0])
    return year if date[3] <= YEAR else f"{year}-{date[1]:02d}" if date[3] == MONTH else f"{year}-{date[1]:02d}-{date[2]:02d}"


def check_site(base_url: str, site_fetch: Fetch, wikidata_fetch: Fetch) -> list[Result]:
    results, cache = [], {}
    for document_url in document_urls(base_url.rstrip("/") + AUDIT_PATH, site_fetch):
        response = site_fetch(document_url)
        record = cps_canonical.find_record(response.body) if response.status == 200 else None
        claims = (record or {}).get("claim", [])
        for claim in claims if isinstance(claims, list) else [claims]:
            if isinstance(claim, dict):
                results.append(check_claim(claim, wikidata_fetch, cache))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="base URL of the site")
    parser.add_argument("--insecure", action="store_true", help="skip TLS certificate checks of the site (local development only)")
    arguments = parser.parse_args()

    results = check_site(arguments.site, http_fetch(arguments.insecure), http_fetch(user_agent=USER_AGENT))
    for result in results:
        print(f"{result.status:12} {result.fact}" + (f"  ({result.detail})" if result.detail else ""))
    counts = {status: sum(r.status == status for r in results) for status in ("confirmed", "contradicted", "unknown")}
    print(f"\n{len(results)} facts: {counts['confirmed']} confirmed, {counts['contradicted']} contradicted, {counts['unknown']} unknown")
    return 1 if counts["contradicted"] else 0


if __name__ == "__main__":
    sys.exit(main())
