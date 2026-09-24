# 10. Testing and release

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- Offline tests use deterministic fakes and recorded provider fixtures. Live-provider tests are opt-in.
- The test matrix below lists the cases each layer must cover. Shared contract suites per protocol are described in [Interfaces](04-interfaces.md#proving-conformance).
- Each package has its own `pyproject.toml`; `make build` and `make smoke` are the source of truth for packaging.
- A short checklist applies to every change.

## Test matrix

| Layer | Cases that must be covered |
| --- | --- |
| Static typing | A valid sequence; an incompatible sequence is rejected; input and output variance; protocol conformance |
| Model contract | Finish-reason consistency; tool IDs; unsupported capabilities; unknown usage; cancellation; provider-state round trip; other providers' options ignored; no corrective calls |
| Tool contract | Bad JSON; bad fields or types; duplicate names; unknown tool; correlation; unexpected failure; each anticipated failure renders as its `ToolError`; decoder rejection uses `invalid_argument`; a repeated identical failure is flagged; an undeclared effect is treated as `non_idempotent`; `non_idempotent` tools are never retried; the idempotency key is stable across retries |
| Runtime | Nested shared budget; a child cannot exceed its parent; exhaustion exactly at the limit; zero and expired deadlines; parent cancellation; no hidden retry |
| Context | Scope isolation; evidence provenance; no dangling tool messages; provider state stays with its message; budget overflow; compaction trigger and target; compaction charged to the ledger; pinned content and the journal view survive; pinned overflow raises `ContextLengthError`; oversized output is offloaded with a handle; ranged read-back is bounded; a sub-agent's transcript is absent from the parent's history |
| Loop control | Every stop reason is reachable; ledger exhaustion overrides a `Continue` policy; an unbounded `Repeat` is rejected at construction; a goal verified on the last permitted iteration completes; a false claim never completes; `inconclusive` stops with its own reason; `None` readings neither reset nor advance patience; the critic's `Stop` binds; the critic's reserve survives an exhausted inner scope; guidance is visible in history; the critic failure policy; the per-iteration cap is enforced |
| Experiment loop | Rollback leaves the workspace byte-identical; a protected write is rejected; tampering through a side channel aborts and rolls back; a duplicate change is rejected before the run; an empty diff is aborted; the noise policy re-measures near-threshold candidates; commits are decided by code only; a tool with external effects is rejected at construction; resuming after a crash mid-run rolls back and never repeats a committed iteration; `no_regression` commits a non-empty diff with passing tests and rolls back an empty diff; `reset` iterations start with only pinned content, the task, and the journal view |
| MCP | Namespacing; duplicate rejection; untrusted hints ignored; server lifecycle closes on cancellation |
| Durable execution | Crash before and after dispatch; duplicate resume; stale approval; stale checkpoint; unknown outcome |
| Architecture | Import contracts; no SDK imported without its extra |
| Packaging | Wheel install; `py.typed`; each extra; no forbidden imports |

**How tests are written.**

- Use deterministic fakes for offline tests, and recorded provider wire fixtures for adapter tests.
- Live-provider tests are opt-in. They check integration behaviour, not exact generated prose.
- Negative typing tests put `# type: ignore[code]` on lines that must fail, with mypy's `warn_unused_ignores` (enabled by `strict`). If a line stops failing, the unused ignore fails the build. The [starter appendix](appendix-starter-code.md) has an example.
- Run lint, static typing, offline tests, and wheel builds on the supported Python versions: initially 3.12 and the newest stable release, with the CI versions chosen explicitly. Where compatibility is promised, test both the minimum and the current dependency sets.

## Packaging

Each package has its own `pyproject.toml`. For example, tools:

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "llmgrid-tools"
version = "0.1.0a1"
description = "Typed tool bindings and dispatch for llmgrid"
readme = "README.md"
requires-python = ">=3.12"
license = "MIT"
license-files = ["LICENSE"]
dependencies = ["llmgrid-interfaces>=0.1.0a1,<0.2"]

[project.optional-dependencies]
mcp = ["mcp>=1.0"]          # when llmgrid.tools.mcp lands

[tool.hatch.build.targets.wheel]
# `llmgrid` is a namespace package shared by every distribution: no llmgrid/__init__.py.
packages = ["src/llmgrid"]
```

- **Planned extras:** `llmgrid-network[anthropic]`, `llmgrid-network[openai]`, `llmgrid-network[gemini]` (each bringing `httpx`), later `llmgrid-network[bedrock]`; `llmgrid-tools[mcp]`; `llmgrid-loops[otel]`. Check every version floor when the extra is implemented; the numbers are placeholders.
- Whether `httpx` is a hard dependency of `llmgrid-network` or only of its extras is open (Q-05).
- Each package copies the repository `LICENSE` so it ships in the sdist and the wheel.
- Consumers must not need a particular workspace manager. The Makefile uses a plain virtualenv and pip; `make build` and `make smoke` are the source of truth for packaging.
- Release order and version ranges are in [Packages](03-packages.md#versioning).

## Checklist for every change

- Does it add a dependency between packages? Does the architecture test still pass?
- Does a real consumer need every new interface?
- Are its behavioural guarantees documented and tested?
- Does a nested composition inherit cancellation and resource limits?
- Does any code path call a model or tool without a ledger reservation?
- Can expected domain errors be told apart from bugs?
- Does the public schema match the runtime decoder?
- Does the example run from the installed package?
- Does it change a decision in the [decision log](02-decisions.md)? If so, update the log and the ADR in the same change.
