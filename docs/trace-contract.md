# Trace contract — protocol v1 (FROZEN 2026-09-29)

Status: **FROZEN** from live Stage-0.5 probes (codex-cli 0.157.1, direct `codex exec`
route). Replaces the W1a DRAFT. A provider-schema or launcher change requires a new
protocol ID. Fidelity rule throughout: unknown event types and line-parse failures are
retained as named partial coverage — never silently discarded.

The engine consumes three record shapes:

1. **Exec event stream** — `codex exec --json` stdout (the primary live parse source).
2. **Session rollout file** — `<CODEX_HOME>/sessions/<Y>/<M>/<D>/rollout-<iso>-<uuid>.jsonl`
   (accounting/quota enrichment and offline trace study).
3. **Mock/fixture protocol** — the committed offline suite shape.

## 1. Exec event stream (`--json` stdout, v0.157.1)

One JSON object per line, no envelope.

| type | payload | notes |
|---|---|---|
| `thread.started` | `thread_id` (uuid) | session association |
| `turn.started` | — | |
| `item.started` | `item{...}` | in-progress item |
| `item.completed` | `item{...}` | terminal item |
| `turn.completed` | `usage{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens}` | terminal marker + usage |

`item.type ∈ {agent_message{id, text}, command_execution{id, command(str),
aggregated_output, exit_code, status}}`. `command` is one shell string, e.g.
`/bin/bash -lc 'printf %s three > gamma.txt'` (note: shell-quoted, not argv).

Limits of this stream: **no rate limits and no per-response token records** — quota and
accounting enrichment use the rollout file (§2).

## 2. Session rollout file (v0.157.1)

Envelope per line: `{timestamp, ordinal, type, payload}`. Types:
`session_meta | turn_context | world_state | event_msg | response_item | token_usage_record`.

- `session_meta` — `session_id`/`id`, `timestamp`, `cwd`, `runtime_workspace_roots`,
  `originator`, `cli_version`, `source`, `thread_source`, `model_provider`,
  `history_mode`, `context_window{window_id}`, `base_instructions{text}`.
- `turn_context` — `turn_id`, `root_turn_id`, `cwd`, `workspace_roots`,
  `model` (resolved), `effort`, `approval_policy`,
  `sandbox_policy{type, network_access}`, `collaboration_mode.settings{model, reasoning_effort}`.
- `event_msg.payload.type`:
  - `task_started` — `turn_id`, `root_turn_id`.
  - `item_completed` — `item{...}`, `started_at_ms`, `completed_at_ms`.
    `item.type ∈ {UserMessage, Reasoning, AgentMessage, CommandExecution}`.
    `CommandExecution` = `id`, `process_id`, `command[argv]`, `cwd` (file:// URI),
    `parsed_cmd[{type, cmd}]`, `source`, `status`, `stdout`, `stderr`,
    `aggregated_output`, `exit_code`, `duration{secs, nanos}`, `formatted_output`.
  - `token_count` — `info{total_token_usage{...5 fields + total_tokens},
    last_token_usage{...}, model_context_window}`,
    `rate_limits{limit_id, primary{used_percent, window_minutes, resets_at},
    secondary{...}, credits, plan_type}`.
  - `task_complete` — `turn_id`, `last_agent_message` (terminal marker).
- `response_item.payload.type`:
  - `message{role: developer|user|assistant, content[{type, text}]}`
  - `reasoning{id, summary_text[], raw_content[]}`
  - `custom_tool_call{id, status, call_id, name ("exec"), input}` — `input` is a small
    JS script embedding `tools.exec_command({cmd, workdir, max_output_tokens})`.
  - `custom_tool_call_output{id, call_id, output[{type, text}]}` — pairs by `call_id`;
    `exit_code=N` appears in the output text.
  - `function_call` / `function_call_output` — legacy path; treat as known.
- `token_usage_record` — `thread_id`, `turn_id`, `session_id`, `root_turn_id`,
  `response_id`, `usage{...}`, `turn_token_usage{...}`, `thread_token_usage{...}`.
- `world_state` — `{full, state{...}}` config snapshot; **not a tool event** (must not
  degrade coverage).

## 3. Normalized mapping (adapter requirements)

**From the exec stream** — each `command_execution` item ⇒ one `ToolEvent`
(`kind=classify_command(command)`, `cmd_digest`, `cmd_scrubbed`, `exit_code`,
`result.summary=aggregated_output`, `completed` per `status`); started/completed pair by
`item.id`; `agent_message` items are not tool events; `turn.completed` ⇒ token record +
terminal marker; `thread.started` ⇒ session association.

**From the rollout file** — prefer `CommandExecution` items (take the `bash -lc` script
as the command string for classification). `custom_tool_call name="exec"` is a *secondary*
source used only when an execution has no `CommandExecution` item; `name="apply_patch"`
⇒ `edit`. Pair by `call_id` where present. Tokens from `token_count.info` and
`token_usage_record.usage`; quota from `rate_limits{primary, secondary, plan_type,
credits}`. Session = `session_meta.session_id`; every item carries `thread_id`/`turn_id`.

Rules:

- **R1** — classify from the executable string only; never execute.
- **R2** — scrub + digest every command (`scrub_command` + sha256); raw bytes stay in
  private run artifacts only.
- **R3** — missing start/end pairing, missing terminal marker, missing session
  association ⇒ named partial.
- **R4** — `world_state`, `turn_context`, `reasoning`, usage records are **known
  non-tool records**: parse and retain, zero coverage degradation.
- **R5** — unknown `payload.type` ⇒ partial dimension `known_event_types` + retain raw.

### 3.1 Adapter metadata (`TraceParse.provider_meta`)

Adapters populate a `provider_meta` dict (default empty; existing consumers unaffected):

```json
{
  "source": "codex-stream | codex-rollout",
  "session_id": "…",
  "cli_version": "… | null",
  "model_provider": "… | null",
  "model": {"resolved": "… | null", "effort": "… | null"},
  "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
            "reasoning_output_tokens": 0, "total_tokens": 0},
  "rate_limits": {"…": "rollout only; null for the exec stream"}
}
```

Stream source fills `source`, `session_id` (thread id), and `usage`
(`total_tokens = input_tokens + output_tokens`); rollout source fills all fields
from `session_meta` / `turn_context` / `token_count`.

## 4. Coverage

`full` only when: every line parses, session association known, terminal marker present,
start/end pairing complete, token basis present. Otherwise `partial` with named missing
dimensions; dependent metrics are `indeterminate` (existing `derive_metrics` semantics).

## 5. Fixtures (committed, sanitized, live captures)

`tests/fixtures/codex-0.157.1/`:

| fixture | raw sha256 | fixture sha256 | notes |
|---|---|---|---|
| `fixture-exec-stream.jsonl` | `2fb7561ce2508ea0…` | `e2d4aa4241a38bcd…` | live `--json` stdout; path substitutions only |
| `fixture-route-a.jsonl` | `f3ad3ddaf42f7aba…` | `4fef8f2068e5dd0c…` | live rollout, bare route; instruction bodies redacted, account ids redacted, paths substituted, all numerics unchanged |
| `fixture-route-b.jsonl` | `5377b619acf8664e…` | `0f1aede22c116bdf…` | live rollout, tracked route; identical schema (route-shape equality evidence) |

Sanitization is documented and structure-preserving. Tests assert against these live
fixtures; no fixture exists that the engine did not actually observe.

## 6. Route / protocol identity

See `docs/provenance.md` § Launch protocol. All live runs use the frozen argv and
minimal environment; run artifacts capture `cli_version` + `model_provider` from the
rollout header for protocol-ID verification.
