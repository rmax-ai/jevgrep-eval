# Leakage controls

Materialized workspaces are extracted from an exact source revision without
`.git`, benchmark metadata, gold patches, or hidden tests. Manifests and
digests are computed runner-side and are never placed in the agent view.
Gold-swap invariance is tested by changing evaluator artifacts while checking
agent-visible bytes.

Tier A uses bubblewrap `--unshare-all`, a minimal filesystem, curated
file-level binary binds, and a bind of only the workspace. The negative DNS
and TCP connectivity probe is an artifact whose result is recorded per run.
Tier B keeps the provider network for Jevgrep while applying the same
filesystem minimization and deny-read probes.

**Agent web lookup (closed 2026-09-29, probe-verified).** The a0 smoke showed
the agent retrieving the upstream fix over the web (provider web-search MCP
tool), which would contaminate repository-retrieval measurement. Provider-side
web search is disabled and apps / browser / computer-use features are off for
every arm, and sandboxed command egress is routed through the managed network
proxy. Live verification (2026-09-29): (1) `curl https://api.github.com`
→ proxy 403 "domain is not on the allowlist"; (2) the same curl with
`--noproxy '*'` → DNS failure (no resolver outside the proxy); (3)
`getent hosts` → rc=2; (4) `curl https://ai-gateway.vercel.sh/` → HTTP 308
through the proxy. Direct egress is impossible, not merely discouraged.

**Arm-scoped Jevgrep exposure (2026-10-02, dq#117 review fold).** The Jevgrep
capability is declared per arm (`retrieval_tools: [jg]`) and is now
materialized per arm. Only jg-declaring arms receive the jg executable and the
rest of the node toolchain, the read-only provider-credentials mount
(`/codex-home/.config/jevgrep`), and the provider-domain egress allowlist.
Every other arm receives only the node runtime plus the Codex package that
executes the agent: `jg` does not resolve, no part of the `@dzhng/jevgrep`
package tree is mounted, credentials are absent, and the proxy carries no
domain allowlist. Deterministic tests pin both variants
(`tests/test_agent_bindings.py`, `tests/test_isolation_argv.py`,
`tests/test_live_dry_run.py`); `arm_isolation_probe_script()` records the
in-sandbox assertions and was executed live against the generated argv for
both variants (transcript: `reports/arm-isolation-probe-20261002.txt`).

Agent runs execute on the network-allowed tier with a fully cleared child
environment (`subprocess env={}`); only explicit `--setenv` values reach the
agent. An inherited `SSL_CERT_FILE` pointing outside the sandbox broke TLS
during validation (V4b). The recipe binds `/etc/ssl` and relies on system trust
roots.

Snapshots reject special files, escaping symlinks, `.git`, and policy-violating
paths. The runner hashes around a snapshot twice and captures patches in a
private throwaway git worktree. Stage 0.5 V4 (2026-09-29) validated the exact
recipes live: connectivity-fail, deny-read, Python test execution inside
Tier A, group-kill quiescence, and Tier-B provider reachability all pass
(evidence: `configs/isolation/tier_*.yaml` validation lines + ops records).
