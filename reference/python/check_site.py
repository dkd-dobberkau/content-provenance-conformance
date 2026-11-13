"""Reports the conformance level each Document of a site reaches (Section 4).

    uv run python check_site.py https://example.org/
    uv run python check_site.py https://project.ddev.site/ --insecure   # local dev certificates

Takes the Documents from the Audit Endpoint, or from the XML sitemap when there
is none, and checks each level in turn: L1 sitemap, canonical URL and JSON-LD;
L2 a complete Record (cps_record.py); L3 a signature that verifies
(verify_site.py); L4 a conforming Audit Endpoint (check_endpoint.py) and
conforming Facts (check_facts.py). Levels are cumulative. Prints the level each
Document reaches, what blocks the next one, and exits with 1 if a Document or
the site claims a higher level than it reaches.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from typing import Any

import html5lib

import cps_canonical
import cps_record
import verify_site
from check_endpoint import AUDIT_PATH, Fetch, Finding, check_endpoint, http_fetch
from check_facts import check_document_facts, document_urls

LEVEL_NAMES = {0: "below L1", 1: "L1 Discoverable", 2: "L2 Provenance", 3: "L3 Verifiable", 4: "L4 Citable"}
SITEMAP_NAMESPACE = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
MAX_SITEMAPS = 50


@dataclass(frozen=True)
class DocumentResult:
    url: str
    claimed: int | None
    reached: int
    blockers: list[str] = field(default_factory=list)  # why the next level is not reached


@dataclass(frozen=True)
class SiteResult:
    documents: list[DocumentResult]
    claimed: int | None
    reached: int
    endpoint_findings: list[Finding]

    def overclaims(self) -> list[str]:
        """Every claim of a level higher than the one reached."""
        claims = [
            f"{d.url} claims L{d.claimed} but reaches {LEVEL_NAMES[d.reached]}"
            for d in self.documents
            if d.claimed is not None and d.claimed > d.reached
        ]
        if self.claimed is not None and self.claimed > self.reached:
            claims.append(f"the Audit Endpoint claims L{self.claimed} for the site but it reaches {LEVEL_NAMES[self.reached]}")
        return claims


def check_site(base_url: str, fetch: Fetch) -> SiteResult:
    base = base_url.rstrip("/")
    sitemap = sitemap_urls(base, fetch)
    listing_response = fetch(base + AUDIT_PATH)

    if listing_response.status == 200:
        endpoint_findings = check_endpoint(base, fetch)
        urls = document_urls(base + AUDIT_PATH, fetch)
        claimed = _site_claim(listing_response.body)
        verification = _verify(base, fetch)
    else:
        endpoint_findings = [Finding(base + AUDIT_PATH, f"answered with status {listing_response.status}")]
        urls = sorted(sitemap)
        claimed = None
        verification = None

    documents = [_check_document(url, fetch, sitemap, verification, endpoint_findings) for url in urls]
    reached = min((d.reached for d in documents), default=0)
    return SiteResult(documents, claimed, reached, endpoint_findings)


def _check_document(
    url: str,
    fetch: Fetch,
    sitemap: set[str],
    verification: dict[str, verify_site.Result] | None,
    endpoint_findings: list[Finding],
) -> DocumentResult:
    response = fetch(url)
    if response.status != 200:
        return DocumentResult(url, None, 0, [f"answered with status {response.status}"])
    html = response.body
    record = cps_canonical.find_record(html)

    requirements = {
        1: _discoverability_problems(url, html, sitemap),
        2: ["has no Provenance Record"] if record is None else cps_record.problems(record),
        3: _signature_problems(url, verification),
        4: _citability_problems(url, html, fetch, verification, endpoint_findings),
    }
    reached, blockers = 0, []
    for level, problems in requirements.items():
        if problems:
            blockers = problems
            break
        reached = level

    claimed = record.get("cpsConformance") if record else None
    return DocumentResult(url, claimed if isinstance(claimed, int) else None, reached, blockers)


def _discoverability_problems(url: str, html: str, sitemap: set[str]) -> list[str]:
    problems = []
    if url not in sitemap:
        problems.append("is not listed in the XML sitemap")
    canonical = _canonical_url(html)
    if canonical is None:
        problems.append('has no <link rel="canonical">')
    elif not canonical.startswith(("http://", "https://")):
        problems.append(f"canonical URL {canonical!r} is not absolute")
    if not _has_schema_org_json_ld(html):
        problems.append("has no schema.org metadata as JSON-LD")
    return problems


def _signature_problems(url: str, verification: dict[str, verify_site.Result] | None) -> list[str]:
    if verification is None:
        return ["no Audit Endpoint publishes the Site Key, so no signature can be verified"]
    result = verification.get(url)
    if result is None:
        return ["is not listed by the Audit Endpoint"]
    if result.status != "valid":
        return [f"signature is {result.status}" + (f": {result.detail}" if result.detail else "")]
    return []


def _citability_problems(
    url: str,
    html: str,
    fetch: Fetch,
    verification: dict[str, verify_site.Result] | None,
    endpoint_findings: list[Finding],
) -> list[str]:
    if verification is None:
        return ["the site has no Audit Endpoint"]
    problems = []
    if endpoint_findings:
        problems.append(f"the Audit Endpoint has {len(endpoint_findings)} findings; run check_endpoint.py")
    facts_findings, _ = check_document_facts(url, html, fetch)
    problems.extend(str(finding) for finding in facts_findings)
    return problems


def _verify(base: str, fetch: Fetch) -> dict[str, verify_site.Result]:
    def legacy_fetch(url: str) -> tuple[str, str]:
        response = fetch(url)
        if response.status != 200:
            raise OSError(f"{url} answered with status {response.status}")
        return response.body, response.headers.get("link", "")

    try:
        return {result.url: result for result in verify_site.verify_site(base, legacy_fetch)}
    except (OSError, ValueError, KeyError, TypeError) as error:
        # A broken endpoint is reported by check_endpoint; no signature counts as verified.
        print(f"Signatures could not be checked: {error}", file=sys.stderr)
        return {}


def sitemap_urls(base: str, fetch: Fetch) -> set[str]:
    """The page URLs of the XML sitemap at /sitemap.xml or those named in /robots.txt."""
    queue = [base + "/sitemap.xml"]
    robots = fetch(base + "/robots.txt")
    if robots.status == 200:
        queue += [line.split(":", 1)[1].strip() for line in robots.body.splitlines() if line.lower().startswith("sitemap:")]

    pages, seen = set(), set()
    while queue and len(seen) < MAX_SITEMAPS:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        response = fetch(url)
        if response.status != 200:
            continue
        try:
            root = ElementTree.fromstring(response.body)
        except ElementTree.ParseError:
            continue
        locations = [loc.text.strip() for loc in root.iter(SITEMAP_NAMESPACE + "loc") if loc.text]
        if root.tag == SITEMAP_NAMESPACE + "sitemapindex":
            queue += locations
        else:
            pages.update(locations)
    return pages


def _canonical_url(html: str) -> str | None:
    document = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=False)
    for link in document.iter("link"):
        if "canonical" in link.attrib.get("rel", "").lower().split():
            return link.attrib.get("href", "").strip()
    return None


def _has_schema_org_json_ld(html: str) -> bool:
    document = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=False)
    for script in document.iter("script"):
        if script.attrib.get("type") != "application/ld+json":
            continue
        try:
            data = json.loads(script.text or "")
        except json.JSONDecodeError:
            continue
        context = data.get("@context") if isinstance(data, dict) else None
        contexts = context if isinstance(context, list) else [context]
        if any(isinstance(c, str) and c.rstrip("/") in ("https://schema.org", "http://schema.org") for c in contexts):
            return True
    return False


def _site_claim(body: str) -> int | None:
    try:
        listing: Any = json.loads(body)
    except json.JSONDecodeError:
        return None
    claimed = listing.get("cpsConformance") if isinstance(listing, dict) else None
    return claimed if isinstance(claimed, int) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", help="base URL of the site")
    parser.add_argument("--insecure", action="store_true", help="skip TLS certificate checks (local development only)")
    arguments = parser.parse_args()

    result = check_site(arguments.site, http_fetch(arguments.insecure))
    for document in result.documents:
        claim = f"claims L{document.claimed}" if document.claimed is not None else "claims no level"
        print(f"{LEVEL_NAMES[document.reached]:16} {document.url}  ({claim})")
        for blocker in document.blockers:
            print(f"{'':16}   next level blocked: {blocker}")
    site_claim = f"claims L{result.claimed}" if result.claimed is not None else "claims no level"
    print(f"\nSite: {len(result.documents)} documents, reaches {LEVEL_NAMES[result.reached]} ({site_claim})")
    overclaims = result.overclaims()
    for overclaim in overclaims:
        print(f"Overclaim: {overclaim}")
    return 1 if overclaims else 0


if __name__ == "__main__":
    sys.exit(main())
