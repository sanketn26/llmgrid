# 03 — Replay the verified run without running the tool again

> Record a run in memory and replay it deterministically, without touching the real tool.

← [02](02-verified-answer.md) · [All features](README.md) · [04](04-provider-roundtrip.md) →

## Why

Replay makes agent runs reproducible for debugging and tests, and proves that a recorded run is self-contained. It also introduces restricted tool views and output limits used later.

## Expects

**Behavior (end to end)**

- Record the verified `2 + 3` run, replay it, and get the same `Completed` outcome.
- The real `add` tool runs once in total.

**Rules**

- Records stay in memory. Do not write prompts or tool output to a file.
- Replay compares `ChatRequest` and `ToolCall` values; a mismatch raises and does not run the original tool.
- A restricted registry view rejects unknown names. Oversized tool output becomes an error result.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/tools/src/llmgrid/tools/registry.py` | Restricted views reject unknown names. Oversized output is an error result. |
| `packages/loops/src/llmgrid/loops/recording.py` | Replay returns recorded tool results and does not call the original executor. |

**Also update / keep green**

- `llmgrid.network`: `ScriptedModel` is the recorded model.

## Acceptance

- [ ] `packages/loops/tests/test_replay.py` passes.
- [ ] Replay equals the `Completed` outcome.
- [ ] The real tool ran once.
- [ ] A mismatched replay call raises and does not execute the original tool.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_replay.py`

Unit test for one recorded run and one replay.

```python
import unittest

from llmgrid.interfaces import (
    Budget,
    ChatResponse,
    Message,
    RunContext,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from llmgrid.interfaces.loop import Completed
from llmgrid.interfaces.verification import Verification
from llmgrid.loops.recording import RecordingModel, RecordingTools, ReplayModel, ReplayTools
from llmgrid.loops.tool_agent import AgentResult, ToolAgent
from llmgrid.network.scripted import ScriptedModel


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


def recorded_replies() -> tuple[ChatResponse, ChatResponse]:
    return (
        ChatResponse(
            Message("assistant", calls=(ToolCall("c1", "add", '{"a":2,"b":3}'),)),
            "tool_calls",
        ),
        ChatResponse(Message("assistant", "5"), "stop"),
    )


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        AddExecutor.calls = 0

    async def test_replay_matches_and_does_not_rerun_the_tool(self) -> None:
        tools = AddExecutor()
        recorded_tools = RecordingTools(tools)
        model = RecordingModel(ScriptedModel(recorded_replies()))
        outcome = await ToolAgent(model, recorded_tools, EqualsFive()).run(
            "2 + 3?", context=RunContext("example", Budget(2, 1))
        )
        replay = ReplayModel(tuple(model.records), model.capabilities)
        repeated = await ToolAgent(
            replay, ReplayTools(tools.specs, tuple(recorded_tools.records)), EqualsFive()
        ).run("2 + 3?", context=RunContext("example", Budget(2, 1)))
        self.assertIsInstance(outcome, Completed)
        self.assertEqual(repeated, outcome)
        self.assertEqual(AddExecutor.calls, 1)

    async def test_mismatched_tool_replay_raises_and_does_not_execute(self) -> None:
        tools = AddExecutor()
        recorded_tools = RecordingTools(tools)
        model = RecordingModel(ScriptedModel(recorded_replies()))
        await ToolAgent(model, recorded_tools, EqualsFive()).run(
            "2 + 3?", context=RunContext("example", Budget(2, 1))
        )
        self.assertEqual(AddExecutor.calls, 1)
        replay_tools = ReplayTools(tools.specs, tuple(recorded_tools.records))
        with self.assertRaises(ValueError):
            await replay_tools.execute(
                ToolCall("c1", "add", '{"a":9,"b":9}'),
                context=RunContext("mismatch", Budget(2, 1)),
            )
        self.assertEqual(AddExecutor.calls, 1)


if __name__ == "__main__":
    unittest.main()
```
