# Feature implementation guide

Build one end-to-end feature at a time. Each feature guide says what the feature
expects, gives the unit test that locks that behavior, and states the acceptance
criteria. It does not include a reference implementation. The packages still
contain the prototype. Writing the files named in the guide is the work.

The task that uses this order is [task.md](task.md). The guides are in
[features/](features/).

| Feature | What works when it is done | Check |
| --- | --- | --- |
| [00](features/00-baseline.md) | The current demo answers `2 + 3` | `make demo` and `make check` |
| [01](features/01-budgeted-round.md) | One tool round charges each call once, and a child cannot spend a held slice | `test_nested_budget.py`, `test_single_charge.py` |
| [02](features/02-verified-answer.md) | `2 + 3` is `Completed` with text `5`, and a false claim stops | `test_verified_agent.py` |
| [03](features/03-replay.md) | Replay matches that outcome and does not run the tool again | `test_replay.py` |
| [04](features/04-provider-roundtrip.md) | The same tool call round-trips through five offline adapters | `test_provider_roundtrip.py` |
| [05](features/05-guardrail.md) | A denied tool is reported and not executed. An input denial charges nothing | `test_guardrails.py` |
| [06](features/06-resample.md) | A rejected result is retried. A budget error is not | `test_resample.py` |
| [07](features/07-refiner.md) | An unapproved draft is never returned | `test_refine.py` |
| [08](features/08-route-and-errand.md) | A known label routes, an unknown label errors, a two-part errand recomposes | `test_route_errand.py` |
| [09](features/09-grounded-answer.md) | An answer must cite stored evidence | `test_grounded.py` |
| [10](features/10-context.md) | Compaction keeps the pinned system message and the newest turn | `test_context_window.py` |
| [11](features/11-experiment.md) | A rejected review stops. Three rounds raise a score without writing `grader` | `test_review.py`, `test_experiment.py` |
| [12](features/12-mcp-tool.md) | One allowed MCP tool runs against a fake session | `test_mcp_source.py` |
| [13](features/13-parallel-stream.md) | Parallel results stay in order. One stream charges one model call | `test_parallel_stream.py` |
| [14](features/14-approval.md) | An approved action is sent once. An uncertain send is not repeated | `test_approval.py` |
| [15](features/15-coding-release.md) | The seeded `clamp` bug is fixed under an independent verifier | `test_coding_repair.py`, then `make check` |

Design notes for guardrails, errands, and routers stay in
[capabilities-guardrails-errands-routing.md](plan/capabilities-guardrails-errands-routing.md).
Showcases in [plan/](plan/) repeat a finished feature as a goal and a checklist. They do not include a reference program.

## How to use it

1. Run feature 00. Python 3.12 or later. `make setup`, then `make check` and `make demo`.
2. Read the feature's **Expects**, **Unit tests**, and **Acceptance**. Write the named files yourself.
3. Do the next feature only after the acceptance criteria pass. A failed test is the next turn.
4. Update the existing package tests named in the feature when a public type changes, then run `make check`.
5. The guide checker confirms that every feature has those three sections, that features 01–15 each contain a unit-test block, that every Python fence in a feature guide is one of those tests, that the tests compile, and that showcase files contain no Python program. It does not implement a feature or run its tests.

```bash
.venv/bin/python tools/check_implementation_guide.py
```

## Package rules

- `llmgrid.interfaces` uses only the standard library.
- Other packages import interfaces and their own package, not sibling packages.
- Application code creates clients and injects them into steps.
- Leaf dispatch charges calls before execution and preserves cancellation.
- Guardrail denials, routing failures, and exhausted resampling raise distinct errors. Nothing falls back silently.
- Completion, partial results, expected provider failures, and suspension stay distinct.

## Adjustments

Keep a change beside the feature it affects:

```markdown
Adjustment: <changed API or implementation>
Reason: <one sentence>
Affected files: <paths>
```

Call-count budgets and text or tool input are in scope. Token and money limits,
multimodal input, and streaming for the adapters other than Chat Completions are not,
until a feature adds them and a test covers them.
