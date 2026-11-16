# Example: record and replay a coding-agent failure

[Feature 15](../features/15-coding-release.md) · [Feature guide](../composable-agent-platform-plan.md)

## Goal and starting point

Record a coding agent that runs the tests and then repeatedly claims it fixed the
bug without editing. Independent verification rejects the claims and the agent stops
for no progress. Print the failed tool output and recorded model claims, then replay
exactly those interactions without repeating recorded tool execution.

The verifier remains independent and reruns its tests during replay. The example
counts evaluator invocations to prove the distinction. Changed input must fail exact
replay matching instead of quietly borrowing a response from a different run.

| Action | Starting file / role |
| --- | --- |
| Reuse | Feature 03 model and tool recording and replay; feature 15 coding fixture and independent tests |
| Add | `examples/implementation/showcase_replay.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

Write the file named in the starting-point table so the checklist below passes. This guide does not include a reference implementation.


## Run and inspect

After the features this showcase needs are in the packages:

```bash
.venv/bin/python examples/implementation/showcase_replay.py
```

The feature guide checker does not run this showcase. Run the command above and compare it with the checklist.

The first run executes the evaluator four times. Replay consumes recorded model and
tool records and executes only the three independent verifier evaluations: the total
counter becomes seven. Both runs have the same no-progress outcome and logical budget
usage. This is replay-based debugging, not proof that rerunning a live model would
produce the same answers.

## Extend to live use

Keep capture opt-in and redact sensitive inputs before persistent storage. Feature
03 records are in-memory dataclasses; durable recordings need a versioned serializer,
model capabilities, and tool specifications. Preserve the exact normalized requests.
For recorded writes, restore the candidate state explicitly before verification, since
ReplayTools returns saved results without writing files. For nondeterministic verifiers,
record their evidence separately and label evidence replay versus fresh verification.

## Before moving on

- [ ] Recorded test output shows the seeded bug.
- [ ] Three unsupported completion claims lead to no progress.
- [ ] Exact replay reproduces the full outcome and usage.
- [ ] Recorded tools have no repeated execution.
- [ ] Independent verification still runs during replay.
- [ ] Changed prompt rejects replay before consuming unrelated records.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
