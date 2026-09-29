# Provenance

The pinned Jevgrep adapter targets `@dzhng/jevgrep@0.4.3`, licensed MIT.
W1b does not include the external package, credentials, provider data, or a
live install receipt. Public source candidates are represented by exact SHA
references in `corpus/repos.lock.yaml`; local admission receipts identify the
operator-staged cache mechanism and network-denial probe.

The deterministic BM25 chunking and index shape reuse the public
`rmax-ai/bm25-vfs-ablation` approach at commit
`91e6c38303cf1aed4a7f402f29b4055a00b8d218`. The reuse is limited to the
chunk/index mechanics; this repository makes no production retrieval-policy
claim.

All mock artifacts are marked `simulated-fixture` and are protocol
demonstrations only. Pricing and live tool identity remain frozen during the
later Stage 0.5 probes.

## Launch protocol identity (frozen 2026-09-29 — Stage 0.5 V3)

Live agent runs use the direct `codex exec` route (bare) in a minimal
environment. Frozen argv:

```
codex exec -C <workspace> -s workspace-write --skip-git-repo-check --json \
  -m gpt-6-luna -c model_reasoning_effort=max <prompt>
```

Environment allowlist: `PATH HOME LANG LC_ALL TZ` (HOME/CODEX_HOME resolved on
the run host).

Identities: codex-cli `0.157.1`; launcher module `@openai/codex`
(`bin/codex.js`, sha256 `61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70`);
user config sha256 `898e81a8896ec9401e7d51d9fa96dd3bcf574db687d4c7be0004ad5c3057dc56`
(model `gpt-6-luna`, reasoning effort `max`).

Evidence: the bare route and the host's tracked launcher (`codexq`) produced
identical rollout schemas and durations on the same tiny task (22 s / 15 s);
fixtures `fixture-route-a/b.jsonl`. The tracked launcher is used on this host
for auxiliary tracking only (not the protocol route) and requires
`--extra "--skip-git-repo-check"` for `.git`-free workspaces — the bare route
requires `--skip-git-repo-check` and refuses to run without it (verified).
Any launcher, flag, model, or effort change requires a new protocol ID.
