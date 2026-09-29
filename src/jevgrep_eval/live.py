"""The verified, opt-in live Codex harness path.

The planning API is intentionally side-effect free.  The execution API is
the only place that materializes a task workspace, seeds a Codex home, or
starts the existing runner.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .costing import (
    STAGE_ALLOCATIONS,
    SpendGateError,
    SpendLedger,
    load_pricing,
    usage_cost,
)
from .harnesses.codex import (
    CodexHarness,
    CodexHarnessError,
    Invocation,
    load_harness_config,
)
from .isolation import agent_bwrap_argv, load_host_bindings
from .materialize import materialize_repo
from .models import EventKind, SpendEntry, TaskCase
from .retrieval.bm25 import BM25Index
from .runner import Runner, RunnerError
from .traces_codex import parse_codex_rollout
from .util import canonical_json, digest, write_canonical_json

OK = 0
VALIDATION = 3
POLICY = 4
MISSING = 5

JG_RATE = Decimal("0.048")
JG_SEARCHES = 6
JG_RESERVATION = JG_RATE * JG_SEARCHES
JG_RATE_SOURCE = (
    "LIVE-MEASURED: gateway /v1/credits delta (V6 2026-09-29; n=4)"
)


class LiveHarnessError(ValueError):
    """The live harness configuration is invalid."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise LiveHarnessError(f"cannot load {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LiveHarnessError(f"{label} must be a mapping")
    return payload


def load_experiment(path: Path) -> dict[str, Any]:
    """Load one experiment definition."""
    return _load_mapping(path, "experiment")


def load_condition(path: Path) -> dict[str, Any]:
    """Load one frozen arm condition."""
    return _load_mapping(path, "condition")


# Arm-neutral standing directive: the frozen task statements are sanitized of fix-oriented
# wording, so the harness template must state the work expectation explicitly. The text is
# identical across arms and carries no solution hints. Pilot finding (2026-09-29): without it
# the a0 smoke agent concluded read-only investigation ("I haven't changed anything").
STANDING_DIRECTIVE = (
    "You are working in a repository checkout. The report below describes a behavioral issue. "
    "Resolve the issue by modifying the repository as needed, and verify your change with the "
    "test suite."
)


def build_prompt(statement: str, fragment: str) -> str:
    """Build the exact directive-plus-statement-plus-condition prompt."""
    statement = str(statement).strip()
    fragment = str(fragment or "").strip()
    parts = [STANDING_DIRECTIVE, statement]
    if fragment:
        parts.append(fragment)
    return "\n\n".join(parts)


def _task_definition_path(corpus_root: Path, task_id: str) -> Path:
    candidates = (
        corpus_root / "tasks" / task_id / "task.yaml",
        corpus_root / "tasks" / f"{task_id}.yaml",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"task definition is missing: {candidates[0]}")


def _first_hidden_argv(admission: dict[str, Any]) -> list[str]:
    """Read the first recorded argv from the hidden-test admission run."""
    for section_name in ("base_hidden", "gold_hidden", "hidden"):
        section = admission.get(section_name)
        if not isinstance(section, dict):
            continue
        repetitions = section.get("repetitions")
        if not isinstance(repetitions, list):
            continue
        for repetition in repetitions:
            if not isinstance(repetition, dict):
                continue
            argv = repetition.get("argv")
            if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
                return list(argv)
    commands = admission.get("commands")
    if isinstance(commands, dict):
        for key in ("hidden", "hidden_test", "measured"):
            argv = commands.get(key)
            if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
                return list(argv)
    raise LiveHarnessError("admission evidence has no hidden-test argv")


def load_task(corpus_root: Path, task_id: str) -> dict[str, Any]:
    """Load a task and the evaluator-only artifacts associated with it."""
    task_path = _task_definition_path(corpus_root, task_id)
    task_dir = task_path.parent
    task = _load_mapping(task_path, "task")
    if str(task.get("task_id", "")) != task_id:
        raise LiveHarnessError(f"task definition has the wrong task id: {task_path}")

    admission_path = task_dir / "admission.json"
    evidence_path = task_dir / "gold-evidence.json"
    try:
        admission = json.loads(admission_path.read_text(encoding="utf-8"))
        gold_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveHarnessError(f"cannot load evaluator evidence for {task_id}: {exc}") from exc
    if not isinstance(admission, dict) or not isinstance(gold_evidence, dict):
        raise LiveHarnessError(f"evaluator evidence must be mappings: {task_dir}")

    hidden_patch = task_dir / "hidden_tests.patch"
    if not hidden_patch.is_file():
        raise FileNotFoundError(f"hidden test patch is missing: {hidden_patch}")
    files = gold_evidence.get("files", [])
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise LiveHarnessError(f"gold evidence files are invalid: {evidence_path}")
    task = dict(task)
    task["hidden_test_patch"] = hidden_patch
    task["hidden_test_command"] = _first_hidden_argv(admission)
    task["gold_evidence_files"] = list(files)
    return task


def _command_argv(command: list[str] | tuple[str, ...] | str) -> list[str]:
    if isinstance(command, str):
        command = command.split(";", 1)[0].strip()
        return shlex.split(command)
    if not all(isinstance(item, str) for item in command):
        raise LiveHarnessError("setup commands must contain strings")
    return list(command)


def _setup_commands(
    out: Path,
    setup_commands: list[list[str]] | list[str] | None,
) -> list[list[str]]:
    if setup_commands:
        if not isinstance(setup_commands, list):
            raise LiveHarnessError("setup_commands must be a list")
        if all(isinstance(item, str) for item in setup_commands):
            return [_command_argv(item) for item in setup_commands]
        if not all(isinstance(item, list) for item in setup_commands):
            raise LiveHarnessError("setup commands must be argv lists or strings")
        return [_command_argv(item) for item in setup_commands]
    if any((out / name).is_file() for name in ("pyproject.toml", "setup.py", "setup.cfg")):
        # Verified offline recipe (V5 staging): pinned 3.12 venv + editable install from the
        # warmed uv cache. `uv sync` is NOT used: default dependency groups pull packages the
        # offline cache does not carry (e.g. pyright in click's typing group).
        return [
            ["uv", "venv", "--python", "3.12"],
            ["uv", "pip", "install", "pytest", "-e", ".[dev]"],
        ]
    return []


def prepare_workspace(
    *,
    source_repo: Path,
    base_sha: str,
    out: Path,
    dep_cache: Path,
    setup_commands: list[list[str]] | list[str] | None = None,
) -> None:
    """Materialize a repo and prepare its dependencies from an offline cache."""
    materialize_repo(source_repo, base_sha, out)
    commands = _setup_commands(out, setup_commands)
    if not commands:
        return
    environment = os.environ.copy()
    # Strip interpreter-manager env from the caller (a leaked VIRTUAL_ENV redirected uv to the
    # wrong environment during the operator smoke; V4b recorded the sibling bwrap env leak).
    for leaked in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
        environment.pop(leaked, None)
    environment["UV_CACHE_DIR"] = str(dep_cache.expanduser().resolve())
    environment["UV_OFFLINE"] = "1"
    environment["UV_PYTHON"] = "3.12"
    user_bin = Path.home() / ".local" / "bin"
    environment["PATH"] = os.pathsep.join(
        [str(user_bin), environment.get("PATH", "")]
    ).rstrip(os.pathsep)
    dep_cache.mkdir(parents=True, exist_ok=True)

    defaulted = setup_commands is None
    for command in commands:
        if not command:
            continue
        try:
            subprocess.run(command, cwd=out, env=environment, check=True)
        except subprocess.CalledProcessError:
            if defaulted and command[-3:] == ["pytest", "-e", ".[dev]"]:
                # Base-era repos without a [dev] extra install as plain editable + pytest.
                fallback = ["uv", "pip", "install", "pytest", "-e", "."]
                subprocess.run(fallback, cwd=out, env=environment, check=True)
                continue
            raise


def seed_codex_home(
    run_dir: Path,
    bindings: dict[str, str],
    *,
    model: str,
    effort: str,
) -> Path:
    """Create an idempotent, per-run Codex home with only required state."""
    if "codex_home_source" not in bindings:
        raise LiveHarnessError("host bindings missing codex_home_source")
    codex_home = run_dir / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / ".config").mkdir(exist_ok=True)
    source = Path(bindings["codex_home_source"]).expanduser()
    auth_source = source if source.name == "auth.json" else source / "auth.json"
    if not auth_source.is_file():
        raise FileNotFoundError(f"Codex auth.json is missing: {auth_source}")
    auth_destination = codex_home / "auth.json"
    shutil.copyfile(auth_source, auth_destination)
    auth_destination.chmod(0o600)
    config = (
        f"model = {json.dumps(model)}\n"
        f"model_reasoning_effort = {json.dumps(effort)}\n\n"
        '[projects."/workspace"]\n'
        'trust_level = "trusted"\n'
    )
    (codex_home / "config.toml").write_text(config, encoding="utf-8")
    return codex_home


