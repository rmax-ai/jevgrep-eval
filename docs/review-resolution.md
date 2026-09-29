# W1a review resolution

The W1b hardening pass resolved all three blockers and all nine majors from the
operator review.

| Item | Resolution |
| --- | --- |
| B1 | Envelope verification now requires retained bytes, recomputes every digest, checks identity bindings, and validates ordered parent links. Wipe and mutation tests fail closed. |
| B2 | Metadata filtering is path-scoped. Nested evaluator paths such as `corpus/gold` and `corpus/hidden` are excluded without deleting legitimate source directories named `gold`, `corpus`, or `runs`. |
| B3 | Jevgrep honors valid emitted ranks, verifies duplicate/partial rank columns, and records unordered semantics instead of inventing a rank. |
| M4 | BM25 query tokens are sorted before scoring. |
| M5 | Evaluator commands run in new process groups and kill/reap descendants on timeout. |
| M6 | Upstream and hidden evaluator commands are separate inputs and are retained in the evaluator digest. |
| M7 | Hidden-test failures map to localization or incorrect-implementation classes; malformed patches, regressions, environment failures, and timeouts remain distinct. |
| M8 | Missing dollar components propagate `unknown` into combined modeled cost. |
| M9 | Runner execution persists the envelope, stage records, run record, tree digests, patch digest, and evaluator result. |
| M10 | Trace coverage is partial when session association, terminal markers, or start/end pairing are missing. |
| M11 | Resume returns a persisted run, environment failures can retry once in a new run id, and forced-first/noncompliance flags are recorded. |
| M12 | Quiescent snapshots hash three times with a settle interval between observations. |

The remaining minor items are either explicit protocol limitations or outside
the offline W1b acceptance boundary. They are not presented as validated
production isolation or live-provider claims.
