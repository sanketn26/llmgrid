# Phase 3: verified tool agent, stop rules, and replay

Depends on Phase 1; use Phase 2 adapters or the existing `ScriptedModel`.
Apply files in the order below. Keep `composition.py`, the typed tool binding,
and the scripted model. Replace `ModelStep` so it stops charging calls separately:
`RunContext.invoke(kind=...)` now owns that charge.

The agent returns `Outcome[AgentResult]`. Update consumers from `result.text` to
matching `Completed`, `Stopped`, or `Failed`; the runnable example shows the new use.
Update the old demo, integration assertions, and negative typing tests for this return
type when implementing this phase. `AcceptClaim` is explicitly self-report verification;
use an injected deterministic verifier when completion needs independent evidence.

Replay wraps both the model and tools so it cannot repeat recorded tool side effects.
Records stay in memory here; persist them with a versioned serializer only if needed.
They contain raw prompts/tool output: keep capture opt-in and redact at the boundary.

## Starting point

| Action | Starting file / role |
| --- | --- |
| Keep | Existing `loops/composition.py`, `tools/binding.py`, `network/scripted.py`, and package exports |
| Replace | `loops/model_step.py`: remove its separate budget charge |
| Replace | `loops/tool_agent.py`: change `AgentResult`/stop exceptions to explicit outcomes |
| Replace | `tools/registry.py`: add restricted views and output limits |
| Add | `interfaces/loop.py`, `loops/{policies,recording}.py`, and the phase example |
| Update | Existing demo, integration/loop assertions, and negative typing tests for the new agent return type |

## Implement these files

[All phases](../composable-agent-platform-plan.md)

### `packages/interfaces/src/llmgrid/interfaces/loop.py`

Add outcomes, observations, and explicit agent input. These replace exception-only stopping at the application boundary.

```python
from dataclasses import dataclass
from typing import Literal, Protocol

from llmgrid.interfaces import Message
from llmgrid.interfaces.execution import Counters
from llmgrid.interfaces.verification import Verification

type StopReason = Literal[
    "max_iterations",
    "no_progress",
    "repeated_failure",
    "claimed_unverified",
    "budget_exhausted",
    "deadline",
    "critic_veto",
    "verification_inconclusive",
    "model_length",
    "model_refusal",
    "model_content_filter",
    "frontier_empty",
]


@dataclass(frozen=True)
class AgentInput:
    messages: tuple[Message, ...]
    instructions: str = ""


@dataclass(frozen=True)
class AgentResult:
    text: str
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class Observation:
    index: int
    call_fingerprints: tuple[str, ...]
    errors: int
    claimed_done: bool
    verification: Verification | None = None


@dataclass(frozen=True)
class Continue:
    pass


@dataclass(frozen=True)
class Stop:
    reason: StopReason
    detail: str


type StopDecision = Continue | Stop


class StopPolicy(Protocol):
    def check(self, history: tuple[Observation, ...]) -> StopDecision: ...


@dataclass(frozen=True)
class Completed[T]:
    value: T
    verification: Verification
    usage: Counters


@dataclass(frozen=True)
class Stopped[T]:
    reason: StopReason
    detail: str
    best: T | None
    usage: Counters
    iterations: int


@dataclass(frozen=True)
class Failed[T]:
    code: str
    message: str
    best: T | None
    usage: Counters


type Outcome[T] = Completed[T] | Stopped[T] | Failed[T]
```

### `packages/loops/src/llmgrid/loops/policies.py`

Add pure stop policies. Order in `AnyOf` decides which reason wins when several policies match.

```python
from dataclasses import dataclass

from llmgrid.interfaces.loop import Continue, Observation, Stop, StopDecision, StopPolicy


@dataclass(frozen=True)
class MaxIterations:
    limit: int

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be positive")

    def check(self, history: tuple[Observation, ...]) -> StopDecision:
        if len(history) >= self.limit:
            return Stop("max_iterations", f"Reached {self.limit} rounds")
        return Continue()


@dataclass(frozen=True)
class NoProgress:
    window: int = 3

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ValueError("window must be at least two")

    def check(self, history: tuple[Observation, ...]) -> StopDecision:
        recent = history[-self.window :]
        if len(recent) < self.window:
            return Continue()
        repeated_calls = bool(recent[0].call_fingerprints) and all(
            item.call_fingerprints == recent[0].call_fingerprints for item in recent
        )
        false_claims = all(
            item.claimed_done
            and item.verification is not None
            and item.verification.verdict != "passed"
            for item in recent
        )
        if repeated_calls or false_claims:
            return Stop("no_progress", f"No progress over {self.window} rounds")
        return Continue()


@dataclass(frozen=True)
class MaxConsecutiveFailures:
    limit: int = 3

    def __post_init__(self) -> None:
        if self.limit < 1:
            raise ValueError("limit must be positive")

    def check(self, history: tuple[Observation, ...]) -> StopDecision:
        recent = history[-self.limit :]
        if len(recent) == self.limit and all(item.errors > 0 for item in recent):
            return Stop("repeated_failure", f"Tool failures in {self.limit} rounds")
        return Continue()


@dataclass(frozen=True)
class AnyOf:
    policies: tuple[StopPolicy, ...]

    def check(self, history: tuple[Observation, ...]) -> StopDecision:
        for policy in self.policies:
            result = policy.check(history)
            if isinstance(result, Stop):
                return result
        return Continue()
```

