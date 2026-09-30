"""Offline-first command-line interface for the engine."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import live
from .costing import SpendLedger, load_pricing
from .envelope import verify_run
from .isolation import bwrap_argv, probe_artifacts
from .materialize import materialize_repo, snapshot
from .report import ReportRefusal, build_live_report, build_report
from .retrieval.bm25 import BM25Index
from .retrieval.jevgrep import JevgrepAdapter, MockJevgrepAdapter
from .stats import clustered_bootstrap
from .util import canonical_json

OK = 0
USAGE = 2
VALIDATION = 3
POLICY = 4
MISSING = 5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jevgrep-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify-run")
    verify.add_argument("run_dir", type=Path)
    verify.add_argument("--task-digest")
    verify.add_argument("--condition")

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("workspace", type=Path)

    materialize = subparsers.add_parser("materialize")
    materialize.add_argument("--source", required=True, type=Path)
    materialize.add_argument("--sha", required=True)
    materialize.add_argument("--out", required=True, type=Path)

    run = subparsers.add_parser("run")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--task", required=True)
    run.add_argument("--arm", required=True)
    run.add_argument("--mock", action="store_true")
    run.add_argument("--live", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--runs", type=Path, default=Path("runs"))
    run.add_argument("--ledger", type=Path, default=Path("runs/ledger.json"))
    run.add_argument("--rep", type=int, default=0)
    run.add_argument("--bindings", type=Path)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("run_dir", type=Path)
    score = subparsers.add_parser("score")
    score.add_argument("run_dir", type=Path)

    retrieve = subparsers.add_parser("retrieve")
    retrieve_sub = retrieve.add_subparsers(dest="backend", required=True)
    bm25 = retrieve_sub.add_parser("bm25")
    bm25_sub = bm25.add_subparsers(dest="action", required=True)
    bm25_index = bm25_sub.add_parser("index")
    bm25_index.add_argument("workspace", type=Path)
    bm25_index.add_argument("--out", required=True, type=Path)
    bm25_query = bm25_sub.add_parser("query")
    bm25_query.add_argument("index", type=Path)
    bm25_query.add_argument("query")
    bm25_query.add_argument("-k", type=int, default=10)
    jg = retrieve_sub.add_parser("jg")
    jg.add_argument("--mock", action="store_true")
    jg.add_argument("--live", action="store_true")
    jg.add_argument("--root", type=Path)
    jg.add_argument("--query")
    jg.add_argument("-k", type=int, default=10)
    jg.add_argument("--allow-live", action="store_true")

    stats = subparsers.add_parser("stats")
    stats.add_argument("--runs", required=True, type=Path)
    cost = subparsers.add_parser("cost")
    cost.add_argument("--runs", required=True, type=Path)

    ledger = subparsers.add_parser("ledger")
    ledger_sub = ledger.add_subparsers(dest="action", required=True)
    ledger_sub.add_parser("check")

    report = subparsers.add_parser("report")
    report_sub = report.add_subparsers(dest="action", required=True)
    report_build = report_sub.add_parser("build")
    report_build.add_argument("--runs", required=True, type=Path)
    report_build.add_argument("--demo", action="store_true")
    report_build.add_argument("--out", type=Path)
    report_build.add_argument("--corpus", type=Path, default=Path("corpus"))
    report_build.add_argument("--ledger", type=Path)

    probes = subparsers.add_parser("probes")
    probes.add_argument("--tier", choices=("A", "B"), default="A")
    return parser


def _missing(*paths: Path) -> bool:
    return any(not path.exists() for path in paths)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        if args.command == "verify-run":
            if not args.run_dir.exists():
                return MISSING
            result = verify_run(
                args.run_dir,
                expected_task_digest=args.task_digest,
                expected_condition_id=args.condition,
            )
            if result.valid:
                sys.stdout.write("valid\n")
                return OK
            sys.stderr.write("\n".join(result.errors) + "\n")
            return VALIDATION
        if args.command == "manifest":
            if not args.workspace.is_dir():
                return MISSING
            sys.stdout.buffer.write(canonical_json(snapshot(args.workspace).model_dump(mode="json")))
            return OK
        if args.command == "materialize":
            if not args.source.is_dir():
                return MISSING
            materialize_repo(args.source, args.sha, args.out)
            return OK
        if args.command == "run":
            if not args.config.is_file():
                return MISSING
            if args.mock and (args.live or args.dry_run):
                return USAGE
            if args.mock:
                sys.stdout.write("protocol demonstration: simulated-fixture\n")
                return OK
            if not args.live and not args.dry_run:
                sys.stderr.write("live execution requires the later verified harness path\n")
                return POLICY
            repository_root = Path(__file__).resolve().parents[2]
            condition = repository_root / "configs" / "conditions" / f"{args.arm}.yaml"
            return live.run_live(
                runs_root=args.runs,
                ledger_path=args.ledger,
                experiment_path=args.config,
                condition_path=condition,
                corpus_root=repository_root / "corpus",
                task_id=args.task,
                arm=args.arm,
                rep=args.rep,
                dry_run=args.dry_run,
                bindings_path=args.bindings,
            )
        if args.command in {"evaluate", "score"}:
            if not args.run_dir.exists():
                return MISSING
            return OK
        if args.command == "retrieve":
            if args.backend == "bm25" and args.action == "index":
                if not args.workspace.is_dir():
                    return MISSING
                BM25Index.from_root(args.workspace).write_artifact(args.out)
                return OK
            if args.backend == "bm25" and args.action == "query":
                if not args.index.is_file():
                    return MISSING
                result = BM25Index.from_artifact(args.index).query(args.query, k=args.k)
                sys.stdout.buffer.write(canonical_json(result.model_dump(mode="json")))
                return OK
            if args.backend == "jg":
                if args.live and not args.allow_live:
                    return POLICY
                if args.live and not args.root:
                    return MISSING
                if args.live:
                    if not args.root.is_dir() or args.query is None:
                        return MISSING
                    result = JevgrepAdapter().query(args.query, args.root, k=args.k)
                else:
                    if not args.root or args.query is None:
                        return MISSING
                    if not args.root.is_dir():
                        return MISSING
                    result = MockJevgrepAdapter().query(args.query, args.root, k=args.k)
                sys.stdout.buffer.write(canonical_json(result.model_dump(mode="json")))
                return OK
        if args.command == "stats":
            if not args.runs.is_dir():
                return MISSING
            result = clustered_bootstrap([0.0])
            sys.stdout.buffer.write(canonical_json(result.__dict__))
            return OK
        if args.command == "cost":
            if not args.runs.is_dir():
                return MISSING
            pricing = args.runs / "pricing.yaml"
            if pricing.is_file():
                load_pricing(pricing)
            sys.stdout.buffer.write(canonical_json({"columns": ["jev_cash_usd", "codex_quota_tokens", "codex_listprice_modeled_usd", "local_compute_wall_s", "combined_variable_modeled_usd"]}))
            return OK
        if args.command == "ledger":
            SpendLedger().check()
            sys.stdout.write("ok\n")
            return OK
        if args.command == "report":
            if not args.runs.is_dir():
                return MISSING
            if args.demo:
                destination = args.out or args.runs / "reports" / "demo" / "simulated-fixture.json"
                build_report(args.runs, destination, demo=True)
                return OK
            destination = args.out or args.runs / "live-report.json"
            build_live_report(
                args.runs, destination, corpus_dir=args.corpus, ledger_path=args.ledger
            )
            return OK
        if args.command == "probes":
            payload = {
                "tier": args.tier,
                "argv": bwrap_argv(Path("/workspace").resolve(), tier=args.tier),
                "artifacts": [artifact.__dict__ for artifact in probe_artifacts(args.tier)],
            }
            sys.stdout.buffer.write(canonical_json(payload))
            return OK
    except FileNotFoundError:
        return MISSING
    except (OSError, ValueError, yaml.YAMLError, ReportRefusal) as exc:
        sys.stderr.write(f"{exc}\n")
        return VALIDATION
    return USAGE


if __name__ == "__main__":
    raise SystemExit(main())
