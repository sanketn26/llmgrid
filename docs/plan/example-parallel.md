# Example: parallel launch investigation with streamed report

[Feature 15](../features/15-coding-release.md) · [Feature guide](../composable-agent-platform-plan.md)

## Goal and starting point

Split a fictional launch review into engineering, support, and rollback questions.
Each worker retrieves and verifies its own short finding using a child context and
its own model. Two workers run at a time; results retain input order even when their
work completes in a different order. Merge only completed findings with citations.

Stream the assembled report through an OpenAI-compatible SSE fixture, expose text
deltas, and require the final event before publishing. This fixture demonstrates
transport assembly; its stream content is predetermined, not a live synthesis model.
A deliberately unsupported question yields Stopped and the report assembler refuses
it rather than silently publishing a partial investigation.

| Action | Starting file / role |
| --- | --- |
| Reuse | Feature 13 `ParallelMap` and `CompatibleStream`, and feature 09 grounded research |
| Add | `examples/implementation/showcase_parallel.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

Write the file named in the starting-point table so the checklist below passes. This guide does not include a reference implementation.


## Run and inspect

After the features this showcase needs are in the packages:

```bash
.venv/bin/python examples/implementation/showcase_parallel.py
```

The feature guide checker does not run this showcase. Run the command above and compare it with the checklist.

The report lists engineering, support, and rollback in that order. Two visible chunks
assemble into the exact final response. Three findings plus one formatting stream cost
four model calls and three retrieval calls. The unsupported topic prevents publication.
Child contexts share the root budget; no independent worker can spend beyond it.

## Extend to live use

Inject a model factory per worker and use real retrievers. Retain a deliberate
policy for partial results; this recipe requires all workers to complete. Replace the
SSE fixture with a real compatible streaming client and distinguish preview text from
the final verified report. Recheck citations and claim support after live synthesis,
since formatting can introduce unsupported claims. Limit retrieved context per worker.

## Before moving on

- [ ] Observed worker concurrency reaches two and never exceeds it.
- [ ] Findings retain input order and cite their source IDs.
- [ ] All workers have independent models and share the root budget.
- [ ] Text deltas reconstruct the final response exactly.
- [ ] A stopped worker prevents final report assembly.
- [ ] Live integration additionally checks sibling cancellation and truncated streams.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
