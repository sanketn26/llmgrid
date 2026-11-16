# 06 — Retry a rejected result, and do not retry a budget error

> Retry a step until its result is accepted — but never retry running out of budget.

← [05](05-guardrail.md) · [All features](README.md) · [07](07-refiner.md) →

## Why

Sampling again is a cheap fix for a flaky model output. Retrying a budget error, though, would just burn the rest of the ledger.

## Expects

**Behavior (end to end)**

- A step that returns `bad` then `ok!` runs twice and returns `ok!`.
- A budget error is not retried.

**Rules**

- Retry only the named failures.
- Each attempt spends the shared ledger from feature 01.
- Exhaustion raises `ResamplingExhaustedError` listing every reason. The rejected value is never returned.
- `ResampleStep` reraises `BudgetExceededError` on the first attempt; it does not convert it to `Stopped` (only `ToolAgent.run` does that). The test calls `ResampleStep` directly.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/loops/src/llmgrid/loops/resample.py` | `ResampleStep` and `BestOfStep`. |

**Also update / keep green**

- `llmgrid.interfaces`: add `ResamplingExhaustedError` to the capabilities module from feature 05.

## Acceptance

- [ ] `packages/loops/tests/test_resample.py` passes.
- [ ] `bad` then `ok!` returns `ok!` after two runs.
- [ ] Exhaustion lists every reason.
- [ ] `BudgetExceededError` is not retried.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_resample.py`

Unit tests for acceptance, exhaustion, and budget errors.

```python
"""Feature behaviour tests. Fakes depend only on llmgrid.interfaces."""

import unittest

from llmgrid.interfaces import (
    Budget,
    BudgetExceededError,
    ChatRequest,
    ChatResponse,
    Message,
    ModelCapabilities,
    RunContext,
)
from llmgrid.interfaces.capabilities import (
    GuardrailViolationError,
    ResamplingExhaustedError,
    Verdict,
)
from llmgrid.loops.guarded import GuardedStep, MaxLength
from llmgrid.loops.resample import BestOfStep, ResampleStep


class TextModel:
    """Replies with prepared texts and counts model calls through the budget."""

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)
        self.requests: list[ChatRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities()

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(Message("assistant", self._texts.pop(0)), "stop")


class Sequenced:
    """Returns prepared outputs in order and records how often it ran."""

    def __init__(self, *outputs: str) -> None:
        self._outputs = list(outputs)
        self.runs = 0

    async def run(self, value: str, *, context: RunContext) -> str:
        self.runs += 1
        return self._outputs.pop(0)


class Accept:
    """Accepts results that contain the word `ok`."""

    name = "contains_ok"

    async def check(self, value: str, *, context: RunContext) -> Verdict:
        return Verdict.allow() if "ok" in value else Verdict.deny("missing ok")


class Length:
    async def run(self, value: str, *, context: RunContext) -> float:
        return float(len(value))


def make_context(model_calls: int = 8) -> RunContext:
    return RunContext("t", Budget(model_calls, 8))


class ResampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_first_accepted_result(self) -> None:
        step = Sequenced("bad", "ok!", "ok again")
        result = await ResampleStep(step, Accept()).run("x", context=make_context())
        self.assertEqual((result, step.runs), ("ok!", 2))

    async def test_exhaustion_reports_every_reason(self) -> None:
        step = Sequenced("a", "b")
        with self.assertRaises(ResamplingExhaustedError) as raised:
            await ResampleStep(step, Accept(), max_attempts=2).run("x", context=make_context())
        self.assertEqual(len(raised.exception.reasons), 2)

    async def test_retries_named_failures_only(self) -> None:
        def guarded() -> GuardedStep[str, str]:
            return GuardedStep(Sequenced("long text", "ok"), outputs=(MaxLength(4),))

        result = await ResampleStep(guarded(), Accept()).run("x", context=make_context())
        self.assertEqual(result, "ok")
        with self.assertRaises(GuardrailViolationError):
            await ResampleStep(guarded(), Accept(), retry_on=()).run("x", context=make_context())

    async def test_best_of_picks_highest_score_earliest_on_tie(self) -> None:
        step = Sequenced("aa", "bbbb", "cccc")
        result = await BestOfStep(step, Length(), samples=3).run("x", context=make_context())
        self.assertEqual(result, "bbbb")


class RaisesBudget:
    def __init__(self) -> None:
        self.runs = 0

    async def run(self, value: str, *, context: RunContext) -> str:
        self.runs += 1
        raise BudgetExceededError("stopped")


class BudgetRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_error_is_never_retried(self) -> None:
        step = RaisesBudget()
        with self.assertRaises(BudgetExceededError):
            await ResampleStep(step, Accept(), max_attempts=5).run("x", context=make_context())
        self.assertEqual(step.runs, 1)


if __name__ == "__main__":
    unittest.main()
```
