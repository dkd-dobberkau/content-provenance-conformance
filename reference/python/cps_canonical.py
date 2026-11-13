"""Reference implementation of Annex A (canonicalisation and signing) of the
Content Provenance Specification, Draft 0.3.

This module is written for clarity, not speed. Every function maps to a
numbered step in Annex A; when the two disagree, the specification wins and
this code has a bug.
"""

from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from collections.abc import Iterator
from typing import Any

import html5lib
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

VOCABULARY = "https://cms-provenance.org/ns/v1"

# A.2.2 Content roots and excluded subtrees
CONTENT_ROOT_ATTRIBUTE = "data-cps-content"
IGNORE_ATTRIBUTE = "data-cps-ignore"

EXCLUDED_ELEMENTS = frozenset({
    "head", "script", "style", "template", "noscript", "iframe", "object",
    "embed", "canvas", "svg", "button", "input", "select", "textarea",
})

# A.2.3 Elements that start and end a line
BLOCK_ELEMENTS = frozenset({
    "address", "article", "aside", "blockquote", "caption", "dd", "details",
    "dialog", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer",
    "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li",
    "main", "nav", "ol", "p", "pre", "section", "summary", "table", "tbody",
    "td", "tfoot", "th", "thead", "tr", "ul",
})

# A.2.4 step 1: General_Category Cf as of Unicode 15.1, frozen here so the
# result does not depend on the Unicode version of an implementation.
INVISIBLE_RANGES = (
    (0x00AD, 0x00AD), (0x0600, 0x0605), (0x061C, 0x061C), (0x06DD, 0x06DD),
    (0x070F, 0x070F), (0x0890, 0x0891), (0x08E2, 0x08E2), (0x180E, 0x180E),
    (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x2064), (0x2066, 0x206F),
    (0xFEFF, 0xFEFF), (0xFFF9, 0xFFFB), (0x110BD, 0x110BD), (0x110CD, 0x110CD),
    (0x13430, 0x1343F), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A),
    (0xE0001, 0xE0001), (0xE0020, 0xE007F),
    # C0 and C1 controls other than the whitespace handled in step 3
    (0x0000, 0x0008), (0x000E, 0x001F), (0x007F, 0x009F),
)

# A.2.4 step 3: characters treated as a space (U+000A is the line separator)
WHITESPACE = frozenset(
    "\u0009\u000B\u000C\u000D        "
    "          　"
)

LINE_BREAK = "\n"


# --------------------------------------------------------------------------
# A.2 Content text
# --------------------------------------------------------------------------

def canonical_text(html: str) -> str:
    """A.2: canonical text of the document content."""
    document = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=False)
    segments: list[str] = []
    for root in _content_roots(document):
        segments.append(LINE_BREAK)
        _collect(root, segments)
        segments.append(LINE_BREAK)
    return normalise_text("".join(segments))


def normalise_text(raw: str) -> str:
    """A.2.4: normalisation of the extracted text."""
    # Step 1: remove invisible and control characters
    without_invisible = "".join(ch for ch in raw if not _is_invisible(ord(ch)))
    # Step 2: Unicode Normalization Form C
    composed = unicodedata.normalize("NFC", without_invisible)
    # Step 3: whitespace to U+0020
    spaced = "".join(" " if ch in WHITESPACE else ch for ch in composed)
    # Step 4: collapse runs of spaces, trim lines, drop empty lines
    lines = (" ".join(word for word in line.split(" ") if word) for line in spaced.split(LINE_BREAK))
    return LINE_BREAK.join(line for line in lines if line)


def content_hash(html: str) -> str:
    """A.3: "sha256:" followed by the lowercase hex SHA-256 of the canonical text."""
    return "sha256:" + hashlib.sha256(canonical_text(html).encode("utf-8")).hexdigest()


def _content_roots(document: Any) -> list[Any]:
    """A.2.1: marked regions, else the first main element, else body."""
    marked = [el for el in _elements(document) if CONTENT_ROOT_ATTRIBUTE in el.attrib]
    if marked:
        nested = {descendant for el in marked for descendant in el.iter() if descendant is not el}
        return [el for el in marked if el not in nested]
    for name in ("main", "body"):
        found = next((el for el in _elements(document) if _local_name(el) == name), None)
        if found is not None:
            return [found]
    return [document]


