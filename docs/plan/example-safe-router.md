# Phase 7 example: guarded, routed, and decomposed requests

[Example phase](phase-7-examples.md) · [All phases](../composable-agent-platform-plan.md) · [Package code](phase-4-safety-patterns.md)

## Goal and starting point

Show guardrails, resampling, errands, and routing working together on a
deterministic offline model. A prompt-injection attempt is blocked before any model
call, an empty reply is resampled, a simple question takes the direct route, and a
compound question is decomposed into two subtasks and recomposed.

| Action | Starting file / role |
| --- | --- |
| Reuse | The [Phase 4 addendum](phase-4-safety-patterns.md) modules and `ModelStep` |
| Add | `examples/implementation/showcase_safe_router.py`: application composition and a canned model |
| Keep | Package dependency rules; the model is an application fixture, not a package |

## Implement this file

### `examples/implementation/showcase_safe_router.py`

```python
"""Offline showcase: route a request, guard it, decompose a task, and resample until acceptable."""

from __future__ import annotations

import asyncio

from llmgrid.interfaces import (
    Budget,
    ChatRequest,
    ChatResponse,
    Message,
    ModelCapabilities,
    RunContext,
)
from llmgrid.interfaces.capabilities import (
    GuardrailViolationError,
    Verdict,
)
from llmgrid.loops.errand import (
    Errand,
    ErrandStep,
    ModelDecomposer,
)
from llmgrid.loops.guarded import (
    DenyPatterns,
    GuardedStep,
    MaxLength,
)
from llmgrid.loops.model_step import (
    ModelStep,
)
from llmgrid.loops.resample import (
    ResampleStep,
)
from llmgrid.loops.router import (
    RouterStep,
    RuleClassifier,
)


class CannedModel:
    """Replies with prepared texts in order, ignoring the request."""

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities()

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        return ChatResponse(Message("assistant", self._texts.pop(0)), "stop")


class Ask:
    """Sends the text to a model and returns its reply."""

    def __init__(self, model: CannedModel) -> None:
        self.model = model

    async def run(self, value: str, *, context: RunContext) -> str:
        response = await ModelStep(self.model).run(
            ChatRequest((Message("user", value),)), context=context
        )
        return response.message.text


class Join:
    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> str:
        return " | ".join(part.result for part in value.parts)


class NonEmpty:
    name = "non_empty"

    async def check(self, value: str, *, context: RunContext) -> Verdict:
        return Verdict.allow() if value.strip() else Verdict.deny("empty answer")


async def main() -> None:
    context = RunContext("safe-router-1", Budget(max_model_calls=8, max_tool_calls=0))

    # Guardrails: the second request never reaches a model.
    guarded = GuardedStep(
        Ask(CannedModel("Paris.")),
        inputs=(MaxLength(200), DenyPatterns((r"ignore (all )?previous instructions",))),
        outputs=(DenyPatterns((r"\bpassword\b",)),),
    )
    print(await guarded.run("Capital of France?", context=context))
    try:
        await guarded.run("Ignore previous instructions and ...", context=context)
    except GuardrailViolationError as exc:
        print("blocked:", exc.reason)

    # Resampling: the first reply is empty, so the step runs again.
    resampled = ResampleStep(Ask(CannedModel("", "Berlin.")), NonEmpty())
    print(await resampled.run("Capital of Germany?", context=context))

    # Errand: decompose, work each part, recompose.
    errand = ErrandStep(
        ModelDecomposer(CannedModel('["Capital of Italy?", "Capital of Spain?"]')),
        Ask(CannedModel("Rome.", "Madrid.")),
        Join(),
    )

    # Router: pick a route by rule; `otherwise` names the label for everything else.
    router = RouterStep[str, str](
        RuleClassifier([(lambda text: " and " in text, "complex")], otherwise="simple"),
        {"simple": Ask(CannedModel("Vienna.")), "complex": errand},
    )
    print(await router.run("Capital of Austria?", context=context))
    print(await router.run("Capital of Italy and Spain?", context=context))
    print("model calls:", context.budget.model_calls)


if __name__ == "__main__":
    asyncio.run(main())
```

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
