# 01 — One tool round on a nested budget

> **Status: done** (verified 2026-11-17). Move call charging into one place and let a parent hand out budget slices a child cannot steal.

← [00](00-baseline.md) · [All features](README.md) · [02](02-verified-answer.md) →

## Why

Today `ModelStep` and `ToolAgent` each charge a flat `Budget` themselves. That makes double-charging easy and gives no way to reserve budget for a later step (such as a critic). After this feature every charge goes through `RunContext.invoke`, and budgets nest.

## Expects

**Behavior (end to end)**

- The existing upper-case tool round still answers.
- A child budget cannot spend a slice held for a sibling.
- One tool round charges each model call and each tool call exactly once.

**Rules**

- Keep `Budget(max_model_calls, max_tool_calls)` and the readable `model_calls` / `tool_calls`.
- `Budget.child(limits)` shares what remains. `Budget.allocate(limits)` holds a sibling slice until that sibling consumes it.
- There is no `RunContext.child`.
- A failed `consume` raises `BudgetExceededError` and changes nothing.
- `invoke(..., kind="model"|"tool")` charges once, after the deadline check. An expired deadline raises `TimeoutError`, charges nothing, and does not run the operation.
- `ToolAgent.run` still returns `AgentResult`; `BudgetExceededError`, `ModelStoppedError` and `TimeoutError` still propagate. Feature 02 turns them into `Stopped`.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/interfaces/src/llmgrid/interfaces/execution.py` | Replace the flat budget. `kind` on `invoke` defaults to `None` so old callers keep working until this feature updates them. |
| `packages/loops/src/llmgrid/loops/model_step.py` | Charge the model call only inside `invoke`. |
| `packages/loops/src/llmgrid/loops/tool_agent.py` | Charge each tool call only inside `invoke`. Return type stays `AgentResult` until the next feature. |

**Also update / keep green**

- Keep green: `packages/loops/tests/test_loops_tool_agent.py` (including `test_model_budget_exhaustion`) and `packages/interfaces/tests/test_interfaces_contracts.py`.
- `llmgrid.network` and `llmgrid.tools` are unchanged; the unit test drives them through the agent.

## Acceptance

- [x] `packages/interfaces/tests/test_nested_budget.py` passes.
- [x] `packages/loops/tests/test_single_charge.py` passes.
- [x] A child cannot spend a held sibling slice.
- [x] One tool round charges each model call and each tool call once.
- [x] An expired deadline charges nothing.
- [x] `make demo` still prints `The answer is 5.`
- [x] Existing budget and tool-agent tests stay green, still expecting raised `BudgetExceededError` and `ModelStoppedError` from `ToolAgent.run`.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/interfaces/tests/test_nested_budget.py`

Unit tests for the ledger and the deadline.

```python
import unittest

from llmgrid.interfaces import Budget, BudgetExceededError, RunContext
from llmgrid.interfaces.execution import Counters, Limits


class NestedBudgetTests(unittest.TestCase):
    def test_child_cannot_spend_a_held_slice(self) -> None:
        root = Budget(3, 2)
        critic = root.allocate(Limits(1, 0))
        inner = root.child(Limits(2, 2))
        inner.consume("model", 2)
        with self.assertRaises(BudgetExceededError):
            inner.consume("model")
        self.assertEqual(root.used, Counters(2, 0))
        critic.consume("model")
        self.assertEqual(root.used, Counters(3, 0))

    def test_failed_consume_leaves_counters_unchanged(self) -> None:
        budget = Budget(max_model_calls=1, max_tool_calls=0)
        budget.consume("model")
        with self.assertRaises(BudgetExceededError):
            budget.consume("model")
        with self.assertRaises(BudgetExceededError):
            budget.consume("tool")
        self.assertEqual((budget.model_calls, budget.tool_calls), (1, 0))


class DeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_deadline_does_not_charge(self) -> None:
        import asyncio

        called = False

        async def operation() -> None:
            nonlocal called
            called = True

        context = RunContext("expired", Budget(), asyncio.get_running_loop().time() - 1)
        with self.assertRaises(TimeoutError):
            await context.invoke(operation, kind="model")
        self.assertFalse(called)
        self.assertEqual(context.budget.model_calls, 0)


if __name__ == "__main__":
    unittest.main()
```

### `packages/loops/tests/test_single_charge.py`

Unit test that one tool round charges each model call and each tool call once.

```python
import asyncio
import unittest
from collections.abc import Sequence

from llmgrid.interfaces import (
    Budget,
    ChatRequest,
    ChatResponse,
    Message,
    ModelCapabilities,
    RunContext,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from llmgrid.loops import ToolAgent


class ReplayModel:
    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tool_calling=True)

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        return self._responses.pop(0)


class UpperExecutor:
    calls = 0

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return (ToolSpec("upper", "Upper-case text", "{}"),)

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        type(self).calls += 1
        return ToolResult(call.id, call.arguments_json.upper())


def calls(*ids: str) -> ChatResponse:
    return ChatResponse(
        Message("assistant", calls=tuple(ToolCall(i, "upper", i) for i in ids)),
        "tool_calls",
    )


def final(text: str) -> ChatResponse:
    return ChatResponse(Message("assistant", text), "stop")


class SingleChargeTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_round_charges_each_call_once(self) -> None:
        context = RunContext("t", Budget(2, 2))
        agent = ToolAgent(ReplayModel([calls("a", "b"), final("done")]), UpperExecutor())
        result = await agent.run("go", context=context)
        self.assertEqual(result.text, "done")
        self.assertEqual((context.budget.model_calls, context.budget.tool_calls), (2, 2))

    async def test_expired_deadline_does_not_call_the_model(self) -> None:
        context = RunContext("t", Budget(), asyncio.get_running_loop().time() - 1)
        agent = ToolAgent(ReplayModel([final("done")]), UpperExecutor())
        with self.assertRaises(TimeoutError):
            await agent.run("go", context=context)
        self.assertEqual(context.budget.model_calls, 0)


if __name__ == "__main__":
    unittest.main()
```