def stage_bm25(
    *,
    workspace: Path,
    run_dir: Path,
    engine_repo: Path,
    engine_venv: Path,
) -> tuple[Path, Path]:
    """Build the deterministic index and the sandbox-visible executable shim."""
    del engine_repo  # The repo itself is mounted by agent_bwrap_argv.
    index = run_dir / "bm25.index"
    BM25Index.from_root(workspace).write_artifact(index)
    tools = run_dir / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    python = (engine_venv / "bin" / "python").resolve()
    shim = tools / "bm25"
    shim.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(str(python))} -m jevgrep_eval.cli retrieve bm25 query "
        '/bm25.index "$*"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim, index


def _pricing_path() -> Path:
    return _repo_root() / "configs" / "pricing" / "pricing.yaml"


def load_or_create_ledger(path: Path) -> SpendLedger:
    """Load a persisted ledger, or return a fresh ledger without writing."""
    cap = Decimal(50)
    pricing_path = _pricing_path()
    if pricing_path.is_file():
        cap = load_pricing(pricing_path).cap_usd
    if not path.is_file():
        return SpendLedger(cap, stage_allocations=dict(STAGE_ALLOCATIONS))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("ledger snapshot must be a mapping")
        ledger = SpendLedger(
            Decimal(str(payload.get("cap_usd", cap))),
            stage_allocations=dict(STAGE_ALLOCATIONS),
        )
        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            raise TypeError("ledger entries must be a list")
        normalized_entries: list[SpendEntry] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise TypeError("ledger entries must be mappings")
            normalized_entry = dict(entry)
            for field in ("cumulative_usd", "reserved_usd", "estimate_usd"):
                value = normalized_entry.get(field)
                if value is not None and value != "unknown":
                    normalized_entry[field] = Decimal(str(value))
            normalized_entries.append(SpendEntry.model_validate(normalized_entry))
        ledger.entries = normalized_entries
        ledger._reserved = sum(
            (entry.reserved_usd for entry in ledger.entries),
            Decimal(0),
        )
        ledger._stopped = any(entry.status == "stopped" for entry in ledger.entries)
        return ledger
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise LiveHarnessError(f"cannot load ledger: {exc}") from exc


