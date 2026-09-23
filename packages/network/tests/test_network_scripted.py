import unittest

from llmgrid.interfaces import Budget, ChatRequest, ChatResponse, Message, RunContext
from llmgrid.network import ScriptedModel


class ScriptedModelTests(unittest.IsolatedAsyncioTestCase):
    async def test_replays_in_order_and_records_requests(self) -> None:
        first = ChatResponse(Message("assistant", "one"), "stop")
        second = ChatResponse(Message("assistant", "two"), "stop")
        model = ScriptedModel([first, second])
        request = ChatRequest((Message("user", "hi"),))
        context = RunContext("t", Budget())
        self.assertIs(await model.generate(request, context=context), first)
        self.assertIs(await model.generate(request, context=context), second)
        self.assertEqual(model.requests, [request, request])

    async def test_exhaustion_is_an_error(self) -> None:
        model = ScriptedModel([])
        with self.assertRaises(RuntimeError):
            await model.generate(
                ChatRequest((Message("user", "hi"),)), context=RunContext("t", Budget())
            )
