# Phase 1: budget, model, and verification contracts

Apply the files below in order. Keep the existing `values.py`, `tools.py`, and public
exports in `interfaces/__init__.py`; the additions import their new modules directly.
This phase remains standard-library-only and keeps the existing prototype running.

The first ledger enforces nested **call limits**. `Usage` records provider tokens,
including unknown values; it does not enforce token or money limits. Add those only
with an explicit reservation/settlement design and a dependable pre-call bound.

`child` shares parent limits. `allocate` holds a sibling slice for a critic or verifier;
unused allocations stay held for the run. Only consumed calls increase `used`.
The ledger is atomic within one event loop, not across threads or processes.

## Starting point

| Action | Starting file / role |
| --- | --- |
| Keep | `interfaces/{errors,values,tools,__init__}.py`: existing shared values, protocols, and exports |
| Replace | `interfaces/execution.py`: the prototype has only flat counters |
| Replace | `interfaces/model.py`: the prototype lacks usage and common request options |
| Add | `interfaces/{verification,providers}.py` and `examples/implementation/phase1.py` |

## Implement these files

[All phases](../composable-agent-platform-plan.md)

### `packages/interfaces/src/llmgrid/interfaces/execution.py`

Replace the flat budget and extend the context. The optional `kind=None` preserves old callers during migration; Phase 3 dispatch always supplies a kind.

