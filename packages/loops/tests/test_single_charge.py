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
