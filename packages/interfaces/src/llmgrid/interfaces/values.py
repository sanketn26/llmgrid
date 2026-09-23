"""Portable value types exchanged between models, tools, and the runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from llmgrid.interfaces.errors import ContractError

__all__ = ["Message", "ProviderState", "ToolCall", "ToolResult", "ToolSpec"]


@dataclass(frozen=True)
class ToolSpec:
    """A tool declaration as the model sees it.

    The schema is kept as immutable JSON text. The tool binding owns the
    runtime decoder that must agree with it.
    """

    name: str
    description: str
    input_schema_json: str


@dataclass(frozen=True)
class ToolCall:
    """A model's request to invoke a declared tool."""

    id: str
    name: str
    # Raw argument text as emitted (after syntactic recovery). Decoding is the
    # binding's job, so undecodable input can still be reported to the model.
    arguments_json: str
    origin: Literal["native", "recovered"] = "native"


@dataclass(frozen=True)
class ToolResult:
    """The outcome of one tool call, correlated by `call_id`."""

    call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ProviderState:
    """Opaque continuation data an adapter must receive back unchanged.

    Examples: reasoning/thinking blocks and their signatures. The runtime
    carries it and never inspects it. Adapters ignore state whose `provider`
    is not their own.
    """

    provider: str
    payload_json: str


@dataclass(frozen=True)
class Message:
    """One conversation turn."""

    role: Literal["system", "user", "assistant", "tool"]
    text: str = ""
    calls: tuple[ToolCall, ...] = ()
    result: ToolResult | None = None
    provider_state: tuple[ProviderState, ...] = ()

    def __post_init__(self) -> None:
        if self.calls and self.role != "assistant":
            raise ContractError("Only assistant messages may contain calls")
        if self.provider_state and self.role != "assistant":
            raise ContractError("Only assistant messages may carry provider state")
        if (self.role == "tool") != (self.result is not None):
            raise ContractError("Tool messages require exactly one result")
        if self.role == "tool" and self.text:
            raise ContractError("Tool content belongs in result.content")
