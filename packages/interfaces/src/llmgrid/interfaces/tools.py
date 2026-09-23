"""Tool capability contracts."""

from __future__ import annotations

from typing import Protocol

from llmgrid.interfaces.execution import RunContext
from llmgrid.interfaces.values import ToolCall, ToolResult, ToolSpec

__all__ = ["Tool", "ToolExecutor"]


class Tool[InputT, OutputT](Protocol):
    """A typed tool implementation. Decoding happens before `invoke`."""

    async def invoke(self, value: InputT, *, context: RunContext) -> OutputT: ...


class ToolExecutor(Protocol):
    """Routes a model's tool call and returns a result with the same call ID."""

    @property
    def specs(self) -> tuple[ToolSpec, ...]: ...

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult: ...
