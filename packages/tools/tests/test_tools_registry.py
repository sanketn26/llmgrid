import json
import unittest
from dataclasses import dataclass

from llmgrid.interfaces import Budget, InvalidArgumentsError, RunContext, ToolCall, ToolSpec
from llmgrid.tools import ToolBinding, ToolRegistry


@dataclass(frozen=True)
class EchoInput:
    text: str


class EchoTool:
    async def invoke(self, value: EchoInput, *, context: RunContext) -> str:
        return value.text


def decode_echo(raw: str) -> EchoInput:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise InvalidArgumentsError("Arguments must be valid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"text"} or not isinstance(value["text"], str):
        raise InvalidArgumentsError("Expected exactly one string field: text")
    return EchoInput(value["text"])


SPEC = ToolSpec("echo", "Echo text", '{"type": "object"}')


def make_registry() -> ToolRegistry:
    return ToolRegistry([ToolBinding[EchoInput, str](SPEC, EchoTool(), decode_echo, str)])


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_and_correlates(self) -> None:
        result = await make_registry().execute(
            ToolCall("c1", "echo", '{"text": "hi"}'), context=RunContext("t", Budget())
        )
        self.assertEqual((result.call_id, result.content, result.is_error), ("c1", "hi", False))

    async def test_bad_arguments_return_correlated_error(self) -> None:
        result = await make_registry().execute(
            ToolCall("bad-1", "echo", '{"text": 3}'), context=RunContext("t", Budget())
        )
        self.assertTrue(result.is_error)
        self.assertEqual(result.call_id, "bad-1")

    async def test_unknown_tool_returns_correlated_error(self) -> None:
        result = await make_registry().execute(
            ToolCall("u1", "missing", "{}"), context=RunContext("t", Budget())
        )
        self.assertTrue(result.is_error)
        self.assertEqual(result.call_id, "u1")

    def test_duplicate_names_rejected(self) -> None:
        binding = ToolBinding[EchoInput, str](SPEC, EchoTool(), decode_echo, str)
        with self.assertRaises(ValueError):
            ToolRegistry([binding, binding])
