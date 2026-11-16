# 02 — Verified answer, or a stopped false claim

> The agent returns `Completed` / `Stopped` / `Failed` instead of raising, and a claimed answer must pass a verifier.

← [01](01-budgeted-round.md) · [All features](README.md) · [03](03-replay.md) →

## Why

A model saying "done" is not evidence. This feature adds verification and turns every way an agent can stop (budget, deadline, truncation, round limit, repeated false claim) into a typed outcome the caller can match on.

## Expects

**Behavior (end to end)**

- A scripted `add` tool run returns `Completed` with text `5` and usage `(2, 1)`.
- A model that claims `wrong` three times returns `Stopped` with `no_progress` and never calls the tool.

**Rules**

- `Usage` records token counts; it does not enforce them.
- Verification strengths: `deterministic`, `judged`, `self_report`. `AcceptClaim` is self-report. This feature's check uses a deterministic verifier.
- `Budget.consume` and `RunContext.invoke` still raise. `ToolAgent.run` is the boundary that converts:

  | Raised / observed | Becomes `Stopped` with |
  | --- | --- |
  | `BudgetExceededError` | `budget_exhausted` |
  | `TimeoutError` | `deadline` |
  | finish reason `length` | `model_length` |
  | round limit | `max_iterations` |
  | repeated false claim | `no_progress` |
- Do not keep `ModelStoppedError` for those agent results.
- A step that is not `ToolAgent` still raises `BudgetExceededError` (feature 06 relies on this).
- Verification runs before the round limit, including on the last round.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/interfaces/src/llmgrid/interfaces/model.py` | Add usage, request limits, and capability checks. Existing constructors keep working. |
| `packages/interfaces/src/llmgrid/interfaces/verification.py` | Verifier result. A verifier may spend budget through the context. |
| `packages/interfaces/src/llmgrid/interfaces/providers.py` | Typed provider failures. `ProviderTimeoutError` is also a `TimeoutError`. |
| `packages/interfaces/src/llmgrid/interfaces/loop.py` | Outcomes replace exception-only stopping at the agent boundary. |
| `packages/loops/src/llmgrid/loops/policies.py` | Stop when rounds run out, the same failure repeats, or a false claim repeats. |
| `packages/loops/src/llmgrid/loops/model_step.py` | Validate the request with this feature's capabilities, then dispatch once. |
| `packages/loops/src/llmgrid/loops/tool_agent.py` | Return `Outcome[AgentResult]`. |

**Also update / keep green**

- Replace `packages/loops/tests/test_single_charge.py` with the module below.
- `packages/loops/tests/test_loops_tool_agent.py`: success reads `Completed.value`; `test_model_budget_exhaustion` → `budget_exhausted`; `test_truncation_is_not_an_answer` → `model_length`; `test_round_limit` → `max_iterations`; `test_expired_deadline_does_not_dispatch` → `deadline` and `model_calls == 0`; `test_sequence_composes_agent` unwraps `Completed` and passes `outcome.value` to `ExtractText`.
- `tests/integration/test_tool_agent_flow.py`, `tests/typing/typing_negative.py`, `examples/tool_agent/demo.py`: read text from `Completed.value`.
- `llmgrid.network`: `ScriptedModel` still builds a `ChatResponse` without passing usage. `llmgrid.tools`: executor unchanged.

## Acceptance

- [ ] `packages/loops/tests/test_verified_agent.py` and the updated `test_single_charge.py` pass.
- [ ] Scripted `add` returns `Completed`, text `5`, usage `(2, 1)`.
- [ ] Three claims of `wrong` return `Stopped` / `no_progress` without calling the tool.
- [ ] Budget exhaustion, truncation, round limit and expired deadline return `Stopped` with `budget_exhausted`, `model_length`, `max_iterations`, `deadline`.
- [ ] `test_loops_tool_agent.py`, `test_tool_agent_flow.py`, `typing_negative.py` and `examples/tool_agent/demo.py` match on `Completed`.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_verified_agent.py`

Unit tests for the verified sum and the false claim.

```python
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
from llmgrid.interfaces.loop import Completed, Stopped
from llmgrid.interfaces.verification import Verification
from llmgrid.loops.tool_agent import AgentResult, ToolAgent


class Scripted:
    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tool_calling=True)

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        return self._responses.pop(0)


class AddExecutor:
    calls = 0

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return (ToolSpec("add", "Add", "{}"),)

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        type(self).calls += 1
        return ToolResult(call.id, "5")


class EqualsFive:
    async def verify(self, candidate: AgentResult, *, context: RunContext) -> Verification:
        context.check()
        passed = candidate.text == "5"
        return Verification(
            "passed" if passed else "failed",
            "deterministic",
            ("Expected final text: 5",),
            "Return the checked result",
        )


class VerifiedAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        AddExecutor.calls = 0

    async def test_verified_tool_answer(self) -> None:
        replies = (
            ChatResponse(
                Message("assistant", calls=(ToolCall("c1", "add", '{"a":2,"b":3}'),)),
                "tool_calls",
            ),
            ChatResponse(Message("assistant", "5"), "stop"),
        )
        context = RunContext("example", Budget(2, 1))
        outcome = await ToolAgent(Scripted(replies), AddExecutor(), EqualsFive()).run(
            "2 + 3?", context=context
        )
        self.assertIsInstance(outcome, Completed)
        assert isinstance(outcome, Completed)
        self.assertEqual(outcome.value.text, "5")
        self.assertEqual((outcome.usage.model_calls, outcome.usage.tool_calls), (2, 1))

    async def test_false_claim_stops(self) -> None:
        wrong = [ChatResponse(Message("assistant", "wrong"), "stop") for _ in range(3)]
        outcome = await ToolAgent(Scripted(wrong), AddExecutor(), EqualsFive()).run(
            "2 + 3?", context=RunContext("false-claim", Budget(3, 0))
        )
        self.assertIsInstance(outcome, Stopped)
        assert isinstance(outcome, Stopped)
        self.assertEqual(outcome.reason, "no_progress")
        self.assertEqual(AddExecutor.calls, 0)


if __name__ == "__main__":
    unittest.main()
```

### `packages/loops/tests/test_single_charge.py`

Replace the feature 01 module. The return value is now an outcome.

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
from llmgrid.interfaces.loop import Completed, Stopped
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
        outcome = await agent.run("go", context=context)
        self.assertIsInstance(outcome, Completed)
        assert isinstance(outcome, Completed)
        self.assertEqual(outcome.value.text, "done")
        self.assertEqual((context.budget.model_calls, context.budget.tool_calls), (2, 2))

    async def test_expired_deadline_does_not_call_the_model(self) -> None:
        context = RunContext("t", Budget(), asyncio.get_running_loop().time() - 1)
        agent = ToolAgent(ReplayModel([final("done")]), UpperExecutor())
        outcome = await agent.run("go", context=context)
        self.assertIsInstance(outcome, Stopped)
        assert isinstance(outcome, Stopped)
        self.assertEqual(outcome.reason, "deadline")
        self.assertEqual(context.budget.model_calls, 0)


if __name__ == "__main__":
    unittest.main()
```
