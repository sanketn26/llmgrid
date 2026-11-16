# 05 — Deny a tool call without hiding it

> Guardrails can block inputs, outputs and tool calls — visibly, and with honest budget accounting.

← [04](04-provider-roundtrip.md) · [All features](README.md) · [06](06-resample.md) →

## Why

A blocked action must show up to the model and the caller as a blocked action, not vanish. And a rejected input should not cost a model call.

## Expects

**Behavior (end to end)**

- A guardrail in front of a tool executor blocks `delete`, reports an error result, and does not run the tool.
- An input that fails `MaxLength` never starts the step and charges nothing.

**Rules**

- A guardrail returns allow or deny. It does not rewrite the value.
- If a guardrail cannot decide, it raises.
- A denied tool call still costs one tool call.
- Do not export the new types from package `__init__.py` yet.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/interfaces/src/llmgrid/interfaces/capabilities.py` | Shared verdicts, `GuardrailViolationError`, and errors used by features 06–08. |
| `packages/loops/src/llmgrid/loops/guarded.py` | `GuardedStep` and `GuardedToolExecutor`: input, output, and tool-call checks. |

**Also update / keep green**

- `llmgrid.tools`: the inner executor keeps its shape (`execute` returns `ToolResult`).

## Acceptance

- [ ] `packages/loops/tests/test_guardrails.py` passes.
- [ ] An input denial charges nothing.
- [ ] A denied tool call is an error result, is not executed, and still costs one tool call.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_guardrails.py`

Unit tests, including the budget assertion for an input denial.

```python
"""Feature behaviour tests. Fakes depend only on llmgrid.interfaces."""

import unittest

from llmgrid.interfaces import (
    Budget,
    ChatRequest,
    ChatResponse,
    ContractError,
    Message,
    ModelCapabilities,
    RunContext,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from llmgrid.interfaces.capabilities import GuardrailViolationError, Verdict
from llmgrid.interfaces.loop import Completed
from llmgrid.loops import ToolAgent
from llmgrid.loops.guarded import (
    DenyPatterns,
    GuardedStep,
    GuardedToolExecutor,
    MaxLength,
    ToolAllowlist,
)


class Echo:
    async def run(self, value: str, *, context: RunContext) -> str:
        return value


class Sequenced:
    """Returns prepared outputs in order and records how often it ran."""

    def __init__(self, *outputs: str) -> None:
        self._outputs = list(outputs)
        self.runs = 0

    async def run(self, value: str, *, context: RunContext) -> str:
        self.runs += 1
        return self._outputs.pop(0)


class CountingExecutor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return (ToolSpec("read", "Read", "{}"),)

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        self.executed.append(call.name)
        return ToolResult(call.id, "done")


def make_context(model_calls: int = 8) -> RunContext:
    return RunContext("t", Budget(model_calls, 8))


class DeleteThenStop:
    def __init__(self) -> None:
        self._done = False

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tool_calling=True)

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        if self._done:
            return ChatResponse(Message("assistant", "stopped"), "stop")
        self._done = True
        return ChatResponse(
            Message("assistant", calls=(ToolCall("1", "delete", "{}"),)),
            "tool_calls",
        )


class GuardrailTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_denial_skips_the_step(self) -> None:
        step = Sequenced("never")
        guarded = GuardedStep(step, inputs=(MaxLength(3),))
        with self.assertRaises(GuardrailViolationError) as raised:
            await guarded.run("too long", context=make_context())
        self.assertEqual(
            (raised.exception.stage, raised.exception.guardrail), ("input", "max_length")
        )
        self.assertEqual(step.runs, 0)

    async def test_output_denial_raises(self) -> None:
        guarded = GuardedStep(Echo(), outputs=(DenyPatterns((r"secret\d+",)),))
        with self.assertRaises(GuardrailViolationError) as raised:
            await guarded.run("the SECRET42 is", context=make_context())
        self.assertEqual(raised.exception.stage, "output")

    async def test_allowed_value_passes_through(self) -> None:
        guarded = GuardedStep(Echo(), (MaxLength(10),), (DenyPatterns(("bad",)),))
        self.assertEqual(await guarded.run("fine", context=make_context()), "fine")

    async def test_denial_requires_reason(self) -> None:
        with self.assertRaises(ContractError):
            Verdict(False)

    async def test_denied_tool_call_is_reported_not_executed(self) -> None:
        inner = CountingExecutor()
        executor = GuardedToolExecutor(inner, (ToolAllowlist(frozenset({"read"})),))
        context = make_context()
        denied = await executor.execute(ToolCall("1", "delete", "{}"), context=context)
        self.assertTrue(denied.is_error)
        self.assertEqual(denied.call_id, "1")
        self.assertEqual(inner.executed, [])

        outcome = await ToolAgent(DeleteThenStop(), executor).run("go", context=context)
        self.assertIsInstance(outcome, Completed)
        assert isinstance(outcome, Completed)
        results = [
            message.result for message in outcome.value.messages if message.result is not None
        ]
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].is_error)
        self.assertEqual(inner.executed, [])
        self.assertEqual((context.budget.model_calls, context.budget.tool_calls), (2, 1))

        allowed = await executor.execute(ToolCall("2", "read", "{}"), context=context)
        self.assertFalse(allowed.is_error)
        self.assertEqual(inner.executed, ["read"])


class GuardrailBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_denial_charges_nothing(self) -> None:
        context = make_context()
        guarded = GuardedStep(Sequenced("never"), inputs=(MaxLength(3),))
        with self.assertRaises(GuardrailViolationError):
            await guarded.run("too long", context=context)
        self.assertEqual((context.budget.model_calls, context.budget.tool_calls), (0, 0))


if __name__ == "__main__":
    unittest.main()
```
