# Example: measurable scheduling improvement

[Feature 15](../features/15-coding-release.md) · [Feature guide](../composable-agent-platform-plan.md)

## Goal and starting point

Schedule jobs lasting 8, 7, and 5 minutes on two workers. Start with all jobs on one
worker (20 minutes), propose schedules, measure makespan, and preserve the best.
A worse proposal is rolled back. The loop maximizes scores, so score is negative
makespan. A fixed evaluator validates every assignment and reports worker loads.

Offline model responses are predetermined proposals; the example demonstrates the
optimization recipe, not autonomous discovery. A protected task file, durable round
journal, and explicit measurements make progress independently inspectable.

| Action | Starting file / role |
| --- | --- |
| Reuse | Feature 11 `ExperimentLoop`, `MemoryWorkspace`, and journals, and feature 02 `ModelStep` |
| Add | `examples/implementation/showcase_improvement.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

Write the file named in the starting-point table so the checklist below passes. This guide does not include a reference implementation.


## Run and inspect

After the features this showcase needs are in the packages:

```bash
.venv/bin/python examples/implementation/showcase_improvement.py
```

The feature guide checker does not run this showcase. Run the command above and compare it with the checklist.

Output progresses from 20 to 13 to 12 minutes and rejects a 15-minute proposal.
Print round evidence and the final assignment rather than an unsupported “improved”
claim. Reloading the journal restores usage; the in-memory workspace remains alive
in this fixture. Process restart additionally requires persisting its best snapshot.

## Extend to live use

Inject a live model into the proposer, include prior measurement evidence in its
prompt, and bound rounds and calls. Add more jobs and compare against a deterministic
scheduling baseline. Persist workspace snapshots for restart, and use the feature 11 critic
contexts if adding a reviewer. Do not claim optimality: this fixture proves improvement
and rollback, not a general optimizer or an exhaustive search.

## Before moving on

- [ ] Scores correspond to measured makespan, not model self-assessment.
- [ ] Worse proposals restore the previous best schedule.
- [ ] Invalid worker IDs fail validation.
- [ ] Protected task data stays unchanged.
- [ ] Reloaded journal usage matches all three proposals and four evaluations.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
