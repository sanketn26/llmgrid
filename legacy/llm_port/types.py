"""Typed values exchanged across the port boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, Self

__all__ = [
    "FinishReason",
    "Message",
    "Role",
    "StreamEvent",
    "ToolCall",
    "ToolResult",
    "Usage",
]


class Role(StrEnum):
    """Author of a message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    """Why the model stopped generating."""

    STOP = "stop" # Normal completion
    LENGTH = "length" # Stopped due to reaching max length
    TOOL_CALLS = "tool_calls" # Stopped to make a tool call
    CONTENT_FILTER = "content_filter" # Stopped by content filter
    ERROR = "error" # Stopped due to an error


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A model's request to invoke a declared tool.

    Attributes:
        id: Correlation id used to match a :class:`ToolResult` back to the call.
        name: Declared tool name.
        arguments: Decoded arguments; always a mapping, never a JSON string.
        origin: ``"native"`` when the provider emitted a structured tool call,
            ``"recovered"`` when the conformance layer parsed it out of text.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    origin: Literal["native", "recovered"] = "native"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """The application's response to a :class:`ToolCall`."""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Usage:
    """Token accounting for a single exchange."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
        )


@dataclass(frozen=True, slots=True)
class Message:
    """One turn of a conversation.

    A message carries text, tool calls, or a tool result -- assistant turns may
    carry both text and tool calls in the same message.
    """

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_result: ToolResult | None = None
    name: str | None = None
    finish_reason: FinishReason | None = None
    usage: Usage | None = None
    raw: dict[str, Any] | None = field(default=None, repr=False, compare=False)

    @classmethod
    def user(cls, content: str) -> Self:
        return cls(role=Role.USER, content=content)

    @classmethod
    def system(cls, content: str) -> Self:
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: tuple[ToolCall, ...] = ()) -> Self:
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, tool_call_id: str, content: str, *, is_error: bool = False) -> Self:
        return cls(
            role=Role.TOOL,
            content=content,
            tool_result=ToolResult(tool_call_id=tool_call_id, content=content, is_error=is_error),
        )

    @classmethod
    def coerce(cls, value: Message | dict[str, Any]) -> Message:
        """Accept either a :class:`Message` or a plain ``{"role", "content"}`` dict."""
        if isinstance(value, Message):
            return value
        if not isinstance(value, dict):
            raise TypeError(f"cannot coerce {type(value).__name__} to Message")
        role = Role(value.get("role", "user"))
        calls = tuple(
            ToolCall(
                id=str(c["id"]),
                name=str(c["name"]),
                arguments=dict(c.get("arguments") or {}),
                origin=c.get("origin", "native"),
            )
            for c in value.get("tool_calls") or ()
        )
        result = None
        if role is Role.TOOL:
            call_id = value.get("tool_call_id")
            if call_id is None:
                raise ValueError("tool messages require a 'tool_call_id'")
            result = ToolResult(
                tool_call_id=str(call_id),
                content=str(value.get("content", "")),
                is_error=bool(value.get("is_error", False)),
            )
        return cls(
            role=role,
            content=str(value.get("content") or ""),
            tool_calls=calls,
            tool_result=result,
            name=value.get("name"),
        )

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """One increment of a streamed response.

    ``kind`` discriminates the payload:

    ``content``
        ``text`` holds the newly generated delta.
    ``tool_calls``
        ``tool_calls`` holds every tool call accumulated so far, fully decoded.
        Emitted once, after the provider finishes streaming argument fragments.
    ``usage``
        ``usage`` holds final token accounting.
    ``done``
        ``finish_reason`` explains why generation stopped. Always last.
    """

    kind: Literal["content", "tool_calls", "usage", "done"]
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage | None = None
    finish_reason: FinishReason | None = None
