# W1c trace adapter report

## Implemented

- Added codex-cli 0.157.1 stream and rollout adapters plus first-parseable-line
  auto-detection.
- Added centralized command unwrapping/classification support and `TraceParse.provider_meta`.
- Routed the runner through `parse_trace`.
- Updated Codex invocation assembly to the frozen JSON/sandbox/config argv.
- Added fixture, partial-coverage, fallback, compatibility, and argv tests.

## Spec deltas and limitations

No intentional spec deltas. A rollout `custom_tool_call` named `exec` is a
secondary fallback only when the trace contains zero `CommandExecution` items.
The fallback extracts the embedded `cmd` and pairs any output by `call_id`;
mixed traces therefore prefer the authoritative `CommandExecution` records.

## Validation

- Frozen fixture SHA-256 verification: all three expected hashes matched.
- `UV_OFFLINE=1 uv sync --frozen`: passed, 13 packages checked.
- `export PATH="$HOME/.local/bin:$PATH"; uv run pytest -q`: **67 passed**.
- `export PATH="$HOME/.local/bin:$PATH"; uv run ruff check .`: passed.

No ambiguities remain.
