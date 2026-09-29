# jevgrep-eval

Offline engine for a reproducible benchmark of code localization and task
completion. The research question is whether making Jevgrep available changes
Codex Luna's work on unfamiliar small and medium open-source repositories,
relative to native `rg`/`grep`/`find`/read and a deterministic in-repository
BM25 retriever.

## W1b status

The offline W1b batch includes the frozen public corpus, exact-SHA admission
evidence, evaluator-only gold and hidden-test artifacts, manifest digests,
leakage checks, separate upstream/hidden evaluation, and a labeled mock report.
It does not include credentials, provider data, or a live install receipt.

The frozen corpus has 56 candidates and 22 admitted tasks. Dev has 12 admitted
Python tasks. Holdout has 41 candidates and 10 admitted JavaScript/TypeScript
tasks because the staged offline caches could not support the remaining
candidates. Rejected candidates and infrastructure reasons remain auditable;
they are not scored.

The primary arms are:

- A0: native search only.
- A1: Jevgrep available.
- A3: deterministic BM25 available.

A2 and A4 are forced-first diagnostics. A6 supplies pre-base, paths-only
localization hints. A5 is deferred. No arm makes a production retrieval-policy
claim.

## Offline quickstart

The default engine path is offline and mock-only:

```bash
UV_OFFLINE=1 uv sync --frozen
uv run pytest -q
uv run ruff check .
```

Use `jevgrep-eval --help` for manifest, materialization, retrieval, scoring,
statistics, costing, ledger, report, and probe commands. Validate the committed
corpus with `uv run python -c 'from pathlib import Path; from jevgrep_eval.corpus import validate_manifest; validate_manifest(Path("corpus"))'`.
Mock outputs are explicitly labeled `simulated-fixture` and `protocol
demonstration`. They exercise mechanics and are never evidence of retriever or
model quality.

## Live boundary and limitations

Live Codex or Jevgrep execution requires explicit policy flags and later
Stage 0.5 verification. Credentials and provider responses are never stored
in this public repository. Tier B retains provider-scoped network access and
therefore carries a documented residual egress risk. Tier A recipes are
generated here but must be validated on the target host before any claim.

Results are task-clustered and paired. Timeouts count as failures. Partial
traces, missing receipts, workspace leaks, and failed isolation probes
invalidate the affected primary measurement while retaining its audit trail.
This is a research instrument, not a production search recommendation.

Review resolution, corpus admission details, and demo provenance are documented
in `docs/review-resolution.md`, `docs/corpus.md`, and `docs/demo.md`.
