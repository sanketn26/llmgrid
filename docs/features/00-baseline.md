# 00 — Baseline

> **Status: done** (verified 2026-11-17). The starting point: an offline tool agent that answers "What is 2 + 3?". Nothing to build.

[All features](README.md) · [01](01-budgeted-round.md) →

## Why

Every later feature grows this agent. Confirm it runs before changing anything.

## Expects

**Behavior (end to end)**

- `make demo` prints `The answer is 5.` and the call counts `2 1`.

**What is already in the tree**

| Package | State |
| --- | --- |
| `llmgrid.interfaces` | Contracts, including a flat `Budget` |
| `llmgrid.network` | `ScriptedModel` (offline) |
| `llmgrid.tools` | Tool registry and executor |
| `llmgrid.loops` | `ModelStep` and `ToolAgent`, which charge the `Budget` themselves (feature 01 moves this into `RunContext.invoke`) |
| `llmgrid.context`, `llmgrid.rag` | Import only; no behavior yet |

```bash
make setup
make check
make demo
```

## Acceptance

- [x] `make setup`, then `make check` and `make demo` pass.
- [x] The demo prints `The answer is 5.` and the call counts `2 1`.

## Unit tests

No new tests. The existing suite is the baseline.
