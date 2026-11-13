from __future__ import annotations

import base64
import json

import vectors
from verify_site import verify_site

SITE = "https://example.org"
VECTOR = vectors.CANONICALIZATION / "01-basic"


def fake_site(page_html: str) -> dict[str, tuple[str, str]]:
    signed = json.loads((VECTOR / "expected.json").read_text())["signedRecord"]
    _, key_id, public_hex = vectors.test_key()
    x = base64.urlsafe_b64encode(bytes.fromhex(public_hex)).rstrip(b"=").decode()
    page = page_html.replace("</head>", f'<script type="application/ld+json">{json.dumps(signed)}</script></head>')
    listing_1 = {"site": {"keys": f"{SITE}/keys"}, "documents": [{"url": f"{SITE}/a", "@id": signed["@id"], "signature": signed["signature"]}]}
    listing_2 = {"documents": [{"url": f"{SITE}/b", "@id": "urn:x"}]}
    return {
        f"{SITE}/.well-known/content-provenance": (json.dumps(listing_1), f'<{SITE}/audit?page=2>; rel="next"'),
        f"{SITE}/audit?page=2": (json.dumps(listing_2), ""),
        f"{SITE}/keys": (json.dumps({"keys": [{"keyId": key_id, "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": x}}]}), ""),
        f"{SITE}/a": (page, ""),
    }


def test_valid_signed_page_and_unsigned_page_across_listing_pages() -> None:
    responses = fake_site((VECTOR / "input.html").read_text())
    results = verify_site(SITE, responses.__getitem__)
    assert [(r.url, r.status) for r in results] == [(f"{SITE}/a", "valid"), (f"{SITE}/b", "unsigned")]


def test_changed_page_is_reported_invalid() -> None:
    responses = fake_site((VECTOR / "input.html").read_text().replace("Records", "Altered records"))
    results = verify_site(SITE, responses.__getitem__)
    assert results[0].status == "invalid"
    assert "content hash" in results[0].detail
