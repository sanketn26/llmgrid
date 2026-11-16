# 08 — Route one request, then split one request

> Send a request to the right branch by exact label, or break it into parts and recompose.

← [07](07-refiner.md) · [All features](README.md) · [09](09-grounded-answer.md) →

## Why

Routing and decomposition are where agents most often fail silently. Here a missing route is an error, not a fallback.

## Expects

**Behavior (end to end)**

- A known label runs that branch.
- An unknown label raises `RoutingError` when there is no default.
- A planner emits two parts and recomposes them.

**Rules**

- Labels match exactly. A missing label is an error unless a default branch exists.
- No silent fallback from a missed route to the errand.
- The planner replans after each part. An empty first plan raises `ContractError`.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/loops/src/llmgrid/loops/router.py` | Exact-label router. |
| `packages/loops/src/llmgrid/loops/errand.py` | Decompose, run each part, recompose. |
| `packages/loops/src/llmgrid/loops/planner.py` | Replanning planner. |

**Also update / keep green**

- The verified agent from feature 02 can be a branch; the unit tests use fakes so the routing rules are visible without a provider.

## Acceptance

- [ ] `packages/loops/tests/test_route_errand.py` passes.
- [ ] An unknown label raises `RoutingError`.
- [ ] A two-part plan recomposes.
- [ ] An empty plan raises `ContractError`.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_route_errand.py`

Unit tests for routing, errands, and the planner.

```python
"""Feature behaviour tests. Fakes depend only on llmgrid.interfaces."""

import unittest
from collections.abc import Sequence

from llmgrid.interfaces import (
    Budget,
    ChatRequest,
    ChatResponse,
    ContractError,
    Message,
    ModelCapabilities,
    ModelStoppedError,
    RunContext,
)
from llmgrid.interfaces.capabilities import RoutingError
from llmgrid.loops.errand import Errand, ErrandStep, ModelDecomposer, ModelRecomposer
from llmgrid.loops.planner import ModelPlanner, PlannerStep
from llmgrid.loops.router import ModelClassifier, RouterStep, RuleClassifier


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


class Tag:
    def __init__(self, tag: str) -> None:
        self.tag = tag

    async def run(self, value: str, *, context: RunContext) -> str:
        return f"{self.tag}:{value}"


class Join:
    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> str:
        return "+".join(part.result for part in value.parts)


class Splitter:
    def __init__(self, *parts: str) -> None:
        self._parts = parts

    async def run(self, value: str, *, context: RunContext) -> tuple[str, ...]:
        return self._parts


def make_context(model_calls: int = 8) -> RunContext:
    return RunContext("t", Budget(model_calls, 8))


def labels(texts: Sequence[str]) -> dict[str, str]:
    return {text: f"{text} requests" for text in texts}


class ErrandTests(unittest.IsolatedAsyncioTestCase):
    async def test_decompose_work_recompose(self) -> None:
        errand = ErrandStep(Splitter("a", "b"), Tag("w"), Join())
        self.assertEqual(await errand.run("task", context=make_context()), "w:a+w:b")

    async def test_empty_and_oversized_plans_are_rejected(self) -> None:
        with self.assertRaises(ContractError):
            await ErrandStep(Splitter(), Tag("w"), Join()).run("t", context=make_context())
        oversized = ErrandStep(Splitter("a", "b", "c"), Tag("w"), Join(), max_subtasks=2)
        with self.assertRaises(ContractError):
            await oversized.run("t", context=make_context())

    async def test_model_decomposer_and_recomposer(self) -> None:
        planner = TextModel('["first", "second"]')
        merger = TextModel("final answer")
        errand = ErrandStep(ModelDecomposer(planner), Tag("w"), ModelRecomposer(merger))
        self.assertEqual(await errand.run("task", context=make_context()), "final answer")
        self.assertIn("Result: w:second", merger.requests[0].messages[0].text)

    async def test_malformed_plan_is_rejected(self) -> None:
        for reply in ("not json", '{"a": 1}', '["ok", ""]'):
            with self.subTest(reply=reply), self.assertRaises(ContractError):
                await ModelDecomposer(TextModel(reply)).run("t", context=make_context())


class RouterTests(unittest.IsolatedAsyncioTestCase):
    def router(
        self, classifier: RuleClassifier[str], *, default: bool = False
    ) -> RouterStep[str, str]:
        return RouterStep(
            classifier,
            {"code": Tag("code"), "chat": Tag("chat")},
            default=Tag("fallback") if default else None,
        )

    async def test_routes_by_rule(self) -> None:
        classifier = RuleClassifier([(lambda text: "def " in text, "code")], otherwise="chat")
        router = self.router(classifier)
        self.assertEqual(await router.run("def f()", context=make_context()), "code:def f()")
        self.assertEqual(await router.run("hello", context=make_context()), "chat:hello")

    async def test_unknown_label_needs_explicit_default(self) -> None:
        classifier = RuleClassifier([(lambda text: True, "other")])
        with self.assertRaises(RoutingError):
            await self.router(classifier).run("x", context=make_context())
        routed = await self.router(classifier, default=True).run("x", context=make_context())
        self.assertEqual(routed, "fallback:x")

    async def test_model_classifier_costs_one_call_and_is_strict(self) -> None:
        context = make_context()
        classifier = ModelClassifier(TextModel(" Code \n"), labels(["code", "chat"]))
        self.assertEqual(await classifier.run("def f()", context=context), "code")
        self.assertEqual(context.budget.model_calls, 1)
        with self.assertRaises(RoutingError):
            await ModelClassifier(TextModel("I think code"), labels(["code", "chat"])).run(
                "x", context=make_context()
            )


class PlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_replans_after_each_result(self) -> None:
        seen: list[int] = []

        class Planner:
            async def run(
                self, value: Errand[str, str, str], *, context: RunContext
            ) -> tuple[str, ...]:
                seen.append(len(value.parts))
                return ("a", "b")[len(value.parts) :]

        step = PlannerStep(Planner(), Tag("w"), Join())
        self.assertEqual(await step.run("t", context=make_context()), "w:a+w:b")
        self.assertEqual(seen, [0, 1, 2])

    async def test_empty_first_plan_and_step_limit(self) -> None:
        with self.assertRaises(ContractError):
            await PlannerStep(Never(), Tag("w"), Join()).run("t", context=make_context())
        with self.assertRaises(ModelStoppedError):
            await PlannerStep(Forever(), Tag("w"), Join(), max_steps=2).run(
                "t", context=make_context()
            )

    async def test_model_planner(self) -> None:
        planner = ModelPlanner(TextModel('["first", "second"]', '["second"]', "[]"))
        step = PlannerStep(planner, Tag("w"), Join())
        self.assertEqual(await step.run("t", context=make_context()), "w:first+w:second")

    async def test_model_planner_rejects_bad_json(self) -> None:
        errand = Errand[str, str, str]("t", ())
        with self.assertRaises(ContractError):
            await ModelPlanner(TextModel("sure!")).run(errand, context=make_context())


class Never:
    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> tuple[str, ...]:
        return ()


class Forever:
    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> tuple[str, ...]:
        return ("more",)


if __name__ == "__main__":
    unittest.main()
```
