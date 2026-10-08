# Closeout integrity review — round 2 re-review (dq#117)

**Verdict: FIX-FIRST.** Re-verification of the round-1 fold; item 3 required a fix
(accounting wording described Jev cash as metered/receipt-reconciled while the report
labels it modeled). All other items PASS. Reported paths are repository-relative.

Frozen revision reviewed: `4ad67e6`.

| item | result | direct evidence |
| --- | --- | --- |
| 1 — bundle | PASS | `reports/pilot-v1-evidence/` has 36 cell directories, ledger, manifest, and README; all 143 listed cell-file SHA-256 values and sizes match, as does the ledger hash and size. Manifest `totals.verification_ok: 36`; 146 bundle files are tracked. A rebuild from a disposable bundle copy produced `report_digest` `970e1f3c77eda0d41f3f0f8adf5a7602c0f9fc0b59a8ed35807897e0c52d87ed`, equal to `reports/pilot-v1.json`. |
| 2 — sidecar binding | PASS | Disposable copy of `jinja-1852-a1-r0`: unmutated `verify_run` → `valid=True`, errors `[]`; after one byte changed in `evaluation-result.json` → `valid=False`, errors `['retained artifact digest mismatch: evaluation-result.json']`. |
| 3 — Jev labeling | **FIX-FIRST** | Report claim: “Jev provider spend is included in the cost columns (modeled from executed-search counts at the frozen measured rate)”; `spend.pricing_basis` gives `0.048`/search, V6 credit-delta measurement, and unavailable per-run receipts. Pricing config also says “Modeled per-search rate.” But `docs/accounting.md` still says the ledger “reconciles an auditable receipt afterward” and defines `jev_cash_usd` as “metered provider cash.” Those unqualified statements still overclaim the pilot's per-run Jev cash evidence. |
| 4 — probes | PASS (withheld) | Claim map: `"claim":"per-run isolation and network probe artifacts","status":"withheld"`; reason says “per-run probe artifacts are required before any holdout claim.” Limitation: “per-run isolation/network probe artifacts were not emitted in the pilot (recipe-level validation only); holdout runs must emit them”. |
| 5 — freeze | PASS | `experiments/pilot.yaml` says `status: frozen`. Tracked and recomputed SHA-256 agree: corpus manifest `4a6cb396ebc9f7fd4733721fea3f435762e06cc0c423ed501422bbe0b8c4f9ec`; selection log `b0fe16639f2ae572a403f444fb3e8b2ff52755b05f92fa99a8c86a7493713608`; pricing `242d7cad6051a03ad435404e4dde24c909c60f6abae61fdeb5ca1950756b9010`. |
| 6 — simulated | PASS (specified check) | `build_live_report` refuses `simulated-fixture` flags, `"mock"` in the run ID, or truthy `record.simulated`; `test_live_report_refuses_mock_run_ids` covers an unflagged mock ID. |
| 7 — sensitivity | PASS | Both `sensitivity_all_assigned` comparisons carry `ineligible_counted: 0` in the pilot report. `report.py` documents invalidated assigned cells as unsuccessful in the sensitivity denominator, with `ineligible_counted` exposing the count; `test_live_report_sensitivity_counts_failed_assignments` checks an `env_failure` cell gives `ineligible_counted == 1` and estimate `-1.0`. |

Bonus: PASS. A disposable copy of empty-patch `jinja-1665-a0-r0` returns `verify_run` `valid=True`, errors `[]`.

## Explicitly unverified

- No pytest or ruff run in this review (host reported 114 passing and ruff clean). No agent execution or hidden-test replay.
- No independent per-run provider receipts or credit history; modeled Jev cash was checked for labeling, not actual billed cash.
- No per-run isolation/network probe artifacts; holdout gate remains open.
