from __future__ import annotations

import copy
import json

from check_endpoint import Response, check_endpoint

SITE = "https://example.org"
LISTING = f"{SITE}/.well-known/content-provenance"
KEYS = f"{LISTING}/keys"
KEY_ID = "key-2026-11-13-abcdef"
JSON_HEADERS = {"content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*"}

KEY_ENTRY = {
    "keyId": KEY_ID,
    "algorithm": "Ed25519",
    "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"},
    "createdAt": "2026-11-13T10:00:00Z",
    "retiredAt": None,
}


def document(path: str, identifier: str, signed: bool = True) -> dict:
    entry = {
        "url": f"{SITE}{path}",
        "@id": identifier,
        "datePublished": "2026-11-13T09:00:00Z",
        "lastSubstantiveRevision": "2026-11-13T10:00:00Z",
        "cpsConformance": 4 if signed else 2,
    }
    if signed:
        entry["contentHash"] = "sha256:" + "a" * 64
        entry["signature"] = {"algorithm": "Ed25519", "keyId": KEY_ID, "signatureValue": "c2lnbmF0dXJl"}
    return entry


def listing(page: int, documents: list[dict]) -> dict:
    return {
        "@context": ["https://schema.org", "https://cms-provenance.org/ns/v1"],
        "specVersion": "0.4",
        "generator": "Example CMS 1.0",
        "cpsConformance": 4,
        "site": {"url": f"{SITE}/", "keys": KEYS},
        "totalItems": 3,
        "page": page,
        "pageSize": 2,
        "documents": documents,
    }


def conforming_site() -> dict[str, dict]:
    """Two listing pages, one key; every resource as the specification defines it."""
    return {
        LISTING: {
            "body": listing(1, [document("/", "urn:uuid:1"), document("/a", "urn:uuid:2")]),
            "link": f'<{LISTING}?page=2>; rel="next", <{LISTING}?page=1>; rel="first", <{LISTING}?page=2>; rel="last"',
        },
        f"{LISTING}?page=2": {
            "body": listing(2, [document("/b", "urn:uuid:3", signed=False)]),
            "link": f'<{LISTING}?page=1>; rel="prev", <{LISTING}?page=1>; rel="first", <{LISTING}?page=2>; rel="last"',
        },
        KEYS: {"body": {"keys": [KEY_ENTRY]}},
        f"{KEYS}/{KEY_ID}": {"body": KEY_ENTRY},
    }


def fetcher(site: dict[str, dict]):
    def fetch(url: str) -> Response:
        if url not in site:
            return Response(404, JSON_HEADERS, '{"error": "not found"}')
        resource = site[url]
        headers = dict(resource.get("headers", JSON_HEADERS))
        if "link" in resource:
            headers["link"] = resource["link"]
        return Response(resource.get("status", 200), headers, json.dumps(resource["body"]))

    return fetch


def messages(site: dict[str, dict]) -> list[str]:
    return [str(finding) for finding in check_endpoint(SITE, fetcher(site))]


def test_conforming_endpoint_has_no_findings() -> None:
    assert messages(conforming_site()) == []


def test_relative_urls_are_reported() -> None:
    site = conforming_site()
    site[LISTING]["body"]["site"]["keys"] = "/.well-known/content-provenance/keys"
    site[LISTING]["body"]["documents"][1]["url"] = "/a"

    found = messages(site)

    assert any("site/keys" in message for message in found), found
    assert any("documents/1/url" in message for message in found), found


def test_missing_required_fields_are_reported() -> None:
    site = conforming_site()
    del site[LISTING]["body"]["generator"]
    del site[LISTING]["body"]["documents"][0]["contentHash"]

    found = messages(site)

    assert any("'generator' is a required property" in message for message in found), found
    assert any("'contentHash' is a dependency of 'signature'" in message for message in found), found


def test_private_key_material_is_reported() -> None:
    site = conforming_site()
    leaked = copy.deepcopy(KEY_ENTRY)
    leaked["publicKeyJwk"]["d"] = "c2VjcmV0"
    site[KEYS]["body"] = {"keys": [leaked]}

    assert any("private key" in message for message in messages(site))


def test_signature_with_unpublished_key_is_reported() -> None:
    site = conforming_site()
    site[LISTING]["body"]["documents"][0]["signature"]["keyId"] = "key-unknown"

    assert any("key-unknown" in message and "not in the key list" in message for message in messages(site))


def test_single_key_resource_must_exist() -> None:
    site = conforming_site()
    del site[f"{KEYS}/{KEY_ID}"]

    assert any(f"{KEYS}/{KEY_ID}" in message and "404" in message for message in messages(site))


def test_missing_cors_header_is_reported() -> None:
    site = conforming_site()
    site[KEYS]["headers"] = {"content-type": "application/json"}

    assert any(KEYS in message and "Access-Control-Allow-Origin" in message for message in messages(site))


def test_pagination_must_add_up() -> None:
    site = conforming_site()
    site[f"{LISTING}?page=2"]["body"]["documents"] = [document("/a", "urn:uuid:2")]

    found = messages(site)

    assert any("urn:uuid:2" in message and "more than once" in message for message in found), found


def test_total_items_must_match_the_entries() -> None:
    site = conforming_site()
    for url in (LISTING, f"{LISTING}?page=2"):
        site[url]["body"]["totalItems"] = 5

    assert any("totalItems is 5" in message for message in messages(site))


def test_listing_that_is_not_json_is_reported_without_crashing() -> None:
    site = conforming_site()
    site[LISTING] = {"body": "<html>Forbidden</html>", "status": 403, "headers": {"content-type": "text/html"}}

    found = messages(site)

    assert len(found) == 1 and "403" in found[0], found