def save_ledger(ledger: SpendLedger, path: Path) -> None:
    """Persist exactly the ledger snapshot used for a later run."""
    write_canonical_json(path, ledger.snapshot())


def _condition_has(condition: dict[str, Any], tool: str) -> bool:
    tools = condition.get("retrieval_tools", [])
    return isinstance(tools, list) and tool in tools


def reserve_for_run(
    ledger: SpendLedger,
    run_id: str,
    condition: dict[str, Any],
    experiment: dict[str, Any],
) -> None:
    """Reserve the worst-case Jevgrep spend before any run-side effects."""
    if not _condition_has(condition, "jg"):
        return
    budget = experiment.get("budget", {})
    if not isinstance(budget, dict):
        budget = {}
    stage = str(budget.get("stage", "stage_2_pilot"))
    allocation = ledger.stage_allocations.get(stage)
    # Snapshots do not retain the private stage index from SpendLedger.  Treat
    # existing committed/reserved cash as belonging to this stage here.  This
    # is conservative and keeps a restored ledger fail-closed.
    if (
        allocation is not None
        and ledger.committed_cash_usd + ledger.reserved_cash_usd + JG_RESERVATION
        > allocation
    ):
        raise SpendGateError("reservation exceeds stage allocation")
    ledger.reserve(
        run_id,
        "jev",
        JG_RESERVATION,
        JG_RATE_SOURCE,
        stage=stage,
    )


