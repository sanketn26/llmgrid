# Feature guides

The project grows one offline tool agent, one feature at a time, into a verified
coding agent. Each guide is a **contract**, not an implementation: it says what to
build, the rules, and how you know it is done. Work through them in order; each
starts from the running result of the one before.

## How to read a guide

Every guide has the same shape:

1. **One-line summary** and **Why** — what the feature is for.
2. **Expects** — the end-to-end behavior, the rules, the files to write, and what else to update.
3. **Acceptance** — a checklist. The feature is done when every box is true.
4. **Unit tests** — the exact test modules. Copy them in; they fail until the feature exists.

`make check` stays green after every feature that changes a public type.
No feature needs a provider credential or network access.

## The features

| # | Feature | Done when |
| --- | --- | --- |
| [00](00-baseline.md) | Baseline ✅ | `make demo` prints `The answer is 5.` |
| [01](01-budgeted-round.md) | Nested budget ✅ | A child cannot spend a held slice; each call is charged once |
| [02](02-verified-answer.md) | Verified answer | `2 + 3` is `Completed` with `5`; a false claim is `Stopped` |
| [03](03-replay.md) | Replay | Replay matches the outcome without rerunning the tool |
| [04](04-provider-roundtrip.md) | Provider adapters | One tool call round-trips through five offline adapters |
| [05](05-guardrail.md) | Guardrails | A denied tool is reported, not run; an input denial costs nothing |
| [06](06-resample.md) | Resampling | A rejected result is retried; a budget error is not |
| [07](07-refiner.md) | Refiner | An unapproved draft is never returned |
| [08](08-route-and-errand.md) | Routing and errands | Unknown label errors; a two-part plan recomposes |
| [09](09-grounded-answer.md) | Grounded answer | Answers must cite retrieved evidence |
| [10](10-context.md) | Context compaction | Pinned system message and newest turn survive |
| [11](11-experiment.md) | Review and experiments | Score rises over three rounds; `grader` untouched |
| [12](12-mcp-tool.md) | MCP tool | Only allowed MCP tools run |
| [13](13-parallel-stream.md) | Parallel and streaming | Parallel results stay ordered; one stream = one model call |
| [14](14-approval.md) | Approval | An approved action is sent once; an uncertain send is not repeated |
| [15](15-coding-release.md) | Coding agent + release | The `clamp` bug is fixed under an independent verifier; release checks pass |

## Checking the guides

```bash
.venv/bin/python tools/check_implementation_guide.py
```

This checks the guides' structure and that the test blocks compile. It does not
run the feature tests.
