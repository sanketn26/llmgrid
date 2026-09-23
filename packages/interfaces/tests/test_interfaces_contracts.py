import asyncio
import unittest

from llmgrid.interfaces import (
    Budget,
    BudgetExceededError,
    ChatResponse,
    ContractError,
    Message,
    ProviderState,
    RunContext,
    ToolCall,
)


class MessageContractTests(unittest.TestCase):
    def test_only_assistant_carries_calls(self) -> None:
        with self.assertRaises(ContractError):
            Message("user", calls=(ToolCall("c1", "add", "{}"),))

    def test_provider_state_only_on_assistant(self) -> None:
        with self.assertRaises(ContractError):
            Message("user", "hi", provider_state=(ProviderState("x", "{}"),))

    def test_tool_message_requires_result(self) -> None:
        with self.assertRaises(ContractError):
            Message("tool")


class ResponseContractTests(unittest.TestCase):
    def test_finish_reason_must_match_calls(self) -> None:
        with self.assertRaises(ContractError):
            ChatResponse(Message("assistant"), "tool_calls")

    def test_call_ids_must_be_unique(self) -> None:
        call = ToolCall("c1", "add", "{}")
        with self.assertRaises(ContractError):
            ChatResponse(Message("assistant", calls=(call, call)), "tool_calls")


class BudgetTests(unittest.TestCase):
    def test_consume_stops_at_limit(self) -> None:
        budget = Budget(max_model_calls=1, max_tool_calls=0)
        budget.consume("model")
        with self.assertRaises(BudgetExceededError):
            budget.consume("model")
        with self.assertRaises(BudgetExceededError):
            budget.consume("tool")


class RunContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_deadline_fails_check(self) -> None:
        context = RunContext("test", Budget(), asyncio.get_running_loop().time() - 1)
        with self.assertRaises(TimeoutError):
            context.check()

    async def test_parent_cancellation_propagates(self) -> None:
        started = asyncio.Event()

        async def operation() -> None:
            started.set()
            await asyncio.Event().wait()

        context = RunContext("test", Budget())
        task = asyncio.create_task(context.invoke(operation))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
