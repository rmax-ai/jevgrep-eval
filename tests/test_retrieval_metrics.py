from jevgrep_eval.models import RetrievalHit, RetrievalResult
from jevgrep_eval.retrieval.metrics import calculate_metrics


def test_first_unique_file_metrics():
    result = RetrievalResult(
        task_id="t",
        backend="bm25",
        hits=[
            RetrievalHit(path="a.py", rank=1),
            RetrievalHit(path="./a.py", rank=2),
            RetrievalHit(path="b.py", rank=3),
        ],
    )
    metrics = calculate_metrics(result, ["a.py", "b.py"])
    assert metrics.hit_at_k == 1.0
    assert metrics.recall_at_k == 1.0
    assert metrics.mrr == 1.0


def test_empty_reference_is_na():
    metrics = calculate_metrics(RetrievalResult(task_id="t", backend="bm25"), [])
    assert metrics.hit_at_k is None
    assert metrics.reasons
