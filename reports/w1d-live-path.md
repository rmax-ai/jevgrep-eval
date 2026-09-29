# W1d verified live path

Implemented the opt-in live Codex runner with a pure dry-run planner,
validated Tier-B bubblewrap argv, empty child environments, per-run Codex
homes, offline workspace preparation, optional BM25 staging, and fail-closed
Jevgrep budget reconciliation. Added focused tests for dry-run purity,
budget gating, task/evaluator loading, prompt construction, and host bindings.

Validation:

- `UV_OFFLINE=1 uv sync --frozen` — passed.
- `uv run pytest -q` — 75 passed.
- `uv run ruff check .` — clean.
- The required `run --live --dry-run ...` command — passed and emitted a
  complete plan without creating `runs/`.

No network, Codex, or bubblewrap execution is used by the tests. TypeScript
repository dependency preparation is out of scope for this batch; the pilot
tasks are Python repositories.
