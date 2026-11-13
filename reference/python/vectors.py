"""Builds the expected results of the canonicalisation vectors.

Run `uv run python vectors.py` after changing a vector input; the tests then
check that the stored results are reproducible.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import cps_canonical

VECTORS = Path(__file__).resolve().parents[2] / "vectors"
CANONICALIZATION = VECTORS / "canonicalization"


def test_key() -> tuple[Ed25519PrivateKey, str, str]:
    key = json.loads((VECTORS / "keys" / "test-key.json").read_text())
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key["privateKeySeedHex"]))
    return private_key, key["keyId"], key["publicKeyHex"]


def vector_dirs() -> list[Path]:
    return sorted(path for path in CANONICALIZATION.iterdir() if path.is_dir())


def expected_result(vector: Path) -> dict[str, Any]:
    html = (vector / "input.html").read_text(encoding="utf-8")
    record = json.loads((vector / "record.json").read_text(encoding="utf-8"))
    record["contentHash"] = cps_canonical.content_hash(html)
    canonical = cps_canonical.canonical_record(record)
    private_key, key_id, _ = test_key()
    return {
        "contentHash": record["contentHash"],
        "canonicalRecord": canonical.decode("utf-8"),
        "canonicalRecordSha256": hashlib.sha256(canonical).hexdigest(),
        "signedRecord": cps_canonical.sign(record, private_key, key_id),
    }


def write_all() -> None:
    for vector in vector_dirs():
        result = json.dumps(expected_result(vector), indent=2, ensure_ascii=False) + "\n"
        (vector / "expected.json").write_text(result, encoding="utf-8")
        print(f"wrote {vector.name}/expected.json")


if __name__ == "__main__":
    write_all()
