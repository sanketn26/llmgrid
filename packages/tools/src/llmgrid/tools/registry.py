"""Routes tool calls to bound tools by name."""

from __future__ import annotations

from collections.abc import Sequence

from llmgrid.interfaces import RunContext, ToolCall, ToolResult, ToolSpec
from llmgrid.tools.binding import BoundTool

__all__ = ["ToolRegistry"]


class ToolRegistry:
    """A `ToolExecutor` over a fixed set of uniquely named tools.

    Validates and routes calls only. Budget, ordering, and timeouts belong to
    whoever dispatches the call.
    """

    def __init__(self, tools: Sequence[BoundTool]) -> None:
        self._tools: dict[str, BoundTool] = {}
        for tool in tools:
            if not tool.spec.name or tool.spec.name in self._tools:
                raise ValueError("Tool names must be nonempty and unique")
            self._tools[tool.spec.name] = tool

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec for tool in self._tools.values())

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        context.check()
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, "Unknown tool", is_error=True)
        return await tool.execute(call, context=context)
