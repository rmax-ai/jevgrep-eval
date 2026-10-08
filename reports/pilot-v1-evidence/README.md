# Pilot evidence bundle (`pilot-v1-evidence`)

Sanitized, content-addressed copy of the 36 pilot run bundles that back
`reports/pilot-v1.json`. One directory per cell, mirroring the `runs/` layout:

- `run-record.json` — run record (status, flags, coverage, events)
- `evaluation-result.json` — evaluator outcome (when an evaluation ran)
- `costs.json` — per-run cost columns (when recorded)
- `run-envelope.json` — evidence chain (digest links over all stages)
- `ledger.json` — spend ledger snapshot (metered cash rail)

`manifest.json` carries, per cell: the `sha256` and byte size of every bundled
file, the `verify_run` result over the original run directory, and the cell's
task/arm/terminal status; plus `bundle_digest` over the manifest itself.

## Sanitization

Host-home path strings and remaining host-user identifier fragments were redacted
to a `<host-home>` placeholder. The build
fails closed if any bundled file still contains a host-home path, a known
internal placeholder token, a user identifier, a scratch-directory path, or
provider-session vocabulary. No digest-bearing field is textual, so the
recorded digests are unaffected by redaction.

## Verification

- `verify_run` (envelope chain + record identity + evaluation sidecar binding)
  results are recorded per cell in `manifest.json` -> `cells.*.verification`.
  Cells whose records predate the evaluation-sidecar binding (or that carry no
  evaluation by design) are reported with their exact error list.
- The report rebuilds byte-identically from this bundle: copy the cell
  directories and `ledger.json` into a `runs/` directory, then
  `uv run jevgrep-eval report build --runs <dir> --corpus corpus`
  and compare `report_digest` with `reports/pilot-v1.json`.
- `bundle_digest` recomputes from `manifest.json` alone:
  `jevgrep_eval.util.digest(<manifest with an empty digest value>,
  component="pilot-evidence-bundle")` (canonical JSON, sha256).

Raw agent streams, workspaces and rollout logs are intentionally not included
(size); they remain host-side audit artifacts.
