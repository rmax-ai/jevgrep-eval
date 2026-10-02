"""Deterministic report builders with strict simulated/live separation.

Two builders exist and they are mutually exclusive by construction:

* ``build_demo_report`` renders mechanics demonstrations and refuses any run
  that is not a mock/simulated fixture.
* ``build_live_report`` renders the paired live pilot evidence and refuses any
  run that carries the ``simulated-fixture`` marker.

The live builder encodes the frozen analysis rules: admission-rejected tasks
are never eligible for scoring; timeouts count as failures; partial trace
coverage suppresses trace-derived metrics only; cells invalidated by protocol
flags are retained as audit artifacts but excluded from the comparisons; and
every headline claim carries its run-id / digest-chain prerequisites, or is
explicitly withheld with a reason (claim map, plan §14).
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from .stats import clustered_bootstrap, exact_mcnemar
from .traces import count_search_invocations
from .util import canonical_json, digest, sha256_file

LIVE_REPORT_VERSION = "pilot-report-v1"
PRIMARY_ARMS = ("a0", "a1", "a3")
PRIMARY_COMPARISONS = (("a1", "a0"), ("a3", "a0"))
BOOTSTRAP_REPS = 10_000
BOOTSTRAP_SEED = 0  # pre-registered; do not change without a new protocol ID
# Frozen measured Jev rate (V6 live credit-delta, n=4, 2026-09-29). The provider
# gateway exposes account-level totals only, so per-run cash is modeled from
# executed-search counts at this rate; the report labels it accordingly.
JEV_RATE_USD_PER_SEARCH = "0.048"
ELIGIBLE_STATUSES = ("completed", "timeout")
INVALIDATING_FLAGS = ("pre-snapshot-mutated",)
SIMULATED_FLAG = "simulated-fixture"
REQUIRED_CORPUS_NOTE = "live report requires the corpus admission records"


class ReportRefusal(PermissionError):
    """A report cannot be built under the publication honesty rules."""


def _load_run(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid run artifact {path}: {exc}") from exc


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return _load_run(path)


def build_demo_report(
    runs_dir: Path,
    destination: Path,
    *,
    run_ids: list[str] | None = None,
) -> bytes:
    """Build a byte-stable protocol demonstration report.

    Every selected run must carry a simulated marker.  This function never
    converts live evidence into a demo artifact.
    """
    destination_resolved = destination.resolve()
    run_paths = [
        path
        for path in sorted(runs_dir.glob("**/*.json"))
        if path.resolve() != destination_resolved
    ]
    if run_ids is not None:
        wanted = set(run_ids)
        run_paths = [path for path in run_paths if path.stem in wanted or path.parent.name in wanted]
    rows: list[dict[str, Any]] = []
    for path in run_paths:
        row = _load_run(path)
        run_id = str(row.get("run_id", path.stem))
        marker = str(row.get("simulated", row.get("label", "")))
        if "mock" not in run_id.lower() and "simulated-fixture" not in marker:
            raise ReportRefusal(f"demo builder refuses non-mock run: {run_id}")
        rows.append(row)
    payload = {
        "title": "jevgrep-eval protocol demonstration",
        "label": "simulated-fixture",
        "honesty": "Mock outputs are mechanics drivers, never retriever or model quality evidence.",
        "runs": rows,
        "report_digest": "",
    }
    payload["report_digest"] = digest(payload, component="demo-report")
    content = canonical_json(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return content


def _admission_status(corpus_dir: Path, task_id: str) -> str | None:
    task_file = corpus_dir / "tasks" / task_id / "task.yaml"
    if not task_file.is_file():
        return None
    try:
        body = yaml.safe_load(task_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid task file {task_file}: {exc}") from exc
    value = body.get("admission_status")
    return str(value) if value is not None else None


def _cost_bucket(costs: dict[str, Any] | None) -> dict[str, Any]:
    costs = costs or {}
    return {
        "jev_cash_usd": costs.get("jev_cash_usd"),
        "codex_quota_tokens": costs.get("codex_quota_tokens"),
        "local_compute_wall_s": costs.get("local_compute_wall_s"),
    }


def _cell(run_dir: Path, record: dict[str, Any]) -> dict[str, Any]:
    run_id = str(record["run_id"])
    task_id = str(record["task_id"])
    arm = str(record.get("condition_id") or record.get("arm") or "unknown")
    repetition = int(record.get("repetition", 0))
    status = str(record.get("terminal_status"))
    flags = [str(flag) for flag in (record.get("flags") or [])]
    coverage = str(record.get("trace_coverage") or "unknown")
    evaluation = _load_optional_json(run_dir / "evaluation-result.json")
    costs = _load_optional_json(run_dir / "costs.json")

    notes: list[str] = []
    invalid_reasons: list[str] = []
    if status not in ELIGIBLE_STATUSES:
        invalid_reasons.append(f"terminal_status:{status}")
    for flag in INVALIDATING_FLAGS:
        if flag in flags:
            invalid_reasons.append(f"flag:{flag}")
    if evaluation is None:
        if status == "completed":
            invalid_reasons.append("missing-evaluation")
        elif status == "timeout":
            notes.append("timeout-without-evaluation (counts as failure)")
    raw_success: bool | None = None
    if evaluation is not None:
        raw_success = bool(evaluation.get("task_success"))
    effective_success = raw_success is True and status == "completed"
    if status == "timeout" and raw_success is True:
        notes.append(
            "evaluation passed but the run exceeded the time budget; "
            "timeout counts as failure per protocol"
        )
    if coverage == "partial":
        notes.append("partial trace coverage: trace-derived metrics suppressed")
    jev_searches: int | None = None
    if arm == "a1" and coverage == "full":
        jev_searches = count_search_invocations(record.get("events") or [])
    envelope = _load_optional_json(run_dir / "run-envelope.json")
    evaluation_digest_checked = False
    evaluation_digest_match: bool | None = None
    if envelope is not None:
        expected = str(envelope.get("evaluation_result_digest") or "")
        if expected:
            evaluation_digest_checked = True
            artifact = run_dir / "evaluation-result.json"
            if not artifact.is_file():
                evaluation_digest_match = False
                invalid_reasons.append("missing-evaluation-artifact")
                notes.append("envelope references an evaluation artifact that is absent")
            else:
                evaluation_digest_match = sha256_file(artifact) == expected
                if not evaluation_digest_match:
                    invalid_reasons.append("evaluation-digest-mismatch")
                    notes.append(
                        "evaluation-result.json does not match the envelope digest "
                        "(artifact integrity failure)"
                    )
    return {
        "run_id": run_id,
        "task_id": task_id,
        "arm": arm,
        "repetition": repetition,
        "protocol_id": record.get("protocol_id"),
        "terminal_status": status,
        "flags": sorted(flags),
        "trace_coverage": coverage,
        "patch_digest": record.get("patch_digest") or None,
        "evaluation_present": evaluation is not None,
        "task_success_raw": raw_success,
        "failure_class": (evaluation or {}).get("failure_class"),
        "replay_equal": (evaluation or {}).get("replay_equal"),
        "effective_success": effective_success,
        "analysis_eligible": not invalid_reasons,
        "invalid_reasons": invalid_reasons,
        "evaluation_digest_checked": evaluation_digest_checked,
        "evaluation_digest_match": evaluation_digest_match,
        "jev_executed_searches": jev_searches,
        "costs": _cost_bucket(costs),
        "notes": notes,
    }


def _comparison(
    cells: dict[tuple[str, str], list[dict[str, Any]]],
    task_ids: list[str],
    left: str,
    right: str,
    *,
    require_arms: tuple[str, ...] | None,
) -> dict[str, Any]:
    pairs: list[tuple[str, list[int], list[int]]] = []
    for task_id in task_ids:
        if require_arms is not None and not all((task_id, arm) in cells for arm in require_arms):
            continue
        left_cells = cells.get((task_id, left)) or []
        right_cells = cells.get((task_id, right)) or []
        right_by_rep = {cell["repetition"]: cell for cell in right_cells}
        common = [
            (cell["repetition"], cell, right_by_rep[cell["repetition"]])
            for cell in sorted(left_cells, key=lambda item: item["repetition"])
            if cell["repetition"] in right_by_rep
        ]
        if not common:
            continue
        left_values = [int(cell["effective_success"]) for _, cell, _ in common]
        right_values = [int(other["effective_success"]) for _, _, other in common]
        ineligible = sum(
            1
            for _, cell, other in common
            if cell.get("ineligible_counted") or other.get("ineligible_counted")
        )
        pairs.append((task_id, left_values, right_values, ineligible))
    if not pairs:
        return {
            "left": left,
            "right": right,
            "tasks": [],
            "n_tasks": 0,
            "ineligible_counted": 0,
            "estimate": None,
            "ci_low": None,
            "ci_high": None,
            "mcnemar_p": None,
            "discordant_left": None,
            "discordant_right": None,
            "note": "no complete pairs in this analysis set",
        }
    clusters = [
        [float(left_value - right_value) for left_value, right_value in zip(left_values, right_values)]
        for _, left_values, right_values, _ in pairs
    ]
    interval = clustered_bootstrap(clusters, reps=BOOTSTRAP_REPS, seed=BOOTSTRAP_SEED)
    first_left = [left_values[0] for _, left_values, _, _ in pairs]
    first_right = [right_values[0] for _, _, right_values, _ in pairs]
    mcnemar = exact_mcnemar(first_left, first_right)
    return {
        "left": left,
        "right": right,
        "tasks": [task_id for task_id, _, _, _ in pairs],
        "n_tasks": len(pairs),
        "ineligible_counted": sum(item[3] for item in pairs),
        "left_successes": sum(sum(values) for _, values, _, _ in pairs),
        "right_successes": sum(sum(values) for _, _, values, _ in pairs),
        "estimate": interval.estimate,
        "ci_low": interval.low,
        "ci_high": interval.high,
        "mcnemar_p": mcnemar.p_value,
        "discordant_left": mcnemar.discordant_left,
        "discordant_right": mcnemar.discordant_right,
        "bootstrap": {
            "reps": interval.reps,
            "seed": interval.seed,
            "method": interval.method,
            "caveat": interval.caveat,
        },
        "mcnemar": {"method": mcnemar.method, "basis": "first complete repetition"},
    }


def _run_totals(cells: list[dict[str, Any]]) -> dict[str, Any]:
    jev = Decimal(0)
    tokens = 0
    wall = 0.0
    with_costs = 0
    for cell in cells:
        costs = cell["costs"]
        seen = False
        if costs.get("jev_cash_usd") is not None:
            try:
                jev += Decimal(str(costs["jev_cash_usd"]))
                seen = True
            except InvalidOperation:
                pass
        if costs.get("codex_quota_tokens") is not None:
            tokens += int(costs["codex_quota_tokens"])
            seen = True
        if costs.get("local_compute_wall_s") is not None:
            wall += float(costs["local_compute_wall_s"])
            seen = True
        if seen:
            with_costs += 1
    return {
        "jev_cash_usd_total": f"{jev:.3f}",
        "codex_quota_tokens_total": tokens,
        "local_compute_wall_s_total": round(wall, 1),
        "runs_with_costs": with_costs,
    }


def build_live_report(
    runs_dir: Path,
    destination: Path,
    *,
    corpus_dir: Path | None = None,
    ledger_path: Path | None = None,
) -> bytes:
    """Build the deterministic paired pilot report from retained run records."""
    corpus = corpus_dir if corpus_dir is not None else Path("corpus")
    if not corpus.is_dir():
        raise FileNotFoundError(f"{REQUIRED_CORPUS_NOTE}: {corpus}")

    record_paths = sorted(runs_dir.glob("*/run-record.json"))
    cells: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for record_path in record_paths:
        record = _load_run(record_path)
        run_id = str(record.get("run_id", record_path.parent.name))
        flags = [str(flag) for flag in (record.get("flags") or [])]
        if (
            SIMULATED_FLAG in flags
            or "mock" in run_id.lower()
            or bool(record.get("simulated"))
        ):
            raise ReportRefusal(f"live builder refuses simulated run: {run_id}")
        task_id = str(record.get("task_id", ""))
        arm = str(record.get("condition_id") or record.get("arm") or "unknown")
        admission = _admission_status(corpus, task_id)
        if admission != "admitted":
            reason = (
                "missing-admission-record" if admission is None else f"admission_status={admission}"
            )
            exclusions.append(
                {"run_id": run_id, "task_id": task_id, "arm": arm, "reason": reason}
            )
            continue
        cells.append(_cell(record_path.parent, record))

    cells.sort(key=lambda cell: (cell["task_id"], cell["arm"], cell["repetition"]))
    eligible = [cell for cell in cells if cell["analysis_eligible"]]
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for cell in eligible:
        by_key.setdefault((cell["task_id"], cell["arm"]), []).append(cell)
    task_ids = sorted({cell["task_id"] for cell in eligible})
    complete_triplets = [
        task_id
        for task_id in task_ids
        if all((task_id, arm) in by_key for arm in PRIMARY_ARMS)
    ]

    # Sensitivity = every assigned cell on admitted tasks; cells invalidated by
    # protocol rules remain in the denominator and count as unsuccessful, with
    # the count exposed as `ineligible_counted` (failure/missingness explicit).
    assigned_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for cell in cells:
        shaped = (
            cell
            if cell["analysis_eligible"]
            else {**cell, "effective_success": False, "ineligible_counted": True}
        )
        assigned_key.setdefault((cell["task_id"], cell["arm"]), []).append(shaped)
    assigned_tasks = sorted({cell["task_id"] for cell in cells})

    def comparisons(
        source: dict[tuple[str, str], list[dict[str, Any]]],
        tasks: list[str],
        *,
        require_arms: tuple[str, ...] | None,
    ) -> dict[str, Any]:
        return {
            f"{left}_minus_{right}": _comparison(
                source, tasks, left, right, require_arms=require_arms
            )
            for left, right in PRIMARY_COMPARISONS
        }

    primary = comparisons(by_key, task_ids, require_arms=PRIMARY_ARMS)
    sensitivity = comparisons(assigned_key, assigned_tasks, require_arms=None)

    ledger: dict[str, Any] | None = None
    resolved_ledger = ledger_path if ledger_path is not None else runs_dir / "ledger.json"
    if resolved_ledger.is_file():
        raw = _load_run(resolved_ledger)
        ledger = {
            "cap_usd": raw.get("cap_usd"),
            "committed_cash_usd": raw.get("committed_cash_usd"),
            "reserved_cash_usd": raw.get("reserved_cash_usd"),
            "available_cash_usd": raw.get("available_cash_usd"),
            "entries": len(raw.get("entries") or []),
            "note": (
                "ledger committed totals include smoke and repair-wave spend "
                "(same accounting rail as the benchmark); per-run columns are "
                "the pilot totals"
            ),
        }

    totals = _run_totals(cells)
    integrity_failures = sorted(
        cell["run_id"] for cell in cells if cell.get("evaluation_digest_match") is False
    )
    claims = [
        {
            "claim": "paired A0/A1/A3 pilot executed on the frozen dev corpus",
            "status": "supported" if complete_triplets else "withheld",
            "evidence": {
                "complete_triplet_tasks": complete_triplets,
                "protocol_basis": "experiments/pilot.yaml (frozen; corpus/selection/pricing digests filled 2026-09-30)",
            },
        },
        {
            "claim": "primary paired comparisons computed (A1-A0, A3-A0)",
            "status": (
                "supported"
                if all(item["n_tasks"] >= 1 for item in primary.values())
                else "withheld"
            ),
            "evidence": {key: item["n_tasks"] for key, item in primary.items()},
        },
        {
            "claim": (
                "Jev provider spend is included in the cost columns "
                "(modeled from executed-search counts at the frozen measured rate)"
            ),
            "status": "supported" if totals["runs_with_costs"] else "withheld",
            "evidence": {
                "jev_cash_usd_total": totals["jev_cash_usd_total"],
                "rate_usd_per_search": JEV_RATE_USD_PER_SEARCH,
                "receipts": "per-run provider receipts unavailable (account-level totals only)",
            },
        },
        {
            "claim": "retained evaluation artifacts bind to their run envelopes (sha256)",
            "status": "withheld" if integrity_failures else "supported",
            "evidence": {
                "checked": sum(1 for cell in cells if cell.get("evaluation_digest_checked")),
                "mismatches": integrity_failures,
            },
        },
        {
            "claim": "no simulated outputs among analysis inputs",
            "status": "supported",
            "evidence": {
                "enforced_by": "simulated-fixture flag + run-id/record marker check (live builder refuses)"
            },
        },
        {
            "claim": "retrieval-only metrics",
            "status": "withheld",
            "reason": "retrieval-only pass is not part of the pilot execution set",
        },
        {
            "claim": "per-run isolation and network probe artifacts",
            "status": "withheld",
            "reason": (
                "pilot emitted recipe-level validation (V4/V4b) only; per-run probe "
                "artifacts are required before any holdout claim"
            ),
        },
    ]

    payload: dict[str, Any] = {
        "report_version": LIVE_REPORT_VERSION,
        "protocol_ids": sorted({str(cell["protocol_id"]) for cell in cells if cell["protocol_id"]}),
        "analysis": {
            "arms": list(PRIMARY_ARMS),
            "primary_comparisons": [f"{left}_minus_{right}" for left, right in PRIMARY_COMPARISONS],
            "bootstrap": {"reps": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED},
            "timeout_rule": "timeouts count as failures",
            "partial_coverage_rule": "trace-derived metrics suppressed; evaluation retained",
            "exclusion_rule": "admission_status != admitted is never eligible for scoring",
        },
        "runs": cells,
        "exclusions": exclusions,
        "analysis_sets": {
            "primary": {"tasks": complete_triplets, "comparisons": primary},
            "sensitivity_all_assigned": {"tasks": assigned_tasks, "comparisons": sensitivity},
        },
        "spend": {
            "ledger": ledger,
            "run_totals": totals,
            "pricing_basis": {
                "jev_rate_usd_per_search": JEV_RATE_USD_PER_SEARCH,
                "jev_rate_provenance": "V6 live credit-delta measurement (n=4, 2026-09-29)",
                "receipts": "per-run receipts unavailable; account-level totals only (modeled cash, labeled)",
            },
            "ledger_path_provided": ledger is not None,
        },
        "artifact_integrity": {
            "evaluation_binding_checked": sum(
                1 for cell in cells if cell.get("evaluation_digest_checked")
            ),
            "evaluation_binding_failures": integrity_failures,
        },
        "claim_map": claims,
        "limitations": [
            "pilot is instrumentation-only (single repetition; no efficacy claims)",
            "task-clustered paired analysis, exact McNemar on first complete repetition",
            "Jev cash is modeled from executed-search counts at the frozen measured rate; per-run receipts are not exposed by the provider gateway",
            "per-run isolation/network probe artifacts were not emitted in the pilot (recipe-level validation only); holdout runs must emit them",
        ],
        "report_digest": "",
    }
    payload["report_digest"] = digest(payload, component="live-report")
    content = canonical_json(payload)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return content


def build_report(runs_dir: Path, destination: Path, *, demo: bool = False) -> bytes:
    """Compatibility dispatcher: demo renders mocks, live renders paired evidence."""
    if demo:
        return build_demo_report(runs_dir, destination)
    return build_live_report(runs_dir, destination)
