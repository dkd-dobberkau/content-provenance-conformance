"""Checks the Facts of a site against Section 3.3 of the specification.

    uv run python check_facts.py https://example.org/
    uv run python check_facts.py https://project.ddev.site/ --insecure   # local dev certificates

Walks the Audit Endpoint, reads the Record of every listed Document and checks
each Claim against its Document: Fact URI, quoted words in the canonical text,
the fragment element. Then compares the Web Annotation served for the Fact
with the one Section 3.3 defines; additional members such as "created" are
allowed. Exits with 1 if anything does not conform.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import cps_canonical
import cps_facts
from check_endpoint import AUDIT_PATH, MAX_PAGES, Fetch, Finding, http_fetch, links


def check_facts(base_url: str, fetch: Fetch) -> tuple[list[Finding], int]:
    """Findings, and the number of Facts checked."""
    findings: list[Finding] = []
    checked = 0
    for document_url in _document_urls(base_url.rstrip("/") + AUDIT_PATH, fetch):
        response = fetch(document_url)
        if response.status != 200:
            findings.append(Finding(document_url, f"answered with status {response.status}, expected 200"))
            continue
        record = cps_canonical.find_record(response.body) or {}
        claims = record.get("claim", [])
        for claim in claims if isinstance(claims, list) else [claims]:
            checked += 1
            label = claim.get("@id", document_url) if isinstance(claim, dict) else document_url
            if not isinstance(claim, dict):
                findings.append(Finding(document_url, "claim is not an object"))
                continue
            findings.extend(Finding(label, problem) for problem in cps_facts.claim_problems(claim, response.body, document_url))
            if cps_facts.fact_id(claim, document_url) is not None:
                findings.extend(_check_annotation(claim, document_url, fetch))
    return findings, checked


def _check_annotation(claim: dict[str, Any], document_url: str, fetch: Fetch) -> list[Finding]:
    expected = cps_facts.annotation(claim, document_url)
    url = expected["id"]
    response = fetch(url)
    if response.status != 200:
        return [Finding(url, f"answered with status {response.status}; Facts SHOULD be exposed as Web Annotations")]
    findings = []
    if "ld+json" not in response.headers.get("content-type", ""):
        findings.append(Finding(url, f"Content-Type is {response.headers.get('content-type', 'missing')!r}, expected application/ld+json"))
    if response.headers.get("access-control-allow-origin") != "*":
        findings.append(Finding(url, "should allow cross-origin reads (Access-Control-Allow-Origin: *)"))
    try:
        served = json.loads(response.body)
    except json.JSONDecodeError as error:
        return [*findings, Finding(url, f"is not valid JSON ({error.msg})")]
    findings.extend(Finding(url, difference) for difference in _differences(served, expected, ""))
    return findings


def _differences(served: Any, expected: Any, path: str) -> list[str]:
    """Where `served` lacks or contradicts `expected`; members `expected` does not name are allowed."""
    if isinstance(expected, dict):
        if not isinstance(served, dict):
            return [f"{path or '(root)'}: expected an object"]
        return [d for key, value in expected.items() for d in _differences(served.get(key), value, f"{path}/{key}" if path else key)]
    if isinstance(expected, list) and all(isinstance(item, dict) for item in expected):
        # Selectors: each expected one must be served, in any order.
        served_items = served if isinstance(served, list) else []
        return [
            f"{path}: no entry matches {item}"
            for item in expected
            if not any(not _differences(candidate, item, "") for candidate in served_items)
        ]
    return [] if served == expected else [f"{path}: {served!r}, expected {expected!r}"]


def _document_urls(listing_url: str, fetch: Fetch) -> list[str]:
    urls, seen = [], set()
    while listing_url and listing_url not in seen and len(seen) < MAX_PAGES:
        seen.add(listing_url)
        response = fetch(listing_url)
        if response.status != 200:
            break
        urls.extend(entry["url"] for entry in json.loads(response.body).get("documents", []) if isinstance(entry, dict) and "url" in entry)
        listing_url = links(response.headers.get("link", ""), listing_url).get("next")
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="base URL of the site")
    parser.add_argument("--insecure", action="store_true", help="skip TLS certificate checks (local development only)")
    arguments = parser.parse_args()

    findings, checked = check_facts(arguments.site, http_fetch(arguments.insecure))
    for finding in findings:
        print(finding)
    print(f"\n{checked} facts checked, {len(findings)} findings")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
