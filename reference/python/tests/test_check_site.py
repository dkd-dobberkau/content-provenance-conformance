from __future__ import annotations

import base64
import copy
import json

import cps_canonical
import vectors
from check_endpoint import Response
from check_site import check_site

SITE = "https://example.org"
PAGE = f"{SITE}/a"
LISTING = f"{SITE}/.well-known/content-provenance"
JSON_HEADERS = {"content-type": "application/json", "access-control-allow-origin": "*"}
RECORD = {
    "@context": ["https://schema.org", "https://cms-provenance.org/ns/v1"],
    "@type": "WebPage",
    "@id": "urn:uuid:00000000-0000-4000-8000-000000000001",
    "author": [{"@type": "Person", "@id": "https://example.org/people/ada"}],
    "datePublished": "2026-11-13T09:00:00Z",
    "lastSubstantiveRevision": "2026-11-13T10:00:00Z",
    "generator": "Example CMS 1.0",
    "cpsConformance": 4,
}


def page(record: dict, canonical: str = PAGE) -> tuple[str, dict]:
    """A page whose Record is signed with the RFC 8032 test key; returns the HTML and the signed Record."""
    private_key, key_id, _ = vectors.test_key()
    body = "<main><h1>Page A</h1><p>Text of page A.</p></main>"
    unsigned = f'<!DOCTYPE html><html><head><title>A</title><link rel="canonical" href="{canonical}"></head><body>{body}</body></html>'
    record = {**record, "key": f"{LISTING}/keys/{key_id}", "contentHash": cps_canonical.content_hash(unsigned)}
    signed = cps_canonical.sign(record, private_key, key_id)
    html = unsigned.replace("</head>", f'<script type="application/ld+json">{json.dumps(signed)}</script></head>')
    return html, signed


def site(record: dict | None = None, canonical: str = PAGE, in_sitemap: bool = True, endpoint: bool = True) -> dict[str, Response]:
    _, key_id, public_hex = vectors.test_key()
    html, signed = page(record or RECORD, canonical)
    key = {
        "keyId": key_id,
        "algorithm": "Ed25519",
        "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(bytes.fromhex(public_hex)).rstrip(b"=").decode()},
        "createdAt": "2026-11-13T08:00:00Z",
        "retiredAt": None,
    }
    listing = {
        "@context": ["https://schema.org", "https://cms-provenance.org/ns/v1"],
        "specVersion": "0.4",
        "generator": "Example CMS 1.0",
        "cpsConformance": 4,
        "site": {"url": f"{SITE}/", "keys": f"{LISTING}/keys"},
        "totalItems": 1,
        "page": 1,
        "pageSize": 100,
        "documents": [{
            "url": PAGE,
            "@id": signed["@id"],
            "datePublished": signed["datePublished"],
            "lastSubstantiveRevision": signed["lastSubstantiveRevision"],
            "cpsConformance": signed["cpsConformance"],
            "contentHash": signed["contentHash"],
            "signature": signed["signature"],
        }],
    }
    locations = f"<url><loc>{PAGE}</loc></url>" if in_sitemap else ""
    responses = {
        f"{SITE}/sitemap.xml": Response(200, {"content-type": "application/xml"}, f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locations}</urlset>'),
        PAGE: Response(200, {"content-type": "text/html"}, html),
    }
    if endpoint:
        responses[LISTING] = Response(200, JSON_HEADERS, json.dumps(listing))
        responses[f"{LISTING}/keys"] = Response(200, JSON_HEADERS, json.dumps({"keys": [key]}))
        responses[f"{LISTING}/keys/{key_id}"] = Response(200, JSON_HEADERS, json.dumps(key))
    return responses


def run(responses: dict[str, Response]):
    return check_site(SITE, lambda url: responses.get(url, Response(404, JSON_HEADERS, "{}")))


def test_conforming_site_reaches_level_four() -> None:
    result = run(site())

    assert [(d.url, d.reached, d.claimed) for d in result.documents] == [(PAGE, 4, 4)]
    assert (result.reached, result.claimed) == (4, 4)
    assert result.overclaims() == []


def test_record_without_author_uri_stays_at_level_one_and_overclaims() -> None:
    record = copy.deepcopy(RECORD)
    record["author"] = [{"@type": "Person", "name": "Ada"}]

    result = run(site(record))

    document = result.documents[0]
    assert document.reached == 1
    assert any("author 1 has no @id" in blocker for blocker in document.blockers)
    assert any(PAGE in claim and "claims L4" in claim and "reaches L1" in claim for claim in result.overclaims())


def test_page_missing_from_the_sitemap_does_not_reach_level_one() -> None:
    document = run(site(in_sitemap=False)).documents[0]

    assert document.reached == 0
    assert any("sitemap" in blocker for blocker in document.blockers)


def test_relative_canonical_url_does_not_reach_level_one() -> None:
    document = run(site(canonical="/a")).documents[0]

    assert document.reached == 0
    assert any("canonical" in blocker for blocker in document.blockers)


def test_without_audit_endpoint_documents_come_from_the_sitemap_and_stop_at_level_two() -> None:
    result = run(site(endpoint=False))

    assert [(d.url, d.reached) for d in result.documents] == [(PAGE, 2)]
    assert any("Audit Endpoint" in blocker for blocker in result.documents[0].blockers)
    assert result.claimed is None
