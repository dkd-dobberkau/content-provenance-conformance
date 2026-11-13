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

## Verifying a live site

`verify_site.py` walks a site's Audit Endpoint, fetches every signed document
and checks hash and signature as required by Annex A.5.2:

```bash
cd reference/python
uv run python verify_site.py https://example.org/
uv run python verify_site.py https://project.ddev.site/ --insecure   # local certificates
```

It prints one line per document (`valid`, `invalid` with a reason, or
`unsigned`) and exits with 1 if any signed document fails.

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

- Schema checks for the Audit Endpoint listing itself
- Fact addressing vectors (Layer 3)

## License

MIT. See [LICENSE](LICENSE).
