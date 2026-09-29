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
tool), which would contaminate repository-retrieval measurement. The capability
set is now uniform across arms: provider-side web search disabled, apps /
browser / computer-use features off, and sandboxed command egress routed
through the managed network proxy with a single allowlisted host — the frozen
Jevgrep provider gateway. Live verification: (1) `curl https://api.github.com`
→ proxy 403 "domain is not on the allowlist"; (2) the same curl with
`--noproxy '*'` → DNS failure (no resolver outside the proxy); (3)
`getent hosts` → rc=2; (4) `curl https://ai-gateway.vercel.sh/` → HTTP 308
through the proxy. Direct egress is impossible, not merely discouraged.

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
