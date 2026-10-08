# Closeout integrity review — round 6 delta re-check (dq#117 revision)

**Verdict: FIX-FIRST.** Local adversarial delta review of the dq#117 evidence revision
(`21e2a0a..767e2d2`). Item 5 required a fix: the rebuilt report's `claim_map`/`limitations`
omitted the statement that the affected A0/A3 cells were regenerated under the corrected
environment (the statement existed only in `docs/review-resolution.md`). All other items
PASS. Reported paths are repository-relative.

Frozen revision reviewed: `767e2d2`. Lane: codex `gpt-6-sol`, medium (scope: revision delta).
Fold: `4adfe41` (statement declared as a report limitation; report rebuilt; digest reference
refreshed).

| Item | Result | Direct evidence quotes |
|---|---|---|
| 1. Arm-scoped capability | PASS | `jg = _condition_has(condition, "jg")`; `tools = condition.get("retrieval_tools", [])`; `return isinstance(tools, list) and tool in tools`; `if jg_enabled:` / `mounts.append((node, node))`; `(f"{node}/bin/node", f"{node}/bin/node")`; `f"{node}/lib/node_modules/@openai/codex"`; `"../lib/node_modules/@openai/codex/bin/codex.js"`; `_ro_bind(argv, resolved["provider_credentials"], "/codex-home/.config/jevgrep")`; `if jg_enabled` / `else ""`. |
| 2. Deterministic pins and permitted tests | PASS | `assert (node, node) not in without_targets`; `assert (credentials, "/codex-home/.config/jevgrep") in with_targets`; `assert "OK jg unresolved; credentials absent" in no_jg`; `assert "OK jg resolvable; credentials present" in with_jg`; `assert "[features.network_proxy.domains]" not in plain`. `............. [100%]` / `13 passed in 0.46s`. |
| 3. In-sandbox probe transcript | PASS | `[non-jg:probe] rc=0` / `stdout: arm-isolation: OK jg unresolved; credentials absent`; `[non-jg:codex-version] rc=0` / `stdout: codex-cli 0.157.1`; `[jg:probe] rc=0` / `stdout: arm-isolation: OK jg resolvable; credentials present`; `PROBE-RESULT: ALL PASS`; `if command -v jg >/dev/null 2>&1; then`; `if [ -e /codex-home/.config/jevgrep/credentials.json ]; then`; `if ! command -v jg >/dev/null 2>&1; then`; `if [ ! -e /codex-home/.config/jevgrep/credentials.json ]; then`. |
| 4. Regenerated bundle and report rebuild | PASS | `cell_dirs 36`; `{'cells': 36, 'verification_failed': [], 'verification_ok': 36}`; six per-file checks: `click-3533-a0-r0`, `click-3818-a3-r0`, `jinja-1665-a0-r0`, `jinja-1665-a3-r0`, `click-3533-a1-r0`, `jinja-1665-a1-r0`: `costs.json:True,evaluation-result.json:True,run-envelope.json:True,run-record.json:True`. `bundle_digest f640d6c6f86057633bc45c8226583f2088342f2a356548b5495f617182beb2ad match True`; `report_build_exit 0`; `byte_identical True bytes 25463 25463`; `report_digest 2ba59b2481d7bd4c44b1d512d0bd0725c1a5c93a08f9e1596a2552f6713b495c match True`. `a0a3 manifest statuses Counter({'completed': 22, 'timeout': 2})`; both timeout records: `flags ['trace-partial'] trace_coverage partial jev_cash_usd 0.000`; `a0a3 24 checked`. |
| 5. Report claims and delta containment | FIX-FIRST | `claim_map limitations regenerated False`; `"claim_map": claims`; `"limitations": [`; `Regenerated affected pilot cells (a0/a3 × 12 dev tasks) under the corrected environment` (review-resolution only); `old claims` and current `claim_map`: same seven claim labels and statuses; `old limitations` and current `limitations`: same four entries; `a1 manifest 12`; `git diff --name-only 21e2a0a..HEAD -- reports/pilot-v1-evidence/'*a1*'`: empty; `M configs/isolation/tier_b.yaml`; `A reports/arm-isolation-probe-20261002.txt`; `A src/jevgrep_eval/proc.py`; `M tests/test_runner_terminals.py`; `M reports/pilot-v1.json`; `M reports/pilot-v1-evidence/manifest.json`; `M docs/review-resolution.md`. |

## Explicitly unverified

- `per-run isolation/network probe artifacts were not emitted in the pilot (recipe-level validation only); holdout runs must emit them`.
- `Raw agent streams, workspaces and rollout logs are intentionally not included (size); they remain host-side audit artifacts.`
- `Battery: 123 tests OK; ruff clean` is a committed documentation claim; this review ran only the permitted `13 passed in 0.46s` subset. The two new timeout regressions were read but not run.
- No live runs, `jg`, provider commands, or full suite were executed in this review.
