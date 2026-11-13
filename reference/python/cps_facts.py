"""Reference implementation of Section 3.3 (Fact-level addressing).

Checks a Fact in a Record against its Document and builds the Web Annotation
that the Audit Endpoint serves at /.well-known/content-provenance/facts/{id}.
Written for clarity rather than speed, like cps_canonical.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import html5lib

import cps_canonical

FRAGMENT_PREFIX = "fact-"
FACTS_PATH = "/.well-known/content-provenance/facts/"
DEFAULT_VOCABULARY = "https://schema.org/"
ANNOTATION_CONTEXT = ["http://www.w3.org/ns/anno.jsonld", "https://cms-provenance.org/ns/v1"]
CONFIDENCE = ("measured", "estimated", "asserted")
REQUIRED = ("text", "subject", "predicate", "object")
OPTIONAL_BODY = ("evidence", "confidence", "validFrom", "validUntil")
FACT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def fact_id(claim: dict[str, Any], document_url: str) -> str | None:
    """The {id} of a Fact URI of the form {Document URL}#fact-{id}, or None."""
    prefix = document_url.split("#", 1)[0] + "#" + FRAGMENT_PREFIX
    identifier = claim.get("@id")
    if not isinstance(identifier, str) or not identifier.startswith(prefix):
        return None
    candidate = identifier[len(prefix):]
    return candidate if FACT_ID.match(candidate) else None


def anchors(html: str) -> dict[str, str]:
    """Elements whose id starts with "fact-", mapped to their normalised text."""
    document = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=False)
    found = {}
    for element in document.iter():
        identifier = element.attrib.get("id", "") if isinstance(element.tag, str) else ""
        if identifier.startswith(FRAGMENT_PREFIX):
            found[identifier] = cps_canonical.normalise_text("".join(element.itertext()))
    return found


def predicate_uri(predicate: str) -> str:
    """Section 3.3: a bare term is read as a schema.org term."""
    return predicate if re.match(r"^[a-z][a-z0-9+.-]*:", predicate, re.IGNORECASE) else DEFAULT_VOCABULARY + predicate


def annotation(claim: dict[str, Any], document_url: str) -> dict[str, Any]:
    """The Web Annotation for a Fact (Section 3.3), without implementation-specific members such as "created"."""
    identifier = fact_id(claim, document_url)
    if identifier is None:
        raise ValueError(f"{claim.get('@id')!r} is not a Fact URI of {document_url}")
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(document_url))
    body = {
        "id": claim["@id"],
        "subject": claim["subject"],
        "predicate": predicate_uri(claim["predicate"]),
        "object": claim["object"],
    }
    body.update({name: claim[name] for name in OPTIONAL_BODY if name in claim})
    return {
        "@context": ANNOTATION_CONTEXT,
        "id": origin + FACTS_PATH + identifier,
        "type": "Annotation",
        "motivation": "describing",
        "body": body,
        "target": {
            "source": document_url.split("#", 1)[0],
            "selector": [
                {"type": "FragmentSelector", "conformsTo": "http://tools.ietf.org/rfc/rfc3986", "value": FRAGMENT_PREFIX + identifier},
                {"type": "TextQuoteSelector", "exact": claim["text"]},
            ],
        },
    }


def claim_problems(claim: dict[str, Any], html: str, document_url: str) -> list[str]:
    """Everything in which a Claim of the Record contradicts Section 3.3 or its Document."""
    problems = [f"{name} is missing" for name in REQUIRED if name not in claim]
    identifier = fact_id(claim, document_url)
    if identifier is None:
        problems.append(f"@id {claim.get('@id')!r} is not of the form {document_url}#fact-{{id}}")
    if "confidence" in claim and claim["confidence"] not in CONFIDENCE:
        problems.append(f"confidence {claim['confidence']!r} is not one of {', '.join(CONFIDENCE)}")

    text = claim.get("text")
    if isinstance(text, str):
        quoted = cps_canonical.normalise_text(text)
        if quoted not in cps_canonical.canonical_text(html):
            problems.append(f"text {text!r} is not found in the canonical text of the Document")
        anchored = anchors(html).get(FRAGMENT_PREFIX + identifier) if identifier else None
        if anchored is not None and anchored != quoted:
            problems.append(f"element {FRAGMENT_PREFIX}{identifier} contains {anchored!r}, not the quoted words")
    return problems
