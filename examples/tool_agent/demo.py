"""Offline tool agent: a scripted model asks an `add` tool to sum two integers."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from llmgrid.interfaces import (
    Budget,
    ChatResponse,
    InvalidArgumentsError,
    Message,
    ProviderState,
    RunContext,
    ToolCall,
    ToolSpec,
)
from llmgrid.loops import AgentResult, SequenceStep, ToolAgent
from llmgrid.network import ScriptedModel
from llmgrid.tools import ToolBinding, ToolRegistry


@dataclass(frozen=True)
class AddInput:
    a: int
    b: int


class AddTool:
    async def invoke(self, value: AddInput, *, context: RunContext) -> int:
        context.check()
        return value.a + value.b


def decode_add(raw: str) -> AddInput:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise InvalidArgumentsError("Arguments must be valid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"a", "b"}:
        raise InvalidArgumentsError("Expected exactly a and b")
    a, b = value["a"], value["b"]
    # bool is an int subclass; JSON booleans are not accepted here.
    if type(a) is not int or type(b) is not int:
        raise InvalidArgumentsError("a and b must be integers")
    return AddInput(a, b)


ADD_SPEC = ToolSpec(
    name="add",
    description="Add two integers",
    input_schema_json=json.dumps(
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        }
    ),
)


def make_registry() -> ToolRegistry:
    return ToolRegistry([ToolBinding[AddInput, int](ADD_SPEC, AddTool(), decode_add, str)])


def make_model() -> ScriptedModel:
    return ScriptedModel(
        [
            ChatResponse(
                Message(
                    "assistant",
                    calls=(ToolCall("call-1", "add", '{"a": 2, "b": 3}'),),
                    # Stands in for e.g. a signed reasoning block the provider needs back.
                    provider_state=(ProviderState("scripted", '{"turn": 1}'),),
                ),
                "tool_calls",
            ),
            ChatResponse(Message("assistant", "The answer is 5."), "stop"),
        ]
    )


class ExtractText:
    async def run(self, value: AgentResult, *, context: RunContext) -> str:
        context.check()
        return value.text


async def main() -> None:
    context = RunContext(
        run_id="demo-1",
        budget=Budget(max_model_calls=2, max_tool_calls=1),
        deadline=asyncio.get_running_loop().time() + 5,
    )
    agent = ToolAgent(make_model(), make_registry())
    workflow = SequenceStep[str, AgentResult, str](agent, ExtractText())
    print(await workflow.run("What is 2 + 3?", context=context))
    print(context.budget.model_calls, context.budget.tool_calls)


if __name__ == "__main__":
    asyncio.run(main())
