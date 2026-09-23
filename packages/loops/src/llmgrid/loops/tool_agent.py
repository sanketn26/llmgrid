"""Recipe: bounded, sequential tool-calling agent."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from llmgrid.interfaces import (
    ChatModel,
    ChatRequest,
    ContractError,
    Message,
    ModelStoppedError,
    RunContext,
    ToolExecutor,
)
from llmgrid.loops.model_step import ModelStep

__all__ = ["AgentResult", "ToolAgent"]


@dataclass(frozen=True)
class AgentResult:
    text: str
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class ToolAgent:
    """Calls the model, runs requested tools, and repeats until a final answer.

    A round is one model call plus its tool batch. Starts a fresh conversation
    per input; instructions and continuation are not yet supported.
    """

    model: ChatModel
    tools: ToolExecutor
    max_rounds: int = 8

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        if self.tools.specs and not self.model.capabilities.tool_calling:
            raise ContractError("This agent requires tool calling")

    async def run(self, value: str, *, context: RunContext) -> AgentResult:
        messages = [Message("user", value)]
        model_step = ModelStep(self.model)
        seen_ids: set[str] = set()
        for _ in range(self.max_rounds):
            response = await model_step.run(
                ChatRequest(tuple(messages), self.tools.specs),
                context=context,
            )
            # Appended whole, so provider_state round-trips on the next request.
            messages.append(response.message)
            if response.finish == "stop":
                return AgentResult(response.message.text, tuple(messages))
            if response.finish != "tool_calls":
                raise ModelStoppedError(response.finish)
            calls = response.message.calls
            # Validate the whole batch before executing any call in it.
            if any(call.id in seen_ids for call in calls):
                raise ContractError("Tool-call ID reused within this run")
            seen_ids.update(call.id for call in calls)
            for call in calls:
                context.check()
                context.budget.consume("tool")
                # partial binds `call` now; a lambda would capture the loop variable.
                result = await context.invoke(partial(self.tools.execute, call, context=context))
                if result.call_id != call.id:
                    raise ContractError("Tool result correlation mismatch")
                messages.append(Message("tool", result=result))
        raise ModelStoppedError("Round limit reached before final answer")