```python
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from llmgrid.interfaces.errors import BudgetExceededError

type CallKind = Literal["model", "tool"]


@dataclass(frozen=True)
class Limits:
    model_calls: int = 8
    tool_calls: int = 16

    def __post_init__(self) -> None:
        if type(self.model_calls) is not int or type(self.tool_calls) is not int:
            raise ValueError("Limits must be integers")
        if self.model_calls < 0 or self.tool_calls < 0:
            raise ValueError("Limits must be nonnegative")


@dataclass(frozen=True)
class Counters:
    model_calls: int = 0
    tool_calls: int = 0


class Budget:
    def __init__(
        self,
        max_model_calls: int = 8,
        max_tool_calls: int = 16,
        *,
        parent: Budget | None = None,
        allocated: bool = False,
    ) -> None:
        self.limits = Limits(max_model_calls, max_tool_calls)
        self._used = Counters()
        self._parent = parent
        self._allocated = allocated
        self._held = Counters()

    @property
    def used(self) -> Counters:
        return self._used

    @property
    def model_calls(self) -> int:
        return self.used.model_calls

    @property
    def tool_calls(self) -> int:
        return self.used.tool_calls

    def remaining(self) -> Limits:
        model = self.limits.model_calls - self.model_calls - self._held.model_calls
        tool = self.limits.tool_calls - self.tool_calls - self._held.tool_calls
        if self._parent is not None and not self._allocated:
            parent = self._parent.remaining()
            model, tool = min(model, parent.model_calls), min(tool, parent.tool_calls)
        return Limits(model, tool)

    def consume(self, kind: CallKind, amount: int = 1) -> None:
        if kind not in ("model", "tool") or type(amount) is not int or amount < 0:
            raise ValueError("Invalid reservation")
        chain: list[tuple[Budget, bool]] = []
        node: Budget | None = self
        from_allocation = False
        while node is not None:
            if from_allocation:
                available = node._held.model_calls if kind == "model" else node._held.tool_calls
            else:
                remaining = node.remaining()
                available = remaining.model_calls if kind == "model" else remaining.tool_calls
            if amount > available:
                raise BudgetExceededError(f"{kind} budget exhausted")
            chain.append((node, from_allocation))
            from_allocation = from_allocation or node._allocated
            node = node._parent
        for node, held in chain:
            delta_model = amount if kind == "model" else 0
            delta_tool = amount if kind == "tool" else 0
            node._used = Counters(node.model_calls + delta_model, node.tool_calls + delta_tool)
            if held:
                node._held = Counters(
                    node._held.model_calls - delta_model, node._held.tool_calls - delta_tool
                )

    def child(self, limits: Limits) -> Budget:
        remaining = self.remaining()
        if limits.model_calls > remaining.model_calls or limits.tool_calls > remaining.tool_calls:
            raise BudgetExceededError("Child limits exceed remaining budget")
        return Budget(limits.model_calls, limits.tool_calls, parent=self)

    def allocate(self, limits: Limits) -> Budget:
        # Hold a slice for a sibling. Usage increases only when the slice is consumed.
        remaining = self.remaining()
        if limits.model_calls > remaining.model_calls or limits.tool_calls > remaining.tool_calls:
            raise BudgetExceededError("Allocation exceeds remaining budget")
        node: Budget | None = self
        while node is not None:
            node._held = Counters(
                node._held.model_calls + limits.model_calls,
                node._held.tool_calls + limits.tool_calls,
            )
            if node._allocated:
                break
            node = node._parent
        return Budget(limits.model_calls, limits.tool_calls, parent=self, allocated=True)

    def restore_used(self, used: Counters) -> None:
        if self._parent is not None or self.used != Counters():
            raise ValueError("Restore only into a fresh root budget")
        if min(used.model_calls, used.tool_calls) < 0:
            raise ValueError("Negative usage")
        if used.model_calls > self.limits.model_calls or used.tool_calls > self.limits.tool_calls:
            raise BudgetExceededError("Saved usage exceeds limits")
        self._used = used


@dataclass(frozen=True)
class Event:
    run_id: str
    path: tuple[str, ...]
    label: str
    status: Literal["started", "returned", "raised"]


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class NullSink:
    def emit(self, event: Event) -> None:
        pass


@dataclass(frozen=True)
class RunContext:
    run_id: str
    budget: Budget
    deadline: float | None = None
    path: tuple[str, ...] = ()
    events: EventSink = field(default_factory=NullSink)

    def check(self) -> None:
        if self.deadline is not None and asyncio.get_running_loop().time() >= self.deadline:
            raise TimeoutError("Run deadline exceeded")

    def child(
        self,
        name: str,
        *,
        limits: Limits | None = None,
        deadline: float | None = None,
        allocate: bool = False,
    ) -> RunContext:
        if self.deadline is not None:
            deadline = self.deadline if deadline is None else min(deadline, self.deadline)
        if allocate and limits is None:
            raise ValueError("An allocation needs explicit limits")
        budget = self.budget
        if limits is not None:
            budget = budget.allocate(limits) if allocate else budget.child(limits)
        return RunContext(self.run_id, budget, deadline, self.path + (name,), self.events)

    def emit(self, label: str, status: Literal["started", "returned", "raised"]) -> None:
        try:
            self.events.emit(Event(self.run_id, self.path, label, status))
        except Exception:
            if getattr(self.events, "critical", False):
                raise
            # Optional observability failures cannot alter execution outcomes.
            pass

    async def invoke[T](
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        kind: CallKind | None = None,
        label: str = "call",
    ) -> T:
        self.check()
        if kind is not None:
            self.budget.consume(kind)
        self.emit(label, "started")
        try:
            async with asyncio.timeout_at(self.deadline):
                result = await operation()
        except BaseException:
            self.emit(label, "raised")
            raise
        self.emit(label, "returned")
        return result


class Step[InputT, OutputT](Protocol):
    async def run(self, value: InputT, *, context: RunContext) -> OutputT: ...
```

### `packages/interfaces/src/llmgrid/interfaces/model.py`

Replace the model contracts. Defaults preserve existing scripted responses while adding usage and request validation.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from llmgrid.interfaces.errors import ContractError
from llmgrid.interfaces.execution import RunContext
from llmgrid.interfaces.values import Message, ToolSpec

type FinishReason = Literal["stop", "tool_calls", "length", "content_filter", "refusal"]


