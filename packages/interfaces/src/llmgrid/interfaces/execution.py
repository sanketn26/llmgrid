"""Execution contracts: run context, budget, and the composable `Step`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from llmgrid.interfaces.errors import BudgetExceededError

__all__ = ["Budget", "Counters", "Kind", "Limits", "RunContext", "Step"]


Kind = Literal["model", "tool"]


@dataclass(frozen=True)
class Limits:
    """Call caps for one budget node."""

    model_calls: int = 0
    tool_calls: int = 0

    def __post_init__(self) -> None:
        if self.model_calls < 0 or self.tool_calls < 0:
            raise ValueError("Limits must be nonnegative")

    def get(self, kind: Kind) -> int:
        return self.model_calls if kind == "model" else self.tool_calls


@dataclass(frozen=True)
class Counters:
    """Calls charged so far."""

    model_calls: int = 0
    tool_calls: int = 0

    def get(self, kind: Kind) -> int:
        return self.model_calls if kind == "model" else self.tool_calls

    def plus(self, kind: Kind, amount: int) -> Counters:
        if kind == "model":
            return Counters(self.model_calls + amount, self.tool_calls)
        return Counters(self.model_calls, self.tool_calls + amount)

    def add(self, other: Counters | Limits, sign: int = 1) -> Counters:
        return Counters(
            self.model_calls + sign * other.model_calls,
            self.tool_calls + sign * other.tool_calls,
        )


class Budget:
    """Hierarchical call ledger shared by every step in a run.

    `child(limits)` caps a sub-run and shares what the parent has left.
    `allocate(limits)` holds a slice for one sibling: nobody else can spend it,
    and the parent counts it as used once that sibling consumes it.
    A charge applies to the node and every ancestor, or to none of them.
    Atomic within one event loop; not thread-safe or distributed.
    """

    def __init__(self, max_model_calls: int = 8, max_tool_calls: int = 16) -> None:
        self._init(Limits(max_model_calls, max_tool_calls), None, allocated=False)

    def _init(self, limits: Limits, parent: Budget | None, *, allocated: bool) -> None:
        self.limits = limits
        self._parent = parent
        self._allocated = allocated
        self._used = Counters()
        self._held = Counters()

    @classmethod
    def _node(cls, limits: Limits, parent: Budget, *, allocated: bool) -> Budget:
        node = cls.__new__(cls)
        node._init(limits, parent, allocated=allocated)
        return node

    @property
    def max_model_calls(self) -> int:
        return self.limits.model_calls

    @property
    def max_tool_calls(self) -> int:
        return self.limits.tool_calls

    @property
    def used(self) -> Counters:
        return self._used

    @property
    def model_calls(self) -> int:
        return self._used.model_calls

    @property
    def tool_calls(self) -> int:
        return self._used.tool_calls

    def child(self, limits: Limits) -> Budget:
        """A sub-budget capped by `limits` that draws on what remains here."""
        return Budget._node(limits, self, allocated=False)

    def allocate(self, limits: Limits) -> Budget:
        """Hold `limits` now for one sibling. Raises if the slice is not available."""
        chain = self._chain_until_allocated()
        for node in chain:
            for kind in ("model", "tool"):
                if node._free(kind) < limits.get(kind):
                    raise BudgetExceededError(f"Cannot hold {kind} calls for this slice")
        for node in chain:
            node._held = node._held.add(limits)
        return Budget._node(limits, self, allocated=True)

    def consume(self, kind: Kind, amount: int = 1) -> None:
        """Charge `amount` calls here and on every ancestor, or raise and change nothing."""
        if amount < 1:
            raise ValueError("amount must be positive")
        checked = self._chain_until_allocated()
        for node in checked:
            if node._free(kind) < amount:
                noun = "Model" if kind == "model" else "Tool"
                raise BudgetExceededError(f"{noun}-call limit reached")
        for node in checked:
            node._used = node._used.plus(kind, amount)
        # Above an allocated node the spend comes out of a slice already held.
        above = checked[-1]._parent
        while above is not None:
            above._held = above._held.plus(kind, -amount)
            above._used = above._used.plus(kind, amount)
            above = above._parent

    def _free(self, kind: Kind) -> int:
        return self.limits.get(kind) - self._used.get(kind) - self._held.get(kind)

    def _chain_until_allocated(self) -> list[Budget]:
        """This node and its ancestors, stopping at the first allocated node."""
        chain: list[Budget] = []
        node: Budget | None = self
        while node is not None:
            chain.append(node)
            if node._allocated:
                break
            node = node._parent
        return chain


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

    async def invoke[T](
        self, operation: Callable[[], Awaitable[T]], *, kind: Kind | None = None
    ) -> T:
        """Dispatch one leaf operation (model or tool call) under the deadline.

        Checks the deadline, then charges one `kind` call, then runs. An
        expired deadline charges nothing; a failed charge runs nothing.
        Only the runtime calls this. Composition primitives and capabilities
        call `check()` so a single timeout scope owns each external call.
        """
        self.check()
        if kind is not None:
            self.budget.consume(kind)
        async with asyncio.timeout_at(self.deadline):
            return await operation()


class Step[InputT, OutputT](Protocol):
    """A composable unit of work."""

    async def run(self, value: InputT, *, context: RunContext) -> OutputT: ...