### `packages/loops/src/llmgrid/loops/model_step.py`

Replace the old model wrapper; remove its separate `budget.consume` call.

```python
from dataclasses import dataclass
from functools import partial

from llmgrid.interfaces import ChatModel, ChatRequest, ChatResponse, RunContext


@dataclass(frozen=True)
class ModelStep:
    model: ChatModel

    async def run(self, value: ChatRequest, *, context: RunContext) -> ChatResponse:
        self.model.capabilities.validate(value)
        return await context.invoke(
            partial(self.model.generate, value, context=context),
            kind="model",
            label="generate",
        )
```

### `packages/loops/src/llmgrid/loops/tool_agent.py`

Replace the old agent. Completion verification precedes the round-limit check, including on the last round.

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import partial

from llmgrid.interfaces import (
    BudgetExceededError,
    ChatModel,
    ChatRequest,
    ContractError,
    Message,
    RunContext,
    ToolCall,
    ToolExecutor,
)
from llmgrid.interfaces.loop import (
    AgentInput,
    AgentResult,
    Completed,
    Failed,
    Observation,
    Outcome,
    Stop,
    StopReason,
    Stopped,
    StopPolicy,
)
from llmgrid.interfaces.providers import ProviderError, ProviderTimeoutError
from llmgrid.interfaces.model import FinishReason
from llmgrid.interfaces.verification import Verification, Verifier
from llmgrid.loops.model_step import ModelStep
from llmgrid.loops.policies import AnyOf, MaxIterations, NoProgress


__all__ = ["AgentResult", "ToolAgent", "AcceptClaim"]
_MODEL_STOPS: dict[FinishReason, StopReason] = {
    "length": "model_length",
    "refusal": "model_refusal",
    "content_filter": "model_content_filter",
}


@dataclass(frozen=True)
class AcceptClaim:
    async def verify(self, candidate: AgentResult, *, context: RunContext) -> Verification:
        context.check()
        return Verification("passed", "self_report", ("Model claimed completion",))


def fingerprint(call: ToolCall) -> str:
    try:
        arguments = json.dumps(
            json.loads(call.arguments_json), sort_keys=True, separators=(",", ":")
        )
    except ValueError:
        arguments = call.arguments_json
    return hashlib.sha256(f"{call.name}:{arguments}".encode()).hexdigest()