def _collect(element: Any, segments: list[str], in_pre: bool = False) -> None:
    """A.2.2 and A.2.3: depth-first walk in document order.

    Line breaks come from structure only. A line feed inside a text node is
    whitespace, except within a pre element, where it separates lines.
    """
    if not isinstance(element.tag, str) or _is_excluded(element):
        _append(segments, element.tail, in_pre)
        return

    name = _local_name(element)
    inside_pre = in_pre or name == "pre"
    is_block = name in BLOCK_ELEMENTS
    if is_block:
        segments.append(LINE_BREAK)
    if name == "br":
        segments.append(LINE_BREAK)
    elif name == "img":
        _append(segments, element.attrib.get("alt"), inside_pre)

    _append(segments, element.text, inside_pre)
    for child in element:
        _collect(child, segments, inside_pre)

    if is_block:
        segments.append(LINE_BREAK)
    _append(segments, element.tail, in_pre)


def _is_excluded(element: Any) -> bool:
    return (
        _local_name(element) in EXCLUDED_ELEMENTS
        or "hidden" in element.attrib
        or element.attrib.get("aria-hidden", "").lower() == "true"
        or IGNORE_ATTRIBUTE in element.attrib
    )


def _local_name(element: Any) -> str:
    """Element name without namespace: the parser puts SVG and MathML in their own."""
    return element.tag.rsplit("}", 1)[-1]


def _append(segments: list[str], text: str | None, in_pre: bool) -> None:
    if text:
        segments.append(text if in_pre else text.replace(LINE_BREAK, " "))


def _is_invisible(code_point: int) -> bool:
    return any(low <= code_point <= high for low, high in INVISIBLE_RANGES)


def _elements(document: Any) -> Iterator[Any]:
    root = document.getroot() if hasattr(document, "getroot") else document
    return (el for el in root.iter() if isinstance(el.tag, str))


# --------------------------------------------------------------------------
# A.4 Record canonicalisation (JCS, RFC 8785, restricted to integers)
# --------------------------------------------------------------------------

MAX_SAFE_INTEGER = 2**53 - 1


def canonical_record(record: dict[str, Any]) -> bytes:
    """A.4: JCS serialisation of the record without its top-level "signature"."""
    unsigned = {key: value for key, value in record.items() if key != "signature"}
    return _jcs(unsigned).encode("utf-8")


def _jcs(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise ValueError(f"integer outside the I-JSON range: {value}")
        return str(value)
    if isinstance(value, float):
        raise ValueError("records must not contain non-integer numbers (A.4)")
    if isinstance(value, str):
        return _jcs_string(value)
    if isinstance(value, list):
        return "[" + ",".join(_jcs(item) for item in value) + "]"
    if isinstance(value, dict):
        # Members sorted by the UTF-16 code units of their names (RFC 8785, 3.2.3)
        keys = sorted(value, key=lambda name: name.encode("utf-16-be"))
        return "{" + ",".join(_jcs_string(key) + ":" + _jcs(value[key]) for key in keys) + "}"
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


_SHORT_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _jcs_string(text: str) -> str:
    out = []
    for ch in text:
        if ch in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


# --------------------------------------------------------------------------
# A.5 Signature
# --------------------------------------------------------------------------

def sign(record: dict[str, Any], private_key: Ed25519PrivateKey, key_id: str) -> dict[str, Any]:
    """A.5.1: return the record with an Ed25519 signature object added."""
    value = private_key.sign(canonical_record(record))
    signed = dict(record)
    signed["signature"] = {
        "algorithm": "Ed25519",
        "keyId": key_id,
        "signatureValue": _base64url(value),
    }
    return signed


def verify(html: str, record: dict[str, Any], public_key: Ed25519PublicKey) -> bool:
    """A.5.2: recompute the content hash, then check the signature."""
    signature = record.get("signature")
    if not isinstance(signature, dict) or signature.get("algorithm") != "Ed25519":
        return False
    if record.get("contentHash") != content_hash(html):
        return False
    try:
        public_key.verify(_base64url_decode(signature["signatureValue"]), canonical_record(record))
    except Exception:  # cryptography raises InvalidSignature; malformed input raises others
        return False
    return True


def find_record(html: str) -> dict[str, Any] | None:
    """A.5.2 step 1: the JSON-LD object whose @context includes the vocabulary."""
    document = html5lib.parse(html, treebuilder="etree", namespaceHTMLElements=False)
    for script in _elements(document):
        if _local_name(script) != "script" or script.attrib.get("type") != "application/ld+json":
            continue
        try:
            data = json.loads(script.text or "")
        except json.JSONDecodeError:
            continue
        context = data.get("@context") if isinstance(data, dict) else None
        contexts = context if isinstance(context, list) else [context]
        if VOCABULARY in contexts:
            return data
    return None


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
