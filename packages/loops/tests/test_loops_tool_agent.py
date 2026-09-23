"""Loops tests depend only on llmgrid.interfaces; fakes stand in for models and tools."""

import asyncio
import unittest
from collections.abc import Sequence

from llmgrid.interfaces import (
    Budget,
    BudgetExceededError,
    ChatRequest,
    ChatResponse,
    ContractError,
    Message,
    ModelCapabilities,
    ModelStoppedError,
    ProviderState,
    RunContext,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from llmgrid.loops import AgentResult, SequenceStep, ToolAgent


class ReplayModel:
    def __init__(self, responses: Sequence[ChatResponse]) -> None:
        self._responses = list(responses)

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tool_calling=True)

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        return self._responses.pop(0)


class UpperExecutor:
    """Returns each call's arguments upper-cased, correlated by call ID."""

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return (ToolSpec("upper", "Upper-case text", "{}"),)

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        return ToolResult(call.id, call.arguments_json.upper())


class ExtractText:
    async def run(self, value: AgentResult, *, context: RunContext) -> str:
        return value.text


def calls(*ids: str) -> ChatResponse:
    return ChatResponse(
        Message(
            "assistant",
            calls=tuple(ToolCall(i, "upper", i) for i in ids),
            provider_state=(ProviderState("fake", '{"sig": 1}'),),
        ),
        "tool_calls",
    )


def final(text: str) -> ChatResponse:
    return ChatResponse(Message("assistant", text), "stop")


class ToolAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_cycle_and_budget(self) -> None:
        context = RunContext("t", Budget(2, 2))
        agent = ToolAgent(ReplayModel([calls("a", "b"), final("done")]), UpperExecutor())
        result = await agent.run("go", context=context)
        self.assertEqual(result.text, "done")
        results = [m.result for m in result.messages if m.result is not None]
        self.assertEqual([(r.call_id, r.content) for r in results], [("a", "A"), ("b", "B")])
        self.assertEqual((context.budget.model_calls, context.budget.tool_calls), (2, 2))

    async def test_provider_state_kept_in_history(self) -> None:
        agent = ToolAgent(ReplayModel([calls("a"), final("done")]), UpperExecutor())
        result = await agent.run("go", context=RunContext("t", Budget()))
        self.assertEqual(result.messages[1].provider_state, (ProviderState("fake", '{"sig": 1}'),))

    async def test_model_budget_exhaustion(self) -> None:
        agent = ToolAgent(ReplayModel([calls("a"), final("done")]), UpperExecutor())
        with self.assertRaises(BudgetExceededError):
            await agent.run("go", context=RunContext("t", Budget(1, 1)))

    async def test_reused_call_id_rejected(self) -> None:
        agent = ToolAgent(ReplayModel([calls("a"), calls("a")]), UpperExecutor())
        with self.assertRaises(ContractError):
            await agent.run("go", context=RunContext("t", Budget()))

    async def test_truncation_is_not_an_answer(self) -> None:
        truncated = ChatResponse(Message("assistant", "partial"), "length")
        agent = ToolAgent(ReplayModel([truncated]), UpperExecutor())
        with self.assertRaises(ModelStoppedError):
            await agent.run("go", context=RunContext("t", Budget()))

    async def test_round_limit(self) -> None:
        agent = ToolAgent(ReplayModel([calls("a")]), UpperExecutor(), max_rounds=1)
        with self.assertRaises(ModelStoppedError):
            await agent.run("go", context=RunContext("t", Budget()))

    async def test_expired_deadline_does_not_dispatch(self) -> None:
        context = RunContext("t", Budget(), asyncio.get_running_loop().time() - 1)
        agent = ToolAgent(ReplayModel([final("done")]), UpperExecutor())
        with self.assertRaises(TimeoutError):
            await agent.run("go", context=context)
        self.assertEqual(context.budget.model_calls, 0)

    async def test_sequence_composes_agent(self) -> None:
        agent = ToolAgent(ReplayModel([final("done")]), UpperExecutor())
        workflow = SequenceStep[str, AgentResult, str](agent, ExtractText())
        self.assertEqual(await workflow.run("go", context=RunContext("t", Budget())), "done")