@dataclass(frozen=True)
class ToolAgent:
    model: ChatModel
    tools: ToolExecutor
    verifier: Verifier[AgentResult] = field(default_factory=AcceptClaim)
    max_rounds: int = 8
    stop_policy: StopPolicy = field(default_factory=lambda: NoProgress(3))
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        if self.tools.specs and not self.model.capabilities.tool_calling:
            raise ContractError("Agent requires tool calling")

    async def run(self, value: str | AgentInput, *, context: RunContext) -> Outcome[AgentResult]:
        initial = AgentInput((Message("user", value),)) if isinstance(value, str) else value
        messages = list(initial.messages)
        if initial.instructions:
            messages.insert(0, Message("system", initial.instructions))
        observations: list[Observation] = []
        seen_ids = {call.id for message in messages for call in message.calls}
        policies = AnyOf((self.stop_policy, MaxIterations(self.max_rounds)))
        model_step = ModelStep(self.model)
        rounds = 0
        last_verification: Verification | None = None

        def candidate() -> AgentResult:
            text = next((m.text for m in reversed(messages) if m.role == "assistant"), "")
            return AgentResult(text, tuple(messages))

        def stopped(reason: StopReason, detail: str) -> Stopped[AgentResult]:
            return Stopped(reason, detail, candidate(), context.budget.used, rounds)

        try:
            while True:
                context.check()
                response = await model_step.run(
                    ChatRequest(
                        tuple(messages),
                        self.tools.specs,
                        self.max_output_tokens,
                    ),
                    context=context,
                )
                rounds += 1
                messages.append(response.message)
                errors = 0
                if response.finish == "tool_calls":
                    calls = response.message.calls
                    if any(call.id in seen_ids for call in calls):
                        raise ContractError("Tool-call ID reused")
                    seen_ids.update(call.id for call in calls)
                    for call in calls:
                        result = await context.invoke(
                            partial(self.tools.execute, call, context=context),
                            kind="tool",
                            label=f"tool:{call.name}",
                        )
                        if result.call_id != call.id:
                            raise ContractError("Tool result correlation mismatch")
                        errors += int(result.is_error)
                        messages.append(Message("tool", result=result))
                elif response.finish == "stop":
                    # Verifiers own any model/tool leaf dispatch they need.
                    last_verification = await self.verifier.verify(candidate(), context=context)
                else:
                    return stopped(_MODEL_STOPS[response.finish], "Model stopped before completion")

                observation = Observation(
                    rounds - 1,
                    tuple(fingerprint(c) for c in response.message.calls),
                    errors,
                    response.finish == "stop",
                    last_verification if response.finish == "stop" else None,
                )
                observations.append(observation)
                context.emit(f"round:{observation.index}", "returned")
                if response.finish == "stop" and last_verification is not None:
                    if last_verification.verdict == "passed":
                        return Completed(candidate(), last_verification, context.budget.used)
                    messages.append(
                        Message(
                            "user",
                            last_verification.feedback
                            or "Completion was not verified. Continue working.",
                        )
                    )
                decision = policies.check(tuple(observations))
                if isinstance(decision, Stop):
                    if decision.reason == "max_iterations" and response.finish == "stop":
                        reason: StopReason = (
                            "verification_inconclusive"
                            if (last_verification and last_verification.verdict == "inconclusive")
                            else "claimed_unverified"
                        )
                        return stopped(reason, decision.detail)
                    return stopped(decision.reason, decision.detail)
        except BudgetExceededError as exc:
            return stopped("budget_exhausted", str(exc))
        except ProviderTimeoutError as exc:
            return Failed(exc.code, str(exc), candidate(), context.budget.used)
        except TimeoutError as exc:
            return stopped("deadline", str(exc))
        except ProviderError as exc:
            return Failed(exc.code, str(exc), candidate(), context.budget.used)
```

### `packages/tools/src/llmgrid/tools/registry.py`

Replace the registry. Restricted views reject hidden tools; oversized output becomes an explicit error instead of silent truncation.

```python
from __future__ import annotations

from collections.abc import Iterable, Sequence

from llmgrid.interfaces import RunContext, ToolCall, ToolResult, ToolSpec
from llmgrid.tools.binding import BoundTool


class ToolRegistry:
    def __init__(self, tools: Sequence[BoundTool], *, output_limit: int = 8000) -> None:
        if output_limit < 1:
            raise ValueError("Output limit must be positive")
        self._output_limit = output_limit
        self._tools: dict[str, BoundTool] = {}
        for tool in tools:
            if not tool.spec.name or tool.spec.name in self._tools:
                raise ValueError("Tool names must be nonempty and unique")
            self._tools[tool.spec.name] = tool

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec for tool in self._tools.values())

    def restricted(self, names: Iterable[str]) -> ToolRegistry:
        selected = set(names)
        if selected - self._tools.keys():
            raise ValueError("Unknown tool in restricted view")
        return ToolRegistry(
            [tool for name, tool in self._tools.items() if name in selected],
            output_limit=self._output_limit,
        )

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        context.check()
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(call.id, "Unknown or unavailable tool", is_error=True)
        result = await tool.execute(call, context=context)
        if len(result.content) > self._output_limit:
            return ToolResult(
                call.id, "Output exceeds limit; request a smaller result", is_error=True
            )
        return result
```

### `packages/loops/src/llmgrid/loops/recording.py`

Add model/tool recording and request-checked replay. Replay tools return recorded results without invoking the original tool.

```python
from copy import deepcopy
from dataclasses import dataclass, field

from llmgrid.interfaces import (
    ChatModel,
    ChatRequest,
    ChatResponse,
    ModelCapabilities,
    RunContext,
    ToolCall,
    ToolExecutor,
    ToolResult,
    ToolSpec,
)
from llmgrid.interfaces.execution import Event


@dataclass
class RecordingSink:
    events: list[Event] = field(default_factory=list)

    def emit(self, event: Event) -> None:
        self.events.append(event)


@dataclass(frozen=True)
class ModelRecord:
    request: ChatRequest
    response: ChatResponse


class RecordingModel:
    def __init__(self, model: ChatModel) -> None:
        self.model = model
        self.records: list[ModelRecord] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return self.model.capabilities

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        response = await self.model.generate(request, context=context)
        self.records.append(ModelRecord(deepcopy(request), deepcopy(response)))
        return response


