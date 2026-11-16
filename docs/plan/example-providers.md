# Example: one research workflow across five provider adapters

[Feature 15](../features/15-coding-release.md) · [Feature guide](../composable-agent-platform-plan.md)

## Goal and starting point

Run the same question, document, verifier, and call limits through five actual
adapter classes backed by provider-shaped response fixtures. Compare normalized
outcomes and usage in a table. Repeat each adapter with an invented citation to
show that application verification does not depend on provider response format.

This is an adapter portability demonstration. Fixtures provide no evidence about
real model quality, latency, price, or current provider availability.

| Action | Starting file / role |
| --- | --- |
| Reuse | Feature 04 adapters and the feature 09 grounded research workflow |
| Add | `examples/implementation/showcase_providers.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

Write the file named in the starting-point table so the checklist below passes. This guide does not include a reference implementation.


## Run and inspect

After the features this showcase needs are in the packages:

```bash
.venv/bin/python examples/implementation/showcase_providers.py
```

The feature guide checker does not run this showcase. Run the command above and compare it with the checklist.

The table has ten rows: five Completed fixture runs and five Stopped invalid-citation
runs. Every row uses one model call and one retrieval call. The transport captures the
actual serialized request and the assertions check that the common question survived
encoding.

## Extend to live use

Construct adapters using feature 04 client lifecycle wiring and credentials supplied
outside source code. Run a fixed held-out dataset and record model identifiers,
settings, verified success rate, latency, tokens when supplied, and failures. Set
compatible options explicitly; provider defaults are not equivalent. Keep non-streaming
and streaming comparisons separate and report missing usage fields as unknown.

## Before moving on

- [ ] Five adapter formats normalize into the same verified answer.
- [ ] Each serialized request includes the same question.
- [ ] All adapters reject the invented citation at the application layer.
- [ ] Every run has its own context and fixture transport.
- [ ] No fixture result is presented as a live provider benchmark.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
