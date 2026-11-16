# Example: guarded, routed, and decomposed requests

[Feature 15](../features/15-coding-release.md) · [Feature guide](../composable-agent-platform-plan.md) · [Package code](../features/08-route-and-errand.md)

## Goal and starting point

Show guardrails, resampling, errands, and routing working together on a
deterministic offline model. A prompt-injection attempt is blocked before any model
call, an empty reply is resampled, a simple question takes the direct route, and a
compound question is decomposed into two subtasks and recomposed.

| Action | Starting file / role |
| --- | --- |
| Reuse | The [feature 05–08](../features/05-guardrail.md) modules and `ModelStep` |
| Add | `examples/implementation/showcase_safe_router.py`: application composition and a canned model |
| Keep | Package dependency rules; the model is an application fixture, not a package |

## Implement this file

Write the file named in the starting-point table so the checklist below passes. This guide does not include a reference implementation.


## Run it

```bash
.venv/bin/python examples/implementation/showcase_safe_router.py
```

Expected output:

```text
Paris.
blocked: matches denied pattern 'ignore (all )?previous instructions'
Berlin.
Vienna.
Rome. | Madrid.
model calls: 7
```

The seven calls are: answer (1), resample's empty and good replies (2), the simple route
(1), the decomposer (1), and two workers (2). The blocked request costs nothing.

## Live use

Replace `CannedModel` with a real `ChatModel`, swap `RuleClassifier` for `ModelClassifier`
when labels cannot be matched by rule, and add a stronger input guardrail than a regex.
Claim safety only after testing against your own adversarial cases.
