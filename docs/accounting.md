# Accounting

The ledger is the cap enforcement point. It reserves the worst-case bound
before a metered call, reconciles afterward against counted executed searches at
the frozen measured per-search rate, and stops on a missing rate source,
ambiguous rate, or insufficient headroom. Provider gateways expose account-level
totals only; per-run dollar figures that cannot be receipt-reconciled are labeled
**modeled** and never presented as metered receipts.

## Named columns

- `jev_cash_usd`: modeled provider cash (executed-search count × frozen measured
  rate; per-run provider receipts unavailable — account-level totals only).
- `codex_quota_tokens`: subscription resource use, not dollars.
- `codex_listprice_modeled_usd`: a separate modeled comparison.
- `local_compute_wall_s`: local elapsed compute.
- `combined_variable_modeled_usd`: the labeled sum of named dollar components.

There is no unqualified aggregate cost field. Cost per success is computed
for each named column over all attempted tasks in that column. A zero-success
denominator is `NA`.

Missing usage is `unknown`, never zero. A byte-only estimate is labeled
`MODEL`; it propagates `unknown` into combined dollar fields and cannot support
an observed-savings claim. Pricing entries retain effective date, source,
retrieval time, model, and service-tier notes.

The W1a defaults allocate 2 dollars to Stage 0.5, 3 to retrieval-only, 10 to
the pilot, 30 to the first complete holdout triplets, and 5 to contingency.
Mock paths are protocol demonstrations and consume no live budget.

Attribution: the accounting policy shape is adapted from the public upstream
`evals/accounting.md` and `evals/results/total-cost-2026-09-28.md` pattern.
