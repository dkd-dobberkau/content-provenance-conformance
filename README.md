# Content Provenance conformance suite

Test material for implementations of the
[Content Provenance Specification](https://github.com/dkd-dobberkau/content-provenance-spec).

## Contents

| Path | What it is |
| --- | --- |
| `vectors/canonicalization/` | Test vectors for Annex A: canonical text, content hash, canonical Record and Ed25519 signature |
| `vectors/keys/test-key.json` | The Ed25519 test key from RFC 8032, section 7.1, TEST 1. Public; never use it for real content |
| `reference/python/` | Reference implementation of Annex A, written for clarity rather than speed |

Each vector directory contains:

- `input.html`: the published page
- `expected-text.txt`: the canonical text, **written by hand** from the rules in Annex A.2
- `record.json`: the provenance record before signing
- `expected.json`: `contentHash`, the canonical Record (JCS), its SHA-256, and the signed Record

An implementation conforms to Annex A if it reproduces every
`expected-text.txt` and every value in `expected.json`.

## Running the reference tests

```bash
cd reference/python
uv sync
uv run pytest
```

The tests check the reference implementation against the hand-written texts,
cross-check record canonicalisation against an independent JCS library, verify
every signed record against its page, and make sure that a changed page or a
changed record fails verification.

After changing a vector input, regenerate the stored results with
`uv run python vectors.py` and review the diff.

## Planned

- Audit Endpoint checks (Layer 4) that fetch `/.well-known/content-provenance`
  from a live site
- Fact addressing vectors (Layer 3)

## License

MIT. See [LICENSE](LICENSE).