def _event_kind(event: Any) -> str:
    kind = event.get("kind") if isinstance(event, dict) else getattr(event, "kind", "")
    return str(getattr(kind, "value", kind))


def reconcile_for_run(
    ledger: SpendLedger,
    run_id: str,
    record_events: Iterable[Any],
    rate: Decimal | str,
) -> None:
    """Commit the observed Jevgrep event count against the run reservation."""
    count = sum(1 for event in record_events if _event_kind(event) == EventKind.SEARCH_JG.value)
    ledger.reconcile(
        run_id,
        actual_usd=Decimal(str(rate)) * count,
        rate_source=JG_RATE_SOURCE,
        receipt_id=run_id,
    )


def _task_case(task: dict[str, Any]) -> TaskCase:
    value = dict(task)
    for key in ("_task_path", "_task_dir"):
        value.pop(key, None)
    value["hidden_test_patch"] = str(value["hidden_test_patch"])
    value["gold_evidence_files"] = [str(item) for item in value.get("gold_evidence_files", [])]
    return TaskCase.model_validate(value)


def _harness_config() -> dict[str, Any]:
    path = _repo_root() / "configs" / "harness.yaml"
    if path.is_file():
        return load_harness_config(path)
    return {"command": ["codex", "exec"], "sandbox": "workspace-write"}


def _prompt_and_invocation(
    task: dict[str, Any],
    condition: dict[str, Any],
    *,
    model: str,
    effort: str,
) -> tuple[str, Invocation]:
    prompt = build_prompt(
        str(task.get("statement", "")),
        str(condition.get("prompt_fragment", "")),
    )
    invocation = CodexHarness(
        config={"command": ["codex", "exec"], "sandbox": "workspace-write"}
    ).assemble_invocation(
        prompt,
        model=model,
        effort=effort,
        env={},
    )
    return prompt, invocation


def _resolved_binding_path(
    bindings_path: Path | None,
) -> Path:
    return bindings_path or (
        _repo_root() / "configs" / "isolation" / "host_bindings.local.yaml"
    )


def _experiment_agent(experiment: dict[str, Any]) -> tuple[str, str]:
    agent = experiment.get("agent", {})
    if not isinstance(agent, dict):
        raise LiveHarnessError("experiment agent must be a mapping")
    model = str(agent.get("model", ""))
    effort = str(agent.get("effort", ""))
    if not model or not effort:
        raise LiveHarnessError("experiment agent model and effort are required")
    return model, effort


