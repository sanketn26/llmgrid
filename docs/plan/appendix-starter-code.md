# Appendix: the starter implementation

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- Before the packages existed, the contracts and a bounded tool-calling agent were prototyped as six flat Python files using only the standard library.
- That prototype has since been moved into the packages (table at the end). The files below are kept as the validated reference, not as code to copy into the packages.
- The real design has moved on from the prototype (a hierarchical ledger, outcomes, loop control). Where they differ, the [interfaces chapter](04-interfaces.md) wins.

## How it was validated (2026-09-23)

All six Python blocks were extracted into an isolated directory and checked with:

- `python3 demo.py`: produced the expected output (Python 3.14.7).
- `python3 -m unittest test_starter.py`: all 11 tests passed (Python 3.14.7).
- `mypy` 2.3.1 in strict mode with `python_version = "3.12"`: no issues across all six files.
- `ruff` 0.16.8 with this repository's lint rule selection and line length: all checks passed; `ruff format --check`: already formatted.
- The negative typing file was confirmed to fail when an ignore is removed.

Not yet verified: running on a Python 3.12 interpreter (it was only type-checked against 3.12), and building distributions. Both remain Phase 0 gates.

## Changes from revision 1

- Exceptions renamed with an `Error` suffix (ruff N818).
- The `lambda` in the tool loop replaced with `functools.partial` (ruff B023, loop-variable capture).
- Timeout scopes opened only at leaf dispatch ([runtime](05-runtime.md#deadlines)).
- `ProviderState` and `ToolCall.origin` added (D-13, D-15).
- `FinishReason` extended with `content_filter` (D-18).
- Tests added for the provider-state round trip, per-call correlation within a batch, and provider state on non-assistant messages.

## The files

To try it, create an isolated directory and copy each block into a file with the name shown. Do not overwrite the package modules with these prototype types.

### File: `contracts.py`

```python
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol


class ContractError(ValueError):
    pass


class BudgetExceededError(RuntimeError):
    pass


class InvalidArgumentsError(ValueError):
    pass


class ModelStoppedError(RuntimeError):
    pass


type FinishReason = Literal["stop", "tool_calls", "length", "content_filter", "refusal"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    # Immutable wire boundary. A binding owns the matching runtime decoder.
    input_schema_json: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    # Raw argument text as emitted (after syntactic recovery). Decoding is the
    # binding's job, so undecodable input can still be reported to the model.
    arguments_json: str
    origin: Literal["native", "recovered"] = "native"


@dataclass(frozen=True)
class ToolResult:
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


@dataclass
class Budget:
    max_model_calls: int = 8
    max_tool_calls: int = 16
    model_calls: int = field(default=0, init=False)
    tool_calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.max_model_calls < 0 or self.max_tool_calls < 0:
            raise ValueError("Limits must be nonnegative")

    def consume(self, kind: Literal["model", "tool"]) -> None:
        # No await here: atomic within this prototype's single event loop.
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


class ChatModel(Protocol):
    @property
    def capabilities(self) -> ModelCapabilities: ...

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse: ...


class Tool[InputT, OutputT](Protocol):
    async def invoke(self, value: InputT, *, context: RunContext) -> OutputT: ...


class ToolExecutor(Protocol):
    @property
    def specs(self) -> tuple[ToolSpec, ...]: ...

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult: ...


class Step[InputT, OutputT](Protocol):
    async def run(self, value: InputT, *, context: RunContext) -> OutputT: ...
```

The schema and argument strings keep nested mutable JSON out of this minimal contract. A production implementation can expose a validated immutable JSON representation instead. Do not infer that string storage itself validates JSON. Usage, request options, structured outputs, and streaming are intentionally absent here. `Budget` is the flat prototype; The [runtime chapter](05-runtime.md#the-hierarchical-ledger) describes the hierarchical ledger that replaces it.

### File: `tooling.py`

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from contracts import InvalidArgumentsError, RunContext, Tool, ToolCall, ToolResult, ToolSpec


class BoundTool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult: ...


@dataclass(frozen=True)
class ToolBinding[InputT, OutputT]:
    spec: ToolSpec
    tool: Tool[InputT, OutputT]
    decode: Callable[[str], InputT]
    encode: Callable[[OutputT], str]

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        context.check()
        if call.name != self.spec.name:
            raise ValueError("Binding received a different tool name")
        try:
            value = self.decode(call.arguments_json)
        except InvalidArgumentsError as exc:
            return ToolResult(call.id, str(exc), is_error=True)
        # Unexpected tool/encoder errors propagate. Cancellation propagates.
        # The runtime that dispatched this call owns its timeout scope.
        output = await self.tool.invoke(value, context=context)
        return ToolResult(call.id, self.encode(output))


class ToolRegistry:
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
```

The heterogeneous registry stores a uniform `BoundTool`; individual bindings retain typed inputs and outputs. The recipe reserves tool-dispatch budget, including invalid/unknown attempts, before calling the registry. Direct registry users own their own scheduling, budget, and timeout policy.

### File: `runtime.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from contracts import (
    ChatModel,
    ChatRequest,
    ChatResponse,
    ContractError,
    Message,
    ModelStoppedError,
    RunContext,
    Step,
    ToolExecutor,
)


@dataclass(frozen=True)
class SequenceStep[A, B, C]:
    first: Step[A, B]
    second: Step[B, C]

    async def run(self, value: A, *, context: RunContext) -> C:
        # Composition checks the deadline; leaf dispatches own timeout scopes.
        context.check()
        intermediate = await self.first.run(value, context=context)
        context.check()
        return await self.second.run(intermediate, context=context)


@dataclass(frozen=True)
class ModelStep:
    model: ChatModel

    async def run(self, value: ChatRequest, *, context: RunContext) -> ChatResponse:
        context.check()
        if value.tools and not self.model.capabilities.tool_calling:
            raise ContractError("Model does not support tool calling")
        context.budget.consume("model")
        return await context.invoke(partial(self.model.generate, value, context=context))


@dataclass(frozen=True)
class AgentResult:
    text: str
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class ToolAgent:
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
```

This recipe starts a fresh conversation for each input string and has no instructions input. Conversation continuation and instructions should be introduced as explicit typed inputs, rather than hidden mutable state inside `ToolAgent`. A round is one model call and its requested tool batch. If the last round requests tools, their results are recorded locally but no further model call is allowed; the recipe then raises a stop exception. Production outcomes should preserve partial history on stops and failures.

### File: `demo.py`

```python
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from contracts import (
    Budget,
    ChatRequest,
    ChatResponse,
    InvalidArgumentsError,
    Message,
    ModelCapabilities,
    ProviderState,
    RunContext,
    ToolCall,
    ToolSpec,
)
from runtime import AgentResult, SequenceStep, ToolAgent
from tooling import ToolBinding, ToolRegistry


@dataclass(frozen=True)
class AddInput:
    a: int
    b: int


class AddTool:
    async def invoke(self, value: AddInput, *, context: RunContext) -> int:
        context.check()
        return value.a + value.b


def decode_add(raw: str) -> AddInput:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise InvalidArgumentsError("Arguments must be valid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"a", "b"}:
        raise InvalidArgumentsError("Expected exactly a and b")
    a, b = value["a"], value["b"]
    # bool is an int subclass; JSON booleans are not accepted here.
    if type(a) is not int or type(b) is not int:
        raise InvalidArgumentsError("a and b must be integers")
    return AddInput(a, b)


def make_registry() -> ToolRegistry:
    spec = ToolSpec(
        name="add",
        description="Add two integers",
        input_schema_json=json.dumps(
            {
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            }
        ),
    )
    return ToolRegistry([ToolBinding[AddInput, int](spec, AddTool(), decode_add, str)])


class ScriptedModel:
    """Offline fixture for this particular addition example, not a real LLM."""

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tool_calling=True)

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        context.check()
        last = request.messages[-1]
        if last.role == "tool":
            assert last.result is not None
            if last.result.is_error:
                return ChatResponse(Message("assistant", "Tool failed"), "stop")
            return ChatResponse(
                Message("assistant", f"The answer is {last.result.content}."),
                "stop",
            )
        return ChatResponse(
            Message(
                "assistant",
                calls=(ToolCall("call-1", "add", '{"a": 2, "b": 3}'),),
                # Stands in for e.g. a signed reasoning block the provider needs back.
                provider_state=(ProviderState("scripted", '{"turn": 1}'),),
            ),
            "tool_calls",
        )


class ExtractText:
    async def run(self, value: AgentResult, *, context: RunContext) -> str:
        context.check()
        return value.text


async def main() -> None:
    context = RunContext(
        run_id="demo-1",
        budget=Budget(max_model_calls=2, max_tool_calls=1),
        deadline=asyncio.get_running_loop().time() + 5,
    )
    agent = ToolAgent(ScriptedModel(), make_registry())
    workflow = SequenceStep[str, AgentResult, str](agent, ExtractText())
    print(await workflow.run("What is 2 + 3?", context=context))
    print(context.budget.model_calls, context.budget.tool_calls)


if __name__ == "__main__":
    asyncio.run(main())
```

Run:

```bash
python3 demo.py
```

Expected output:

```text
The answer is 5.
2 1
```

### File: `test_starter.py`

These tests exercise behavior rather than only constructing objects. They are an initial smoke/contract suite, not the complete [test matrix](10-testing-and-release.md#test-matrix).

```python
import asyncio
import unittest

from contracts import (
    Budget,
    BudgetExceededError,
    ChatRequest,
    ChatResponse,
    ContractError,
    InvalidArgumentsError,
    Message,
    ModelCapabilities,
    ProviderState,
    RunContext,
    ToolCall,
)
from demo import ScriptedModel, decode_add, make_registry
from runtime import ToolAgent


class TwoCallModel:
    """Requests two calls in one batch, then echoes the tool results in order."""

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(tool_calling=True)

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        if request.messages[-1].role == "tool":
            ids = [m.result.call_id for m in request.messages if m.result is not None]
            return ChatResponse(Message("assistant", ",".join(ids)), "stop")
        return ChatResponse(
            Message(
                "assistant",
                calls=(
                    ToolCall("c1", "add", '{"a": 1, "b": 1}'),
                    ToolCall("c2", "add", '{"a": 2, "b": 2}'),
                ),
            ),
            "tool_calls",
        )


class StarterTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_tool_cycle(self) -> None:
        context = RunContext("test", Budget(2, 1))
        result = await ToolAgent(ScriptedModel(), make_registry()).run(
            "What is 2 + 3?", context=context
        )
        self.assertEqual(result.text, "The answer is 5.")
        self.assertEqual(
            [m.role for m in result.messages], ["user", "assistant", "tool", "assistant"]
        )
        self.assertEqual(context.budget.model_calls, 2)
        self.assertEqual(context.budget.tool_calls, 1)

    async def test_provider_state_round_trips_in_history(self) -> None:
        result = await ToolAgent(ScriptedModel(), make_registry()).run(
            "What is 2 + 3?", context=RunContext("test", Budget())
        )
        self.assertEqual(
            result.messages[1].provider_state, (ProviderState("scripted", '{"turn": 1}'),)
        )

    async def test_batch_calls_keep_their_own_ids(self) -> None:
        result = await ToolAgent(TwoCallModel(), make_registry()).run(
            "question", context=RunContext("test", Budget())
        )
        self.assertEqual(result.text, "c1,c2")

    async def test_model_budget_stops_next_round(self) -> None:
        context = RunContext("test", Budget(1, 1))
        with self.assertRaises(BudgetExceededError):
            await ToolAgent(ScriptedModel(), make_registry()).run("question", context=context)
        self.assertEqual(context.budget.model_calls, 1)
        self.assertEqual(context.budget.tool_calls, 1)

    async def test_bad_arguments_preserve_correlation(self) -> None:
        result = await make_registry().execute(
            ToolCall("bad-1", "add", '{"a": true, "b": 3}'),
            context=RunContext("test", Budget()),
        )
        self.assertTrue(result.is_error)
        self.assertEqual(result.call_id, "bad-1")

    async def test_unknown_tool(self) -> None:
        result = await make_registry().execute(
            ToolCall("unknown-1", "missing", "{}"),
            context=RunContext("test", Budget()),
        )
        self.assertTrue(result.is_error)
        self.assertEqual(result.call_id, "unknown-1")

    async def test_expired_deadline_does_not_dispatch(self) -> None:
        context = RunContext("test", Budget(), asyncio.get_running_loop().time() - 1)
        with self.assertRaises(TimeoutError):
            await ToolAgent(ScriptedModel(), make_registry()).run("question", context=context)
        self.assertEqual(context.budget.model_calls, 0)

    async def test_parent_cancellation_propagates(self) -> None:
        started = asyncio.Event()

        async def operation() -> None:
            started.set()
            await asyncio.Event().wait()

        context = RunContext("test", Budget())
        task = asyncio.create_task(context.invoke(operation))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    def test_finish_reason_contract(self) -> None:
        with self.assertRaises(ContractError):
            ChatResponse(Message("assistant"), "tool_calls")

    def test_provider_state_only_on_assistant(self) -> None:
        with self.assertRaises(ContractError):
            Message("user", "hi", provider_state=(ProviderState("x", "{}"),))

    def test_decoder_rejects_extra_fields(self) -> None:
        with self.assertRaises(InvalidArgumentsError):
            decode_add('{"a": 1, "b": 2, "extra": 3}')


if __name__ == "__main__":
    unittest.main()
```

Run:

```bash
python3 -m unittest -v test_starter.py
```

### File: `typing_negative.py`

```python
"""Checked by mypy only. Each ignore must stay necessary (strict = warn_unused_ignores)."""

from demo import ExtractText, ScriptedModel, make_registry
from runtime import AgentResult, SequenceStep, ToolAgent

agent = ToolAgent(ScriptedModel(), make_registry())

ok = SequenceStep[str, AgentResult, str](agent, ExtractText())

# ToolAgent produces AgentResult, not str.
wrong_middle = SequenceStep[str, str, str](agent, ExtractText())  # type: ignore[arg-type]

# AgentResult cannot feed a step that takes str.
mismatched = SequenceStep(agent, agent)  # type: ignore[misc]
```

Run (with the strict configuration from this repository's `pyproject.toml`):

```bash
mypy --strict --python-version 3.12 .
```

## Where each prototype definition went

| Prototype definition | Destination (done) |
| --- | --- |
| Errors | `packages/interfaces/src/llmgrid/interfaces/errors.py` |
| `ToolSpec`, `ToolCall`, `ToolResult`, `ProviderState`, `Message` | `llmgrid/interfaces/values.py` |
| `FinishReason`, `ChatRequest`, `ChatResponse`, `ModelCapabilities`, `ChatModel` | `llmgrid/interfaces/model.py` |
| `Tool`, `ToolExecutor` | `llmgrid/interfaces/tools.py` |
| `Budget`, `RunContext`, `Step` | `llmgrid/interfaces/execution.py` |
| `BoundTool`, `ToolBinding` / `ToolRegistry` | `llmgrid/tools/binding.py` / `registry.py` |
| `SequenceStep` / `ModelStep` / `ToolAgent`, `AgentResult` | `llmgrid/loops/composition.py` / `model_step.py` / `tool_agent.py` |
| `ScriptedModel` (generalized to replay any list of responses and record requests) | `llmgrid/network/scripted.py` |
| `AddTool`, `decode_add`, demo | `examples/tool_agent/demo.py` |
| `test_starter.py` | Split into per-package tests (using fakes built on interfaces) and `tests/integration/test_tool_agent_flow.py` |
| `typing_negative.py` | `tests/typing/typing_negative.py` |
| Concrete provider implementations of `ChatModel` | `llmgrid.network` (Phase 2) |
| Retrieval / memory and context implementations | `llmgrid.rag` / `llmgrid.context` (Phase 4) |

The starter has no real provider adapter because the old checkout had no client implementation to adapt. Phase 2 builds the adapters against the contract suite. Do not substitute guessed SDK calls for a tested adapter.
