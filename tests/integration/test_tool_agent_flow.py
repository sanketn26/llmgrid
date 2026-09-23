"""Offline end-to-end flow across interfaces, network, tools, and loops."""

import sys
import unittest
from pathlib import Path

from llmgrid.interfaces import Budget, ProviderState, RunContext
from llmgrid.loops import ToolAgent

sys.path.insert(0, str(Path(__file__).parents[2] / "examples" / "tool_agent"))
from demo import make_model, make_registry


class ToolAgentFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_tool_cycle(self) -> None:
        model = make_model()
        context = RunContext("test", Budget(2, 1))
        result = await ToolAgent(model, make_registry()).run("What is 2 + 3?", context=context)
        self.assertEqual(result.text, "The answer is 5.")
        self.assertEqual(
            [m.role for m in result.messages], ["user", "assistant", "tool", "assistant"]
        )
        self.assertEqual((context.budget.model_calls, context.budget.tool_calls), (2, 1))

    async def test_provider_state_is_sent_back_to_the_model(self) -> None:
        model = make_model()
        await ToolAgent(model, make_registry()).run("q", context=RunContext("t", Budget()))
        second_request = model.requests[1]
        self.assertEqual(
            second_request.messages[1].provider_state,
            (ProviderState("scripted", '{"turn": 1}'),),
        )
