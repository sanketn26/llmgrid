"""The chat-model capability contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from llmgrid.interfaces.errors import ContractError
from llmgrid.interfaces.execution import RunContext
from llmgrid.interfaces.values import Message, ToolSpec

__all__ = ["ChatModel", "ChatRequest", "ChatResponse", "FinishReason", "ModelCapabilities"]

type FinishReason = Literal["stop", "tool_calls", "length", "content_filter", "refusal"]


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()


@dataclass(frozen=True)
class ChatResponse:
    message: Message
    finish: FinishReason

    def __post_init__(self) -> None:
        if self.message.role != "assistant":
            raise ContractError("Model response must be an assistant message")
        if (self.finish == "tool_calls") != bool(self.message.calls):
            raise ContractError("Finish reason and tool calls disagree")
        ids = [call.id for call in self.message.calls]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            raise ContractError("Tool-call IDs must be nonempty and unique")


@dataclass(frozen=True)
class ModelCapabilities:
    tool_calling: bool = False


class ChatModel(Protocol):
    """Generates one assistant turn. Never executes tools."""

    @property
    def capabilities(self) -> ModelCapabilities: ...

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse: ...
