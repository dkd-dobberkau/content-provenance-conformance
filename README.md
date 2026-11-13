# Content Provenance conformance suite

Test material for implementations of the
[Content Provenance Specification](https://github.com/dkd-dobberkau/content-provenance-spec).

## Contents

| Path | What it is |
| --- | --- |
| `vectors/canonicalization/` | Test vectors for Annex A: canonical text, content hash, canonical Record and Ed25519 signature |
| `vectors/facts/` | Test vectors for Section 3.3: Facts in the Record, their fragment elements and the Web Annotation of each Fact |
| `vectors/keys/test-key.json` | The Ed25519 test key from RFC 8032, section 7.1, TEST 1. Public; never use it for real content |
| `schemas/audit-endpoint.schema.json` | JSON Schema (2020-12) of the Audit Endpoint listing, its Document entries and the key resources (Section 3.4) |
| `reference/python/` | Reference implementation of Annex A, written for clarity rather than speed, and the site checks below |

Each vector directory contains:

- `input.html`: the published page
- `expected-text.txt`: the canonical text, **written by hand** from the rules in Annex A.2
- `record.json`: the provenance record before signing
- `expected.json`: `contentHash`, the canonical Record (JCS), its SHA-256, and the signed Record

An implementation conforms to Annex A if it reproduces every
`expected-text.txt` and every value in `expected.json`.

Each Fact vector directory contains:

- `input.html`: a published page whose Record lists Facts under `claim`
- `plain.html`: the same page without the fragment elements; its canonical
  text must equal that of `input.html` (wrapping a Fact must not change it)
- `expected.json`, **written by hand**: the Document URL, the text of each
  `fact-{id}` element and the Web Annotation for each Fact. Members that
  Section 3.3 leaves to the implementation, such as `created`, are not listed.

`03-unwrapped-quote` has a Fact whose words are not wrapped and span inline
markup; the TextQuoteSelector still identifies it.

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

## Checking an Audit Endpoint

`check_endpoint.py` checks the Audit Endpoint itself against Section 3.4:

```bash
cd reference/python
uv run python check_endpoint.py https://example.org/
```

It validates every listing page, the key list and each key resource against
`schemas/audit-endpoint.schema.json`, follows the `Link` headers and checks
what a schema cannot express: page numbers, `totalItems` against the listed
documents, duplicate identifiers, `Access-Control-Allow-Origin: *`, private key
members in a JWK and that every `keyId` used in a signature is published.
It prints one line per finding and exits with 1 if there is any.

The schema can be used on its own with any JSON Schema validator. The listing
is the root schema; key list and key entry are `#/$defs/keyList` and
`#/$defs/keyEntry`.

## Checking the Facts of a site

`check_facts.py` walks the Audit Endpoint and checks every Fact in the listed
Documents against Section 3.3: the Fact URI, the quoted words in the
canonical text, the `fact-{id}` element, and the Web Annotation served for the
Fact, compared with the one `cps_facts.py` builds. Additional annotation
members are allowed.

```bash
uv run python check_facts.py https://example.org/
```

Run all three tools to test an implementation: `check_endpoint.py` for the
shape of the endpoint, `verify_site.py` for the signatures and
`check_facts.py` for the Facts.

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

- A single check that reports the conformance level a site reaches (L1 to L4)

## License

MIT. See [LICENSE](LICENSE).
