"""Checks every signed document of a site against Annex A.5.2.

    uv run python verify_site.py https://example.org/
    uv run python verify_site.py https://project.ddev.site/ --insecure   # local dev certificates

Walks the Audit Endpoint (following rel="next"), resolves keys through the key
endpoint, fetches each document and verifies hash and signature. Exits with 1
if any signed document fails verification.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import ssl
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

import cps_canonical

AUDIT_PATH = "/.well-known/content-provenance"

# fetch(url) -> (body, Link header value)
Fetch = Callable[[str], tuple[str, str]]


@dataclass(frozen=True)
class Result:
    url: str
    status: str  # "valid", "invalid", "unsigned"
    detail: str = ""


def verify_site(base_url: str, fetch: Fetch) -> list[Result]:
    listing_url = base_url.rstrip("/") + AUDIT_PATH
    entries, keys_url = [], None
    while listing_url:
        body, link = fetch(listing_url)
        listing = json.loads(body)
        keys_url = keys_url or listing.get("site", {}).get("keys")
        entries.extend(listing.get("documents", []))
        listing_url = _next_link(link)

    keys = _load_keys(keys_url, fetch) if keys_url else {}
    return [_verify_entry(entry, keys, fetch) for entry in entries]


def _verify_entry(entry: dict, keys: dict[str, Ed25519PublicKey], fetch: Fetch) -> Result:
    url = entry["url"]
    if "signature" not in entry:
        return Result(url, "unsigned")

    html, _ = fetch(url)
    record = cps_canonical.find_record(html)
    if record is None:
        return Result(url, "invalid", "page has no provenance record")
    if record.get("@id") != entry.get("@id"):
        return Result(url, "invalid", "record identifier differs from the audit listing")
    key = keys.get(record.get("signature", {}).get("keyId", ""))
    if key is None:
        return Result(url, "invalid", "signing key is not published")
    if record.get("contentHash") != cps_canonical.content_hash(html):
        return Result(url, "invalid", "content hash does not match the delivered page")
    if not cps_canonical.verify(html, record, key):
        return Result(url, "invalid", "signature does not verify")
    return Result(url, "valid")


def _load_keys(keys_url: str, fetch: Fetch) -> dict[str, Ed25519PublicKey]:
    body, _ = fetch(keys_url)
    keys = {}
    for key in json.loads(body).get("keys", []):
        jwk = key.get("publicKeyJwk", {})
        if jwk.get("kty") == "OKP" and jwk.get("crv") == "Ed25519":
            x = jwk["x"] + "=" * (-len(jwk["x"]) % 4)
            keys[key["keyId"]] = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(x))
    return keys


def _next_link(link_header: str) -> str | None:
    match = re.search(r'<([^>]+)>\s*;\s*rel="next"', link_header or "")
    return match.group(1) if match else None


def http_fetch(insecure: bool = False) -> Fetch:
    context = ssl._create_unverified_context() if insecure else None

    def fetch(url: str) -> tuple[str, str]:
        request = urllib.request.Request(url, headers={"User-Agent": "cps-verify-site/0.3"})
        with urllib.request.urlopen(request, context=context, timeout=30) as response:
            return response.read().decode("utf-8"), response.headers.get("Link", "")

    return fetch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="base URL of the site")
    parser.add_argument("--insecure", action="store_true", help="skip TLS certificate checks (local development only)")
    arguments = parser.parse_args()

    results = verify_site(arguments.site, http_fetch(arguments.insecure))
    for result in results:
        print(f"{result.status:9} {result.url}" + (f"  ({result.detail})" if result.detail else ""))
    counts = {status: sum(r.status == status for r in results) for status in ("valid", "invalid", "unsigned")}
    print(f"\n{len(results)} documents: {counts['valid']} valid, {counts['invalid']} invalid, {counts['unsigned']} unsigned")
    return 1 if counts["invalid"] else 0


if __name__ == "__main__":
    sys.exit(main())
