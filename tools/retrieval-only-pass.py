#!/usr/bin/env python3
"""Retrieval-only mini-pass (diagnostic evidence) over the admitted dev tasks.

Statement-verbatim queries, k=10; jg via the frozen provider config (metered,
~$0.048/search at the V6 measured rate), bm25 local/deterministic. Writes a
canonical JSON artifact (default: ``<repo>/reports/retrieval-only-v1.json``).

Diagnostic only — never efficacy evidence. Re-running the jg arm consumes real
provider spend (~$0.48 for all ten tasks) against a live provider; results are
bound to the recorded jg 0.4.3 text contract and may drift across provider
updates — the committed artifact is the frozen record.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import time
from pathlib import Path

K = 10
TASKS = [
    "click-3533", "click-3678", "click-3764", "click-3805", "click-3818", "click-3865",
    "jinja-1665", "jinja-1852", "jinja-1984", "jinja-2029",
]


def parse_args() -> argparse.Namespace:
    repo_default = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=repo_default,
                        help="repository root (default: parent of this tool's directory)")
    parser.add_argument("--cache", type=Path, default=None,
                        help="repo cache (default: <repo>/.staging/corpus-inputs/repo-cache)")
    parser.add_argument("--bases", type=Path, default=None,
                        help="materialized bases (default: <repo>/.staging/retrieval-bases)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output artifact (default: <repo>/reports/retrieval-only-v1.json)")
    parser.add_argument("--tasks", nargs="*", default=TASKS,
                        help="task ids to run (default: the ten admitted dev tasks)")
    return parser.parse_args()


ARGS = parse_args()
REPO = ARGS.repo.resolve()
sys.path.insert(0, str(REPO / "src"))

import yaml

from jevgrep_eval.materialize import materialize_repo
from jevgrep_eval.retrieval.bm25 import BM25Index
from jevgrep_eval.retrieval.jevgrep import JevgrepAdapter
from jevgrep_eval.scoring import score_retrieval
from jevgrep_eval.util import canonical_json, digest, normalize_path

CACHE = (ARGS.cache or (REPO / ".staging/corpus-inputs/repo-cache")).resolve()
BASES = (ARGS.bases or (REPO / ".staging/retrieval-bases")).resolve()
OUT = (ARGS.out or (REPO / "reports/retrieval-only-v1.json")).resolve()
ONLY = ARGS.tasks or TASKS


def metrics_dict(metrics) -> dict:
    return {
        "hit_at_k": metrics.hit_at_k,
        "recall_at_k": metrics.recall_at_k,
        "mrr": metrics.mrr,
        "evidence_recall_at_k": metrics.evidence_recall_at_k,
        "reference_count": metrics.reference_count,
        "reasons": metrics.reasons,
        "returned_context_bytes": metrics.returned_context_bytes,
    }


def entry_for(task: str) -> dict:
    spec = yaml.safe_load((REPO / f"corpus/tasks/{task}/task.yaml").read_text(encoding="utf-8"))
    repo_id = spec["repo_id"]
    sha = spec["base_sha"]
    statement = spec["statement"].strip()
    base = BASES / task
    okmark = BASES / f"{task}.ok"
    if not okmark.exists():
        if base.exists():
            shutil.rmtree(base)
        BASES.mkdir(parents=True, exist_ok=True)
        materialize_repo(CACHE / repo_id, sha, base)
        okmark.write_text("1", encoding="utf-8")
    refs = [normalize_path(p) for p in (spec.get("changed_files") or [])]
    evidence = [normalize_path(p) for p in (spec.get("gold_evidence_files") or [])]
    present = [p for p in refs if (base / p).exists()]
    present_evidence = [p for p in evidence if (base / p).exists()]

    entry = {
        "task_id": task,
        "repo_id": repo_id,
        "statement_digest": hashlib.sha256(statement.encode("utf-8")).hexdigest(),
        "reference_files": refs,
        "reference_files_missing_at_base": [p for p in refs if p not in present],
        "retrievers": {},
    }

    started = time.perf_counter()
    index = BM25Index.from_root(base)
    bm25_result = index.query(statement, k=K, task_id=task)
    bm25_metrics = score_retrieval(bm25_result, present, evidence_files=present_evidence)
    entry["retrievers"]["bm25"] = {
        "n_hits": len(bm25_result.hits),
        "first_paths": [hit.path for hit in sorted(bm25_result.hits, key=lambda h: h.rank)[:5]],
        "metrics": metrics_dict(bm25_metrics),
        "wall_s": round(time.perf_counter() - started, 3),
    }

    started = time.perf_counter()
    jg_result = JevgrepAdapter().query(statement, base, k=K, task_id=task)
    jg_metrics = score_retrieval(jg_result, present, evidence_files=present_evidence)
    entry["retrievers"]["jg"] = {
        "n_hits": len(jg_result.hits),
        "first_paths": [hit.path for hit in sorted(jg_result.hits, key=lambda h: h.rank)[:5]],
        "metrics": metrics_dict(jg_metrics),
        "wall_s": round(time.perf_counter() - started, 3),
    }
    return entry


def main() -> int:
    entries = [entry_for(task) for task in ONLY]
    payload = {
        "report_version": "retrieval-only-v1",
        "k": K,
        "query_basis": "task statement verbatim (no rewriting)",
        "retrievers": {
            "jg": "pinned @dzhng/jevgrep 0.4.3, provider=vercel (metered; --no-cache)",
            "bm25": "deterministic in-repository BM25 (local; no provider cost)",
        },
        "honesty": "retrieval-only metrics are mechanics diagnostics, not end-to-end task claims",
        "tasks": entries,
        "report_digest": "",
    }
    payload["report_digest"] = digest(payload, component="retrieval-only-report")
    content = canonical_json(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(content)
    for entry in entries:
        jg = entry["retrievers"]["jg"]["metrics"]
        bm = entry["retrievers"]["bm25"]["metrics"]
        print(
            f"{entry['task_id']}: jg hit@10={jg['hit_at_k']} recall={jg['recall_at_k']} "
            f"| bm25 hit@10={bm['hit_at_k']} recall={bm['recall_at_k']} "
            f"| refs(missing)={len(entry['reference_files'])}"
            f"({len(entry['reference_files_missing_at_base'])})"
        )
    print(f"artifact: {OUT} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
