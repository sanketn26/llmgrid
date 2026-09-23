"""Adapts a `ChatModel` into a budgeted `Step`."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from llmgrid.interfaces import ChatModel, ChatRequest, ChatResponse, ContractError, RunContext

__all__ = ["ModelStep"]


@dataclass(frozen=True)
class ModelStep:
    model: ChatModel

    async def run(self, value: ChatRequest, *, context: RunContext) -> ChatResponse:
        context.check()
        if value.tools and not self.model.capabilities.tool_calling:
            raise ContractError("Model does not support tool calling")
        context.budget.consume("model")
        return await context.invoke(partial(self.model.generate, value, context=context))
