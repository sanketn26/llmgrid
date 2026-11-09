# Phased Python implementation guide

Start at Phase 0 with no assumed setup or repository knowledge. It identifies the
pre-existing code, creates the environment, and runs the baseline. Then follow the phases in order. Each phase gives the target file, its types and method
bodies, a runnable offline example, and the checks needed before moving on.
Adjust signatures and implementations together as you build.

The code in these Markdown files is a proposed reference implementation. The actual
packages still contain the existing prototype; writing this guide does not install
its future APIs into the library.

| Phase | Build |
| --- | --- |
| [0](plan/phase-0-baseline.md) | Set up from zero, inventory/reuse existing code, and run the baseline |
| [1](plan/phase-1-contracts.md) | Nested budgets, context dispatch, model values, verification contracts |
| [2](plan/phase-2-providers.md) | All five adapters, serializers, continuation state, and client lifecycles |
| [3](plan/phase-3-tool-agent.md) | Verified tool agent, outcomes, stopping, recording, and replay |
| [4](plan/phase-4-composition.md) | Retrieval, context, review, MCP, artifacts, experiments, critic, and tree search |
| [4+](plan/phase-4-safety-patterns.md) | Addendum: guardrails, errands, planner, refiners, resampling, and routers |
| [5](plan/phase-5-streaming.md) | Stream assembly, bounded parallel steps, and telemetry |
| [6](plan/phase-6-recovery.md) | Approval, durable checkpoints, and uncertain-action recovery |
| [7](plan/phase-7-examples.md) | Runnable showcases: coding, research, improvement, approval, providers, parallel work, and replay |
| [8](plan/phase-8-release.md) | Verify the guide, run checks, and package the implementation |

Design notes for these capabilities, and for self-improving agents (the user's ask as the
invariant, the agent's policy as the variable), are in
[capabilities-guardrails-errands-routing.md](plan/capabilities-guardrails-errands-routing.md).

## How to use it

1. Complete Phase 0 with Python 3.12 or later. Use the current checkout or copy its
   baseline into a new project directory using the provided script.
2. Read each phase's “Starting point” table, then copy its file blocks into the stated
   paths. “Keep” means reuse existing code; “Replace” means update a baseline file;
   “Add” means create a new file. A later phase may replace an earlier file.
3. Run the phase example before changing the implementation for your needs.
4. Update existing callers/tests for each API migration and run the package checks.
5. Update that phase's code and example when your implementation changes.

Only protocol methods use `...`. Concrete method bodies are supplied. Small wiring
snippets identify application-provided objects; they are separate from file blocks.
Optional provider clients need their dependencies and credentials for live checks.

You can verify the file blocks now, in a temporary checkout:

```bash
.venv/bin/python tools/check_implementation_guide.py
```

## Package rules

- `llmgrid.interfaces` uses only the standard library.
- Other packages import interfaces and their own package, not sibling packages.
- Application code creates clients/services and injects them into steps.
- Leaf dispatch charges calls before execution and preserves cancellation.
- Guardrail denials, routing failures, and exhausted resampling raise distinct errors; no fallback is implicit.
- Completion, partial results, expected provider failures, and suspension stay distinct.

## Adjustments

Keep changes beside the phase they affect. One short note is enough:

```markdown
Adjustment: <changed API or implementation>
Reason: <one sentence>
Affected files: <paths>
```

The reference starts with call-count budgets and text/tool provider input. Hard token
and cost limits, richer provider options, multimodal serialization, and the remaining
native streaming assemblers need additional implementation and fixtures. These are
explicit extensions, not capabilities claimed by the examples.
