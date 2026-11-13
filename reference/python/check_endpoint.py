"""Checks a site's Audit Endpoint against Section 3.4 of the specification.

    uv run python check_endpoint.py https://example.org/
    uv run python check_endpoint.py https://project.ddev.site/ --insecure   # local dev certificates

Validates every listing page, the key list and each key resource against
schemas/audit-endpoint.schema.json, and checks what a schema cannot express:
pagination, cross-origin headers and that every signing key is published.
Exits with 1 if anything does not conform. Signatures themselves are checked
by verify_site.py.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from jsonschema import Draft202012Validator

AUDIT_PATH = "/.well-known/content-provenance"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "audit-endpoint.schema.json"
MAX_PAGES = 1000


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]  # names in lower case
    body: str


# fetch(url) -> Response, for any status code
Fetch = Callable[[str], Response]


@dataclass(frozen=True)
class Finding:
    resource: str
    message: str

    def __str__(self) -> str:
        return f"{self.resource}: {self.message}"


class _Checker:
    def __init__(self, fetch: Fetch) -> None:
        self.fetch = fetch
        self.findings: list[Finding] = []
        self.schema = json.loads(SCHEMA_PATH.read_text())

    def report(self, resource: str, message: str) -> None:
        self.findings.append(Finding(resource, message))

    def read(self, url: str, definition: str) -> tuple[dict | None, Response | None]:
        """Fetches a resource, checks status and headers and validates it against a schema definition."""
        response = self.fetch(url)
        if response.status != 200:
            self.report(url, f"answered with status {response.status}, expected 200")
            return None, None
        if "json" not in response.headers.get("content-type", ""):
            self.report(url, f"Content-Type is {response.headers.get('content-type', 'missing')!r}, expected application/json")
        if response.headers.get("access-control-allow-origin") != "*":
            self.report(url, "should allow cross-origin reads (Access-Control-Allow-Origin: *)")
        try:
            document = json.loads(response.body)
        except json.JSONDecodeError as error:
            self.report(url, f"is not valid JSON ({error.msg})")
            return None, None

        validator = Draft202012Validator(
            {"$ref": f"#/$defs/{definition}", "$defs": self.schema["$defs"]},
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        for error in sorted(validator.iter_errors(document), key=lambda error: list(error.absolute_path)):
            self.report(url, self._describe(error))
        return (document if isinstance(document, dict) else None), response

    def _describe(self, error) -> str:
        path = "/".join(str(part) for part in error.absolute_path) or "(root)"
        if error.validator == "pattern" and error.validator_value == self.schema["$defs"]["absoluteUrl"]["pattern"]:
            return f"{path}: {error.instance!r} is not an absolute URL"
        if error.validator == "not" and path.endswith("publicKeyJwk"):
            return f"{path}: contains private key material"
        return f"{path}: {error.message}"


def check_endpoint(base_url: str, fetch: Fetch) -> list[Finding]:
    checker = _Checker(fetch)
    pages = _read_pages(checker, base_url.rstrip("/") + AUDIT_PATH)
    if not pages:
        return checker.findings

    first_url, first = pages[0]
    entries = [entry for _, page in pages for entry in page.get("documents", []) if isinstance(entry, dict)]
    _check_entries(checker, first_url, first, entries)

    keys_url = first.get("site", {}).get("keys")
    if isinstance(keys_url, str) and keys_url.startswith(("http://", "https://")):
        published = _check_keys(checker, keys_url)
        for entry in entries:
            key_id = entry.get("signature", {}).get("keyId")
            if key_id is not None and key_id not in published:
                checker.report(first_url, f"{entry.get('url')}: signature keyId {key_id} is not in the key list")
    return checker.findings


def _read_pages(checker: _Checker, url: str) -> list[tuple[str, dict]]:
    pages: list[tuple[str, dict]] = []
    seen: set[str] = set()
    while url and url not in seen and len(pages) < MAX_PAGES:
        seen.add(url)
        listing, response = checker.read(url, "listing")
        if listing is None:
            return pages
        page_links = links(response.headers.get("link", ""), url)
        if listing.get("page") != len(pages) + 1:
            checker.report(url, f"page is {listing.get('page')!r}, expected {len(pages) + 1}")
        if pages and "prev" not in page_links:
            checker.report(url, 'has no Link with rel="prev"')
        pages.append((url, listing))
        url = page_links.get("next")
    if url in seen:
        checker.report(url, 'rel="next" leads back to a page already read')
    return pages


def _check_entries(checker: _Checker, listing_url: str, first: dict, entries: list[dict]) -> None:
    identifiers = [entry.get("@id") for entry in entries]
    for identifier in sorted({i for i in identifiers if isinstance(i, str) and identifiers.count(i) > 1}):
        checker.report(listing_url, f"{identifier} is listed more than once")
    total = first.get("totalItems")
    if isinstance(total, int) and total != len(entries):
        checker.report(listing_url, f"totalItems is {total}, but the pages list {len(entries)} documents")


def _check_keys(checker: _Checker, keys_url: str) -> set[str]:
    key_list, _ = checker.read(keys_url, "keyList")
    if key_list is None:
        return set()
    published = set()
    for entry in key_list.get("keys", []):
        key_id = entry.get("keyId") if isinstance(entry, dict) else None
        if not isinstance(key_id, str):
            continue
        published.add(key_id)
        key_url = keys_url.rstrip("/") + "/" + key_id
        single, _ = checker.read(key_url, "keyEntry")
        if single is not None and single != entry:
            checker.report(key_url, "differs from the entry in the key list")
    return published


def links(header: str, base: str) -> dict[str, str]:
    """Maps each rel of an RFC 8288 Link header to its target, resolved against the page URL."""
    links = {}
    for target, parameters in re.findall(r"<([^>]*)>\s*((?:;[^,]*)*)", header):
        for rel in re.findall(r'rel="?([^";]+)"?', parameters):
            for name in rel.split():
                links.setdefault(name, urljoin(base, target))
    return links


def http_fetch(insecure: bool = False, user_agent: str = "cps-check-endpoint/0.4") -> Fetch:
    context = ssl._create_unverified_context() if insecure else None

    def fetch(url: str) -> Response:
        request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, context=context, timeout=30) as response:
                return Response(response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return Response(error.code, {k.lower(): v for k, v in error.headers.items()}, error.read().decode("utf-8", "replace"))

    return fetch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="base URL of the site")
    parser.add_argument("--insecure", action="store_true", help="skip TLS certificate checks (local development only)")
    arguments = parser.parse_args()

    findings = check_endpoint(arguments.site, http_fetch(arguments.insecure))
    for finding in findings:
        print(finding)
    print(f"\n{len(findings)} findings" if findings else "The Audit Endpoint conforms to Section 3.4.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