def _make_plan(
    *,
    runs_root: Path,
    ledger_path: Path,
    experiment_path: Path,
    condition_path: Path,
    corpus_root: Path,
    task_id: str,
    arm: str,
    rep: int,
    bindings_path: Path | None,
) -> dict[str, Any]:
    experiment = load_experiment(experiment_path)
    condition = load_condition(condition_path)
    task = load_task(corpus_root, task_id)
    model, effort = _experiment_agent(experiment)
    bindings = load_host_bindings(_resolved_binding_path(bindings_path))
    run_id = f"{task_id}-{arm}-r{rep}"
    run_dir = (runs_root / run_id).resolve()
    workspace = run_dir / "workspace"
    codex_home = run_dir / "codex-home"
    repo_root = _repo_root()
    engine_repo = repo_root
    engine_venv = repo_root / ".venv"
    prompt, invocation = _prompt_and_invocation(
        task,
        condition,
        model=model,
        effort=effort,
    )
    bm25_tool = run_dir / "tools" / "bm25" if _condition_has(condition, "bm25") else None
    bm25_index = run_dir / "bm25.index" if bm25_tool is not None else None
    bwrap = agent_bwrap_argv(
        workspace=workspace,
        codex_home=codex_home,
        bindings=bindings,
        engine_repo=engine_repo,
        engine_venv=engine_venv,
        bm25_tool=bm25_tool,
        bm25_index=bm25_index,
    )
    node_codex = str(Path(bindings["node"]) / "bin" / "codex")
    executor_tail = [node_codex, *invocation.argv[1:]]
    full_argv = [*bwrap, *executor_tail]
    ledger = load_or_create_ledger(ledger_path)
    jg = _condition_has(condition, "jg")
    reservation = JG_RESERVATION if jg else Decimal(0)
    stage = str(experiment.get("budget", {}).get("stage", "stage_2_pilot"))
    allocation = ledger.stage_allocations.get(stage)
    available = ledger.available_usd
    stage_available = (
        allocation - ledger.committed_cash_usd - ledger.reserved_cash_usd
        if allocation is not None
        else available
    )
    can_reserve = available >= reservation and stage_available >= reservation
    budget = {
        "reservation_usd": str(reservation),
        "reserved_searches": JG_SEARCHES if jg else 0,
        "rate_usd_per_search": str(JG_RATE) if jg else "0",
        "rate_source": JG_RATE_SOURCE if jg else None,
        "stage": stage,
    }
    ledger_availability = {
        "available_usd": str(available),
        "stage_available_usd": str(stage_available),
        "can_reserve": can_reserve,
    }
    return {
        "run_id": run_id,
        "task": task_id,
        "arm": arm,
        "repetition": rep,
        "workspace": str(workspace),
        "workspace_path": str(workspace),
        "codex_home": str(codex_home),
        "codex_home_path": str(codex_home),
        "prompt_digest": digest(prompt),
        "bwrap_argv": bwrap,
        "argv": full_argv,
        "executor_argv_tail": executor_tail,
        "env": {},
        "model": model,
        "effort": effort,
        "budget": budget,
        "budget_reservation_preview": str(reservation),
        "ledger_availability": ledger_availability,
        "dry_run": True,
    }


def plan_run(
    *,
    runs_root: Path,
    ledger_path: Path,
    experiment_path: Path,
    condition_path: Path,
    corpus_root: Path,
    task_id: str,
    arm: str,
    rep: int = 0,
    bindings_path: Path | None = None,
) -> dict[str, Any]:
    """Return the complete dry-run plan without writing any file."""
    return _make_plan(
        runs_root=runs_root,
        ledger_path=ledger_path,
        experiment_path=experiment_path,
        condition_path=condition_path,
        corpus_root=corpus_root,
        task_id=task_id,
        arm=arm,
        rep=rep,
        bindings_path=bindings_path,
    )


