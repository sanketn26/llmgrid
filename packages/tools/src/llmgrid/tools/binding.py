"""Binds a typed tool to its declaration, decoder, and encoder."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from llmgrid.interfaces import (
    InvalidArgumentsError,
    RunContext,
    Tool,
    ToolCall,
    ToolResult,
    ToolSpec,
)

__all__ = ["BoundTool", "ToolBinding"]


class BoundTool(Protocol):
    """A tool with its types erased, so a registry can hold many kinds."""

    @property
    def spec(self) -> ToolSpec: ...

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult: ...


@dataclass(frozen=True)
class ToolBinding[InputT, OutputT]:
    spec: ToolSpec
    tool: Tool[InputT, OutputT]
    decode: Callable[[str], InputT]
    encode: Callable[[OutputT], str]

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        context.check()
        if call.name != self.spec.name:
            raise ValueError("Binding received a different tool name")
        try:
            value = self.decode(call.arguments_json)
        except InvalidArgumentsError as exc:
            return ToolResult(call.id, str(exc), is_error=True)
        # Unexpected tool/encoder errors propagate. Cancellation propagates.
        # The runtime that dispatched this call owns its timeout scope.
        output = await self.tool.invoke(value, context=context)
        return ToolResult(call.id, self.encode(output))
