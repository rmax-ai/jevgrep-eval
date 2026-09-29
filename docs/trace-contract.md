# Trace contract

The parser consumes a codex-style JSONL fixture shape. Unknown top-level event
types and line-parse failures are retained as named partial coverage, never
silently discarded. A live provider probe is still required before making a
live holdout claim.

## Normalized event

Each tool event has an ordered `seq`, `kind` (`read`, `search_native`,
`search_jg`, `search_bm25`, `edit`, `test`, or `other_shell`), private
`cmd_digest`, redacted `cmd_scrubbed`, redaction version, timestamp offset,
touched files, and a result summary. Raw command bytes remain in the private
run artifact; only the rendering is publishable.

Coverage is `full` only when every line parses, session association is known,
and start/end pairing is complete. Otherwise the run is `partial` with named
missing dimensions. Dependent metrics are indeterminate.

## Derived metrics

The engine derives first discovery operation, path exposure, content exposure
(primary), direct read, calls to first gold, tokens before first edit,
non-reference operations and unique files, specialized query count, repeated
searches, and fallback calls. Fallback is split after successful specialized
responses versus empty/error responses. Compound or concurrent discovery is
marked `indeterminate`.

The exact provider schema and command grammar remain a live-probe
reconciliation item. The committed mock protocol demonstrates the normalized
contract without claiming provider compatibility.
