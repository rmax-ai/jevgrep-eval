# W1b corpus

The committed corpus contains 56 frozen public candidates from 13 repositories.
Each candidate records an exact base SHA, fix SHA, gold patch, hidden-test patch,
admission evidence, sanitization review, and a per-file SHA-256 manifest.

The offline admission gate admitted 22 tasks:

- dev: 12 admitted tasks from Click, Jinja, and Pluggy;
- holdout: 10 admitted tasks from Immer, tqdm, and Zod;
- 34 candidates remain rejected with their reasons retained in `admission.json`.

The holdout split contains 41 frozen candidates, exceeding the 24-candidate
selection target, but only 10 were admissible with the operator-staged caches.
Requests, HTTPX, tomlkit, Ky, Zustand, Execa, and several Python/JS candidates
are retained as rejected evidence. They are not eligible for scoring. Adding
them requires an operator to stage the missing dependencies, browser binaries,
or submodule data and then rerun the admission protocol. No live fetch is
performed by tests.

`corpus/manifest.json` binds every task definition and evaluator artifact to
its digest. `gold.patch`, `hidden_tests.patch`, `gold-evidence.json`, and
admission records are evaluator-side inputs. Source workspaces are created by
`materialize()` from the exact base revision and contain no `.git`, gold, or
hidden-test data.

Statements were reviewed against changed paths, fix-only symbols, patch text,
stack traces, issue identifiers, and host paths. The task statement is the
only agent-facing task description.

## Rejection matrix

| Primary reason | Candidates | Examples |
| --- | ---: | --- |
| Missing or unusable offline dependency/cache material | 18 | HTTPX, Requests, tomlkit submodule, Ky/Zustand browser or Node overlays, Execa |
| Admission behavior gate failed | 16 | Hidden test did not separate pristine base from gold, or the frozen upstream slice did not pass |

Counts are by candidate, while each `admission.json` retains all observed
reasons and repetitions. Rejected candidates are never silently promoted.