@dataclass(frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        if any(v is not None and v < 0 for v in (self.input_tokens, self.output_tokens)):
            raise ContractError("Usage cannot be negative")


@dataclass(frozen=True)
class ChatRequest:
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    max_output_tokens: int | None = None
    temperature: float | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            raise ContractError("At least one message is required")
        if self.max_output_tokens is not None and self.max_output_tokens < 1:
            raise ContractError("Output limit must be positive")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ContractError("Temperature must be between 0 and 2")


@dataclass(frozen=True)
class ChatResponse:
    message: Message
    finish: FinishReason
    usage: Usage = field(default_factory=Usage)

    def __post_init__(self) -> None:
        if self.finish not in ("stop", "tool_calls", "length", "content_filter", "refusal"):
            raise ContractError("Unknown finish reason")
        if self.message.role != "assistant":
            raise ContractError("Expected an assistant response")
        if (self.finish == "tool_calls") != bool(self.message.calls):
            raise ContractError("Finish reason and tool calls disagree")
        ids = [call.id for call in self.message.calls]
        if any(not item for item in ids) or len(ids) != len(set(ids)):
            raise ContractError("Call IDs must be nonempty and unique")


@dataclass(frozen=True)
class ModelCapabilities:
    tool_calling: bool = False
    temperature: bool = True
    output_limit: bool = True
    streaming: bool = False

    def validate(self, request: ChatRequest) -> None:
        if request.tools and not self.tool_calling:
            raise ContractError("Tool calling unsupported")
        if request.temperature is not None and not self.temperature:
            raise ContractError("Temperature unsupported")
        if request.max_output_tokens is not None and not self.output_limit:
            raise ContractError("Output limit unsupported")


class ChatModel(Protocol):
    @property
    def capabilities(self) -> ModelCapabilities: ...
    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse: ...
```

### `packages/interfaces/src/llmgrid/interfaces/verification.py`

Add this module. A verifier may spend budget through the context when it needs external calls.

```python
from dataclasses import dataclass
from typing import Literal, Protocol

from llmgrid.interfaces.execution import RunContext


@dataclass(frozen=True)
class Verification:
    verdict: Literal["passed", "failed", "inconclusive"]
    strength: Literal["deterministic", "judged", "self_report"]
    evidence: tuple[str, ...] = ()
    feedback: str = ""


class Verifier[T](Protocol):
    async def verify(self, candidate: T, *, context: RunContext) -> Verification: ...
```

### `packages/interfaces/src/llmgrid/interfaces/providers.py`

Add typed provider failures without shadowing Python timeout errors.

```python
from typing import Literal


type ProviderErrorCode = Literal[
    "authentication", "rate_limit", "server", "request", "protocol", "timeout"
]


class ProviderError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: ProviderErrorCode = "protocol",
    ) -> None:
        super().__init__(message)
        self.code = code


class ProviderTimeoutError(ProviderError, TimeoutError):
    pass
```

## Run this phase

### `examples/implementation/phase1.py`

```python
import asyncio

from llmgrid.interfaces import Budget, BudgetExceededError, RunContext
from llmgrid.interfaces.execution import Counters, Limits


async def main() -> None:
    root = Budget(3, 2)
    critic = root.allocate(Limits(1, 0))
    inner = root.child(Limits(2, 2))
    inner.consume("model", 2)
    try:
        inner.consume("model")
    except BudgetExceededError:
        pass
    else:
        raise AssertionError("Inner loop spent critic budget")
    critic.consume("model")
    assert root.used == Counters(3, 0)

    dispatched = False

    async def operation() -> int:
        nonlocal dispatched
        dispatched = True
        return 5

    context = RunContext("expired", Budget(), asyncio.get_running_loop().time() - 1)
    try:
        await context.invoke(operation, kind="model")
    except TimeoutError:
        pass
    assert not dispatched and context.budget.model_calls == 0
    print("Phase 1: nested budgets, reserved critic slice, and deadlines passed")


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
.venv/bin/python examples/implementation/phase1.py
```


## Before moving on

- [ ] The example passes with the standard library only.
- [ ] The original scripted tool demo still runs.
- [ ] Child failure leaves ancestor counters unchanged.

Next: [Phase 2](phase-2-providers.md).
