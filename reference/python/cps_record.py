"""Reference implementation of Section 3.1: when a Provenance Record is complete.

A complete Record is what level L2 requires (Section 4). Written for clarity
rather than speed, like cps_canonical.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

VOCABULARY = "https://cms-provenance.org/ns/v1"
REQUIRED_TEXT = ("@type", "@id", "generator")
REQUIRED_DATE_TIMES = ("datePublished", "lastSubstantiveRevision")
OPTIONAL_DATE_TIMES = ("maintainedDate",)
SOURCE_MEMBERS = ("url", "name", "accessDate")
URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$")


def problems(record: dict[str, Any]) -> list[str]:
    """Why the Record is not complete; empty if it is."""
    found = []
    context = record.get("@context")
    if VOCABULARY not in (context if isinstance(context, list) else [context]):
        found.append(f"@context does not include the vocabulary {VOCABULARY}")

    for member in REQUIRED_TEXT:
        if not _text(record.get(member)):
            found.append(f"{member} is missing")
    if _text(record.get("@id")) and not URI.match(record["@id"]):
        found.append(f"@id {record['@id']!r} is not a URI")

    for member in REQUIRED_DATE_TIMES:
        if member not in record:
            found.append(f"{member} is missing")
        elif not _date_time(record[member]):
            found.append(f"{member} {record[member]!r} is not an RFC 3339 date-time")
    for member in OPTIONAL_DATE_TIMES:
        if member in record and not _date_time(record[member]):
            found.append(f"{member} {record[member]!r} is not an RFC 3339 date-time")

    found.extend(_author_problems(record.get("author")))
    found.extend(_source_problems(record.get("citation", [])))
    return found


def _author_problems(authors: Any) -> list[str]:
    if isinstance(authors, dict):
        authors = [authors]
    if not isinstance(authors, list) or not authors:
        return ["author is missing: at least one author is required"]
    found = []
    for position, author in enumerate(authors, start=1):
        identifier = author.get("@id") if isinstance(author, dict) else None
        if not _text(identifier):
            found.append(f"author {position} has no @id")
        elif not URI.match(identifier):
            found.append(f"author {position} @id {identifier!r} is not a URI")
    return found


def _source_problems(sources: Any) -> list[str]:
    if isinstance(sources, dict):
        sources = [sources]
    if not isinstance(sources, list):
        return ["citation is neither a source nor a list of sources"]
    found = []
    for position, source in enumerate(sources, start=1):
        for member in SOURCE_MEMBERS:
            if not _text(source.get(member) if isinstance(source, dict) else None):
                found.append(f"source {position} has no {member}")
        access_date = source.get("accessDate") if isinstance(source, dict) else None
        if _text(access_date) and not _date(access_date):
            found.append(f"source {position} accessDate {access_date!r} is not an RFC 3339 date")
    return found


def _text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _date_time(value: Any) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return len(value) == 10
