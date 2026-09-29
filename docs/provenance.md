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
