# Task

Take the offline tool agent that answers "What is 2 + 3?" and grow it, one feature
at a time, until a verified coding agent can repair a seeded bug. The order is the
feature guide in [composable-agent-platform-plan.md](composable-agent-platform-plan.md).
Do not implement the old horizontal phases. Those files are gone.

Each feature guide is a contract: what it expects, the unit test, and the acceptance
criteria. It is not an implementation. A feature is done when its acceptance criteria
pass. `make check` stays green after every feature that changes a public type.

```bash
.venv/bin/python tools/check_implementation_guide.py
```

That command checks the guides. It does not run the feature tests. Those tests fail
until the feature is written.

## Why this shape

A feature is one behavior a caller can run: a charged tool round, a verified sum,
a replay, one guarded tool, a cited answer. The interfaces, the package that uses
them, and a unit test land together. The next feature starts from that running
behavior, which is what makes the work more than one turn.

## Features and checks

| # | Done when |
| --- | --- |
| 00 | `make demo` prints `The answer is 5.` and `make check` passes. |
| 01 | A child budget cannot spend a held sibling slice. One tool round charges each model call and each tool call once. `make demo` still prints the answer. |
| 02 | The scripted `add` run returns `Completed` with text `5` and usage `(2, 1)`. Three claims of `wrong` return `Stopped` with `no_progress` and do not call the tool. |
| 03 | Replay equals that `Completed` outcome. The real tool ran once. A mismatched replay call raises and does not run the tool. |
| 04 | `test_provider_roundtrip.py` passes. Five offline adapters round-trip the same tool call and the tool result `5`. No socket and no API key. Provider state survives on every adapter except the OpenAI-compatible one. |
| 05 | An input denial charges nothing. A denied tool call is an error result, is not executed, and still costs one tool call. |
| 06 | `bad` then `ok!` returns `ok!` after two runs. `BudgetExceededError` is not retried. |
| 07 | An approved revision is returned. An unapproved draft is not. |
| 08 | An unknown label raises `RoutingError`. A two-part plan recomposes. An empty plan raises `ContractError`. |
| 09 | Citation `s1` completes. Citation `invented` stops with `claimed_unverified`. |
| 10 | Compacting three messages to two keeps the pinned system message and the newest turn. Artifact search returns the matching line. |
| 11 | `test_review.py` and `test_experiment.py` pass. A one-round review that never accepts is `Stopped`. Three experiment rounds reach score 3 and leave `grader` unchanged. The tree has four nodes. |
| 12 | A fake MCP session runs `add` and does not run an unknown tool. |
| 13 | `test_parallel_stream.py` passes. `ParallelMap` of doubling over `(3, 1, 2)` returns `(6, 2, 4)`. The canned stream ends on finish `stop` and `model_calls == 1`. |
| 14 | `test_approval.py` passes. The approved action is sent once. A checkpoint left in `sending` resumes as `unknown` and is not sent. A stale save raises `CheckpointConflict`. A stale digest raises `ValueError`. `restore_used` applies only to a fresh root. |
| 15 | `test_coding_repair.py` passes. The `clamp` repair passes the independent verifier. A false "fixed" claim and a budget that cannot pay for the edit do not report success. `make check`, `make build`, and `make smoke` pass. |

## Reviewer

Run the check named in the feature file for the last feature the session claims
to have finished, then `make check`. The demo answer stays `5` through feature 02,
after which the demo returns that answer through `Completed`. No feature requires
a provider credential.