def _source_repo(corpus_root: Path, task: dict[str, Any]) -> Path:
    repo_id = str(task["repo_id"])
    configured = task.get("source_repo")
    candidates = []
    if configured:
        candidates.append(Path(str(configured)))
    candidates.extend(
        [
            corpus_root.parent / ".staging" / "corpus-inputs" / "repo-cache" / repo_id,
            corpus_root / "repos" / repo_id,
            corpus_root / ".repos" / repo_id,
            corpus_root / ".cache" / repo_id,
            corpus_root.parent / "repos" / repo_id,
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"staged source repository is missing for {repo_id}: {candidates[0]}"
    )


def _dep_cache(corpus_root: Path, task: dict[str, Any]) -> Path:
    repo_id = str(task["repo_id"])
    configured = task.get("dependency_cache")
    if configured:
        return Path(str(configured))
    staged = corpus_root.parent / ".staging" / "corpus-inputs" / "dep-cache" / repo_id
    # V5 convention: uv-kind caches live at <repo_id>/uv (the actual UV_CACHE_DIR root).
    for candidate in (staged / "uv", staged):
        if candidate.is_dir():
            return candidate
    return corpus_root.parent / "dep-cache" / repo_id


def _duration_seconds(record: Any) -> float:
    """Wall seconds from the first lifecycle stage to the last."""
    stages = getattr(record, "stage_records", None) or []
    try:
        first = getattr(stages[0], "at", None)
        last = getattr(stages[-1], "at", None)
        if first is not None and last is not None:
            return max(0.0, (last - first).total_seconds())
    except (TypeError, AttributeError):
        pass
    return 0.0


def _capture_rollout(run_dir: Path, workspace: Path) -> dict[str, Any]:
    sessions = run_dir / "codex-home" / "sessions"
    candidates = sorted(
        sessions.rglob("rollout-*.jsonl"),
        key=lambda item: item.stat().st_mtime_ns,
    )
    if not candidates:
        raise FileNotFoundError(f"Codex rollout is missing under {sessions}")
    rollout = candidates[-1]
    destination = run_dir / "rollout.jsonl"
    shutil.copyfile(rollout, destination)
    parsed = parse_codex_rollout(
        destination.read_text(encoding="utf-8").splitlines(),
        str(workspace),
    )
    provider_meta = parsed.provider_meta
    write_canonical_json(run_dir / "provider-meta.json", provider_meta)
    return provider_meta


def _task_setup_commands(task: dict[str, Any]) -> list[str] | None:
    commands = task.get("setup_commands")
    if commands is None:
        return None
    if not isinstance(commands, list):
        raise LiveHarnessError("task setup_commands must be a list")
    # task.yaml records human-readable preparation notes (strings), not executable commands;
    # only argv-list entries are executable. All-notes → None → the verified default recipe.
    executable = [list(command) for command in commands if isinstance(command, (list, tuple))]
    if not executable:
        return None
    return executable


def run_live(
    *,
    runs_root: Path,
    ledger_path: Path,
    experiment_path: Path,
    condition_path: Path,
    corpus_root: Path,
    task_id: str,
    arm: str,
    rep: int,
    dry_run: bool,
    bindings_path: Path | None,
) -> int:
    """Plan or execute one verified live run and return a CLI exit code."""
    resolved_bindings_path = _resolved_binding_path(bindings_path)
    if not resolved_bindings_path.is_file():
        return POLICY
    try:
        plan = plan_run(
            runs_root=runs_root,
            ledger_path=ledger_path,
            experiment_path=experiment_path,
            condition_path=condition_path,
            corpus_root=corpus_root,
            task_id=task_id,
            arm=arm,
            rep=rep,
            bindings_path=bindings_path,
        )
        if dry_run:
            print(canonical_json(plan).decode("utf-8"), end="")
            return OK
    except (FileNotFoundError, OSError):
        return MISSING
    except (CodexHarnessError, LiveHarnessError, TypeError, ValueError, yaml.YAMLError):
        return VALIDATION

    run_id = str(plan["run_id"])
    run_dir = Path(str(plan["workspace"])).parent
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        experiment = load_experiment(experiment_path)
        condition = load_condition(condition_path)
        task = load_task(corpus_root, task_id)
        bindings = load_host_bindings(resolved_bindings_path)
        ledger = load_or_create_ledger(ledger_path)
        reserve_for_run(ledger, run_id, condition, experiment)
        save_ledger(ledger, ledger_path)
    except SpendGateError:
        save_ledger(ledger, ledger_path) if "ledger" in locals() else None
        return POLICY
    except FileNotFoundError:
        return MISSING
    except (LiveHarnessError, TypeError, ValueError, OSError, yaml.YAMLError):
        return VALIDATION

    workspace = Path(str(plan["workspace"]))
    codex_home: Path | None = None
    try:
        source_repo = _source_repo(corpus_root, task)
        prepare_workspace(
            source_repo=source_repo,
            base_sha=str(task["base_sha"]),
            out=workspace,
            dep_cache=_dep_cache(corpus_root, task),
            setup_commands=_task_setup_commands(task),
        )
        model, effort = _experiment_agent(experiment)
        codex_home = seed_codex_home(run_dir, bindings, model=model, effort=effort)
        engine_repo = _repo_root()
        engine_venv = engine_repo / ".venv"
        bm25_tool = bm25_index = None
        if _condition_has(condition, "bm25"):
            bm25_tool, bm25_index = stage_bm25(
                workspace=workspace,
                run_dir=run_dir,
                engine_repo=engine_repo,
                engine_venv=engine_venv,
            )
        prompt, invocation = _prompt_and_invocation(
            task,
            condition,
            model=model,
            effort=effort,
        )
        bwrap = agent_bwrap_argv(
            workspace=workspace,
            codex_home=codex_home,
            bindings=bindings,
            engine_repo=engine_repo,
            engine_venv=engine_venv,
            bm25_tool=bm25_tool,
            bm25_index=bm25_index,
        )
        node_codex = str(Path(bindings["node"]) / "bin" / "codex")
        argv = [*bwrap, node_codex, *invocation.argv[1:]]
        forced_first = condition.get("forced_first") or None
        record = Runner(timeout_s=float(_harness_config().get("timeout_seconds", 600))).run(
            run_id=run_id,
            task_id=task_id,
            condition_id=arm,
            workspace=workspace,
            argv=argv,
            repetition=rep,
            timeout_s=float(_harness_config().get("timeout_seconds", 600)),
            env={},
            artifact_dir=run_dir,
            task=_task_case(task),
            statement=str(task["statement"]),
            prompt_common=str(task["statement"]),
            prompt_fragment=str(condition.get("prompt_fragment", "")),
            invocation=invocation.bytes,
            requested_model=model,
            resolved_model=model,
            effort=effort,
            forced_first=forced_first,
            hidden_test_patch=Path(str(task["hidden_test_patch"])),
            hidden_test_command=list(task["hidden_test_command"]),
            upstream_command=None,
        )
        provider_meta = _capture_rollout(run_dir, workspace)
        if _condition_has(condition, "jg"):
            reconcile_for_run(ledger, run_id, record.events, JG_RATE)
        save_ledger(ledger, ledger_path)
        usage = provider_meta.get("usage", {})
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        searches = sum(
            1 for event in record.events if _event_kind(event) == EventKind.SEARCH_JG.value
        )
        costs = usage_cost(
            jev_cash_usd=JG_RATE * searches,
            codex_quota_tokens=int(total_tokens) if total_tokens is not None else None,
            local_compute_wall_s=_duration_seconds(record),
        )
        write_canonical_json(run_dir / "costs.json", costs.model_dump(mode="json"))
        print(
            canonical_json(
                {
                    "run_id": run_id,
                    "terminal_status": str(record.terminal_status),
                    "provider_meta": provider_meta,
                    "costs": costs.model_dump(mode="json"),
                    "ledger": ledger.snapshot(),
                }
            ).decode("utf-8"),
            end="",
        )
        return OK
    except (FileNotFoundError, OSError):
        return MISSING
    except SpendGateError:
        save_ledger(ledger, ledger_path)
        return POLICY
    except (
        CodexHarnessError,
        LiveHarnessError,
        RunnerError,
        TypeError,
        ValueError,
        yaml.YAMLError,
        subprocess.CalledProcessError,
    ):
        return VALIDATION
