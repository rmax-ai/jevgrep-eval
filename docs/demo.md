# Mock report

`reports/demo/simulated-fixture.json` is a committed protocol demonstration
generated from `reports/demo/input/mock-run.json`. It is labeled
`simulated-fixture` and contains no provider output, credentials, or efficacy
claim. The report exercises report serialization and digesting only.

Regenerate it offline with:

```bash
UV_OFFLINE=1 uv run jevgrep-eval report build \
  --runs reports/demo --demo \
  --out reports/demo/simulated-fixture.json
```
