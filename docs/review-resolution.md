# W1a review resolution

The W1b hardening pass resolved all three blockers and all nine majors from the
operator review.

| Item | Resolution |
| --- | --- |
| B1 | Envelope verification now requires retained bytes, recomputes every digest, checks identity bindings, and validates ordered parent links. Wipe and mutation tests fail closed. |
| B2 | Metadata filtering is path-scoped. Nested evaluator paths such as `corpus/gold` and `corpus/hidden` are excluded without deleting legitimate source directories named `gold`, `corpus`, or `runs`. |
| B3 | Jevgrep honors valid emitted ranks, verifies duplicate/partial rank columns, and records unordered semantics instead of inventing a rank. |
| M4 | BM25 query tokens are sorted before scoring. |
| M5 | Evaluator commands run in new process groups and kill/reap descendants on timeout. |
| M6 | Upstream and hidden evaluator commands are separate inputs and are retained in the evaluator digest. |
| M7 | Hidden-test failures map to localization or incorrect-implementation classes; malformed patches, regressions, environment failures, and timeouts remain distinct. |
| M8 | Missing dollar components propagate `unknown` into combined modeled cost. |
| M9 | Runner execution persists the envelope, stage records, run record, tree digests, patch digest, and evaluator result. |
| M10 | Trace coverage is partial when session association, terminal markers, or start/end pairing are missing. |
| M11 | Resume returns a persisted run, environment failures can retry once in a new run id, and forced-first/noncompliance flags are recorded. |
| M12 | Quiescent snapshots hash three times with a settle interval between observations. |

The remaining minor items are either explicit protocol limitations or outside
the offline W1b acceptance boundary. They are not presented as validated
production isolation or live-provider claims.

## Closeout integrity review (2026-09-30) — findings + disposition

Independent adversarial review (non-authoring lane; codex `gpt-6-sol`, medium) over the
closeout revision `deba489`. Full reviewer artifact (paths sanitized):
`reports/closeout-integrity-review-20260930.md`. Verdict at review time: **RED**;
all seven findings folded the same day.

| # | Finding (severity) | Disposition | Evidence |
|---|---|---|---|
| 1 | Tracked branch carried no run evidence (BLOCKER) | FIXED — sanitized content-addressed evidence bundle committed (`reports/pilot-v1-evidence/`, 36 cells; per-file sha256 + `bundle_digest` in the manifest); the report rebuilds byte-identically from the bundle alone | manifest (`verification 36/36`); repro `report_digest` == `reports/pilot-v1.json` |
| 2 | Evaluation/cost sidecars not bound to envelopes (BLOCKER) | FIXED — `verify_run` binds `evaluation-result.json` byte-exactly to `envelope.evaluation_result_digest`; the report marks mismatched/missing artifacts ineligible and withholds its integrity claim; costs are bound by the bundle manifest (envelope v1 has no cost component — documented limitation) | `tests/test_envelope.py`, `tests/test_report_live.py` (tamper → ineligible + claim withheld) |
| 3 | Jev cash presented as metered receipts (MAJOR) | FIXED (labeling) — claim relabeled as modeled spend at the frozen measured rate; report `pricing_basis` + `limitations` added; `configs/pricing/pricing.yaml` provenance updated to the V6 credit-delta measurement; per-run receipts recorded as unavailable (account-level only) | report `spend.pricing_basis`; pricing.yaml diff |
| 4 | No per-run isolation/network probe artifacts (MAJOR) | DEFERRED with hard gate — claim-map entry withheld; limitation recorded; no holdout claim may proceed without per-run probe artifacts | report `claim_map`, `limitations` |
| 5 | `experiments/pilot.yaml` draft; blank digests (MAJOR) | FIXED — frozen; corpus-manifest / selection-log / pricing sha256 digests filled (artifacts unchanged since the corpus freeze) | pilot.yaml diff |
| 6 | Simulated detection relied on the self-reported flag (MAJOR) | FIXED — live builder also refuses on run-id/record markers; claim evidence updated; adversarial forgery rests on the envelope/bundle bindings | `test_live_report_refuses_mock_run_ids` |
| 7 | Sensitivity set excluded failed assignments (MAJOR) | FIXED — sensitivity = all assigned cells; invalidated cells count as unsuccessful with explicit `ineligible_counted` | `test_live_report_sensitivity_counts_failed_assignments` |

Additionally found and fixed while folding (not in the original findings): empty-patch runs
failed `verify_run` ("empty retained bytes") although an empty patch is a valid scored
attempt under the protocol; the verifier now accepts zero-length retained bytes exactly
when the component digest is the empty-bytes digest
(`tests/test_envelope.py::test_empty_patch_component_verifies`).

## Closeout integrity review — round 2 re-review (2026-09-30)

Same independent lane, frozen revision `4ad67e6` (scope: verify the round-1 fold, items 1–7).
Result: **six PASS; one FIX-FIRST** — item 3 (labeling): `docs/accounting.md` still described
Jev cash as metered/receipt-reconciled while the report labels it modeled. Reviewer artifact:
`reports/closeout-integrity-review-r2-20260930.md`. The wording is fixed across
`docs/accounting.md`, `docs/spend-projection.md`, `docs/result-interpretation.md`, and the
README invalidation list.

The same delta also carries two non-review additions made while building the retrieval-only
evidence: the pinned-jg 0.4.3 CLI adapter contract fix (`retrieval/jevgrep.py` — real text
grammar + `--no-cache`, with captured-output fixtures; the previous `search --json --limit`
shape does not exist in the pinned CLI) and the retrieval-only artifact/tool
(`reports/retrieval-only-v1.json`, `tools/retrieval-only-pass.py`). A round-3 delta re-check
covers this fix and these additions.