class ReplayModel:
    def __init__(self, records: tuple[ModelRecord, ...], capabilities: ModelCapabilities) -> None:
        self.records, self.capabilities, self.index = records, capabilities, 0

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        context.check()
        if self.index >= len(self.records):
            raise ValueError("Replay exhausted")
        record = self.records[self.index]
        if request != record.request:
            raise ValueError("Replay request differs from recording")
        self.index += 1
        return record.response


@dataclass(frozen=True)
class ToolRecord:
    call: ToolCall
    result: ToolResult


class RecordingTools:
    def __init__(self, tools: ToolExecutor) -> None:
        self.tools = tools
        self.records: list[ToolRecord] = []

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return self.tools.specs

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        result = await self.tools.execute(call, context=context)
        self.records.append(ToolRecord(deepcopy(call), deepcopy(result)))
        return result


class ReplayTools:
    def __init__(self, specs: tuple[ToolSpec, ...], records: tuple[ToolRecord, ...]) -> None:
        self.specs, self.records, self.index = specs, records, 0

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        context.check()
        if self.index >= len(self.records) or self.records[self.index].call != call:
            raise ValueError("Tool replay differs from recording")
        record = self.records[self.index]
        self.index += 1
        return record.result
```

## Run this phase

### `examples/implementation/phase3.py`

```python
import asyncio
import json
from dataclasses import dataclass

from llmgrid.interfaces import (
    Budget,
    ChatResponse,
    InvalidArgumentsError,
    Message,
    RunContext,
    ToolCall,
    ToolSpec,
)
from llmgrid.interfaces.loop import AgentResult, Completed, Stopped
from llmgrid.interfaces.verification import Verification
from llmgrid.loops.recording import RecordingModel, ReplayModel, RecordingTools, ReplayTools
from llmgrid.loops.tool_agent import ToolAgent
from llmgrid.network.scripted import ScriptedModel
from llmgrid.tools import ToolBinding, ToolRegistry


@dataclass(frozen=True)
class AddInput:
    a: int
    b: int


class Add:
    async def invoke(self, value: AddInput, *, context: RunContext) -> int:
        context.check()
        return value.a + value.b


def decode(raw: str) -> AddInput:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise InvalidArgumentsError("Expected JSON") from exc
    if not isinstance(value, dict) or set(value) != {"a", "b"}:
        raise InvalidArgumentsError("Expected exactly a and b")
    if type(value["a"]) is not int or type(value["b"]) is not int:
        raise InvalidArgumentsError("a and b must be integers")
    return AddInput(value["a"], value["b"])


class EqualsFive:
    async def verify(self, candidate: AgentResult, *, context: RunContext) -> Verification:
        context.check()
        passed = candidate.text == "5"
        return Verification(
            "passed" if passed else "failed",
            "deterministic",
            ("Expected final text: 5",),
            "Return the checked result",
        )


async def main() -> None:
    schema = json.dumps(
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        }
    )
    tools = ToolRegistry([ToolBinding(ToolSpec("add", "Add integers", schema), Add(), decode, str)])
    replies = (
        ChatResponse(
            Message("assistant", calls=(ToolCall("c1", "add", '{"a":2,"b":3}'),)), "tool_calls"
        ),
        ChatResponse(Message("assistant", "5"), "stop"),
    )
    model = RecordingModel(ScriptedModel(replies))
    recorded_tools = RecordingTools(tools)
    outcome = await ToolAgent(model, recorded_tools, EqualsFive()).run(
        "2 + 3?", context=RunContext("example", Budget(2, 1))
    )
    assert isinstance(outcome, Completed) and outcome.value.text == "5"
    assert outcome.usage.model_calls == 2 and outcome.usage.tool_calls == 1
    replay = ReplayModel(tuple(model.records), model.capabilities)
    replay_tools = ReplayTools(tools.specs, tuple(recorded_tools.records))
    repeated = await ToolAgent(replay, replay_tools, EqualsFive()).run(
        "2 + 3?", context=RunContext("example", Budget(2, 1))
    )
    assert repeated == outcome

    wrong = ScriptedModel([ChatResponse(Message("assistant", "wrong"), "stop")] * 3)
    rejected = await ToolAgent(wrong, ToolRegistry([]), EqualsFive()).run(
        "2 + 3?", context=RunContext("false-claim", Budget(3, 0))
    )
    assert isinstance(rejected, Stopped) and rejected.reason == "no_progress"
    print("Phase 3: tool cycle, verification, replay, and false-claim rejection passed")


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
.venv/bin/python examples/implementation/phase3.py
```


## Before moving on

- [ ] Tool calls, verified completion, false claims, and replay pass.
- [ ] Update callers/tests for the outcome return type.
- [ ] Add cancellation, deadline, reused-ID, and partial-history checks.

Next: [Phase 4](phase-4-composition.md).
