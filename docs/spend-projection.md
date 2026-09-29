# Spend projection — Stage 0.5 V7 (2026-09-29)

All amounts USD. Anchors are **live-measured** (receipts retained in the V6 evidence set),
not modeled. This document feeds the pilot/holdout drafts and the ledger reservation policy.

## Measured anchors

| anchor | value | source |
|---|---|---|
| jg cold search (8.2 MB repo) | **≈ $0.046** (n=4: $0.0455–0.0478) | gateway `/v1/credits` `total_used` deltas, V6 |
| jg cached rerun (same question) | ≈ $0.0003 (0.6 %) | V6 |
| jg reservation rate | **$0.048 / search** (rounded up) | V6 |
| codex runs | subscription quota (tokens), not cash | `codex_quota_tokens` column |
| bm25 / evaluator | local compute (`local_compute_wall_s`), $0 | — |

Notes: the V1 synthetic probe ($0.000116) is **superseded** — it under-measured by ~400×.
`--max-source-bytes` is NOT a cost lever (bounded vs unlimited: $0.0460 vs $0.0455, V6);
cache only helps identical queries, and scored runs use distinct questions ⇒ cold pricing.

## Stage projections (jg searches × $0.048)

Searches-per-agent-run is agent-chosen: expected band **2 avg**, reservation cap **6**.

| stage | jg runs | searches (exp / cap) | jg $ (exp / cap) | allocation |
|---|---|---|---|---|
| Stage 1 retrieval-only | 25 tasks × 1 query | 25 / 25 | $1.20 / $1.20 | $3 |
| Pilot (12 × A1) | 12 | 24 / 72 | $1.15 / $3.46 | $10 |
| Holdout (24 × A1 × 2 reps) | 48 | 96 / 288 | $4.61 / $13.82 | $30 |
| Diagnostics (8 × A2) | 8 | 16 / 48 | $0.77 / $2.30 | contingency $5 |
| **total (incl. Stage-0.5 spend $0.2024)** | | | **≈ $7.9 / ≈ $21.0** | $50 cap |

Both bands fit: expected ≈ 16 % of cap, worst-cap ≈ 42 % of cap. If the holdout pool stays at
the currently admitted 10 tasks, holdout jg ≈ $1.92 / $5.76.

## Decisions

- **Pilot repetitions = 1** (screen; 12 × 3 arms = 36 agent runs).
- **Holdout repetitions = 2** (paired design; within-task variance estimate; marginal jg cost
  +$2.3 expected / +$6.9 worst fits the $30 allocation).
- **Reservation policy (fail-closed, existing `SpendLedger` semantics):** before each agent run
  in a jg-enabled arm, reserve `6 × $0.048 = $0.288` (`rate_source` = `LIVE-MEASURED (V6
  2026-09-29; n=4; gateway /v1/credits)`). After the run, reconcile with
  `observed jg events × $0.048`; periodic gateway-delta spot checks are the receipt trail.
  Missing receipt or ambiguous rate ⇒ ledger stops (existing behavior).
- Codex usage is accounted in `codex_quota_tokens` per run (from the frozen trace contract);
  `codex_listprice_modeled_usd` is a separate modeled column and never claimed as observed.

## Drafts

`experiments/pilot.yaml` + `experiments/holdout.yaml` — DRAFT status; corpus digests and the
pricing snapshot are filled at corpus freeze (no post-performance swaps).
