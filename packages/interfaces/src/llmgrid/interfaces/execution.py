"""Execution contracts: run context, budget, and the composable `Step`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from llmgrid.interfaces.errors import BudgetExceededError

__all__ = ["Budget", "RunContext", "Step"]


@dataclass
class Budget:
    """Flat invocation counters shared by every step in a run.

    Prototype: the hierarchical ledger in the plan (Section 6) replaces it.
    """

    max_model_calls: int = 8
    max_tool_calls: int = 16
    model_calls: int = field(default=0, init=False)
    tool_calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.max_model_calls < 0 or self.max_tool_calls < 0:
            raise ValueError("Limits must be nonnegative")

    def consume(self, kind: Literal["model", "tool"]) -> None:
        # No await here: atomic within a single event loop.
        # Not a thread-safe or distributed reservation implementation.
        if kind == "model":
            if self.model_calls >= self.max_model_calls:
                raise BudgetExceededError("Model-call limit reached")
            self.model_calls += 1
        else:
            if self.tool_calls >= self.max_tool_calls:
                raise BudgetExceededError("Tool-call limit reached")
            self.tool_calls += 1


@dataclass(frozen=True)
class RunContext:
    """Run identity, deadline, and budget passed to every step."""

    run_id: str
    budget: Budget
    # Use asyncio.get_running_loop().time(), not a wall-clock timestamp.
    deadline: float | None = None

    def check(self) -> None:
        if self.deadline is not None and asyncio.get_running_loop().time() >= self.deadline:
            raise TimeoutError("Run deadline exceeded")

    async def invoke[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        """Dispatch one leaf operation (model or tool call) under the deadline.

        Only the runtime calls this. Composition primitives and capabilities
        call `check()` so a single timeout scope owns each external call.
        """
        self.check()
        async with asyncio.timeout_at(self.deadline):
            return await operation()


class Step[InputT, OutputT](Protocol):
    """A composable unit of work."""

    async def run(self, value: InputT, *, context: RunContext) -> OutputT: ...
