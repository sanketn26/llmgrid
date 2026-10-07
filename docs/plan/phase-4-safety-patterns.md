# Phase 4 addendum: guardrails, errands, planners, refiners, resampling, and routers

[All phases](../composable-agent-platform-plan.md) · [Overview and design notes](capabilities-guardrails-errands-routing.md) · [Runnable example](example-safe-router.md)

Depends on Phase 3 (`ModelStep`). Every item is an ordinary `Step`, so they nest.
Contracts go in one new interfaces file; implementations go in new `loops` modules.
Nothing here edits an existing file, and no package `__init__.py` changes; import from
the modules (Phase 8 covers exports). Only `Step`, `RunContext`, `ChatModel`, and
`ModelStep` are used, so the code carries over unchanged when budgets and contexts evolve.

| Build order | Files | Result |
| --- | --- | --- |
| 4G | interfaces `capabilities`, loops `guarded` | Input, output, and tool-call checks |
| 4H | loops `resample` | Retry until accepted; best of several |
| 4I | loops `router` | Classify and route; strict labels |
| 4J | loops `errand`, `planner` | Decompose/work/recompose; re-planning |
| 4K | loops `refine` | Draft, critique, revise; Doubting Refiner |

## Starting point

| Action | Starting file / role |
| --- | --- |
| Keep | Phase 1–3 implementations, existing `errors.py`, and every package `__init__.py` |
| Add | `interfaces/capabilities.py` and the `loops` modules `guarded`, `resample`, `router`, `errand`, `planner`, `refine` |
| Add | `loops/tests/test_loops_capabilities.py`, which needs only `llmgrid.interfaces` |

## Behaviour to preserve

- Failures are explicit: a guardrail denial, an unknown route, and exhausted resampling or
  refinement raise distinct errors. Nothing falls back implicitly and a rejected result is
  never returned.
- Guardrails never rewrite values. A guardrail that cannot decide must raise (fail closed).
- Denied tool calls are reported to the model as error results and still cost a tool call.
- `ResampleStep` retries only the failures named in `retry_on`; budget exhaustion and
  timeouts always end the run.
- Every attempt, sample, critique, and revision spends the shared budget.

## Implement these files

### `packages/interfaces/src/llmgrid/interfaces/capabilities.py`

Add the `Guardrail` protocol, `Verdict`, and the three outcome errors.

```python
"""Contracts for guardrails, resampling, and routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from llmgrid.interfaces.errors import ContractError
from llmgrid.interfaces.execution import RunContext

__all__ = [
    "Guardrail",
    "GuardrailViolationError",
    "ResamplingExhaustedError",
    "RoutingError",
    "Verdict",
]


@dataclass(frozen=True)
class Verdict:
    """The outcome of one check. A denial must say why."""

    allowed: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.allowed and not self.reason:
            raise ContractError("A denial requires a reason")

    @classmethod
    def allow(cls) -> Verdict:
        return cls(True)

    @classmethod
    def deny(cls, reason: str) -> Verdict:
        return cls(False, reason)


class Guardrail[T](Protocol):
    """Inspects a value without changing it.

    A guardrail that cannot decide must raise, not allow. Callers treat an
    exception as a failure of the run, so checks fail closed.
    """

    @property
    def name(self) -> str: ...

    async def check(self, value: T, *, context: RunContext) -> Verdict: ...


class GuardrailViolationError(RuntimeError):
    """A guardrail denied a value. `stage` is `input` or `output`."""

    def __init__(self, stage: str, guardrail: str, reason: str) -> None:
        super().__init__(f"{stage} guardrail {guardrail!r} denied: {reason}")
        self.stage = stage
        self.guardrail = guardrail
        self.reason = reason


class ResamplingExhaustedError(RuntimeError):
    """Every sampling attempt was rejected. `reasons` has one entry per attempt."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__(f"No acceptable result after {len(reasons)} attempts: {list(reasons)}")
        self.reasons = reasons


class RoutingError(RuntimeError):
    """A router could not map its input to a route."""
```

### `packages/loops/src/llmgrid/loops/guarded.py`

Add `GuardedStep`, `GuardedToolExecutor`, and the built-in `MaxLength`, `DenyPatterns`, and `ToolAllowlist` guardrails. Pattern matching is a tripwire, not a defence against prompt injection; put real policy behind the `Guardrail` protocol.

```python
"""Guardrails: checks that run before and after a step, and around tool calls."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from llmgrid.interfaces import (
    RunContext,
    Step,
    ToolCall,
    ToolExecutor,
    ToolResult,
    ToolSpec,
)
from llmgrid.interfaces.capabilities import (
    Guardrail,
    GuardrailViolationError,
    Verdict,
)

__all__ = [
    "DenyPatterns",
    "GuardedStep",
    "GuardedToolExecutor",
    "MaxLength",
    "ToolAllowlist",
]


async def _enforce[T](
    stage: str, guards: Sequence[Guardrail[T]], value: T, context: RunContext
) -> None:
    """Runs guards in order and stops at the first denial."""
    for guard in guards:
        context.check()
        verdict = await guard.check(value, context=context)
        if not verdict.allowed:
            raise GuardrailViolationError(stage, guard.name, verdict.reason)


@dataclass(frozen=True)
class GuardedStep[A, B]:
    """Checks the input, runs `step`, then checks the output.

    A denial raises `GuardrailViolationError`; nothing is repaired or replaced.
    An input denial means `step` never ran and nothing was charged to the budget.
    """

    step: Step[A, B]
    inputs: tuple[Guardrail[A], ...] = ()
    outputs: tuple[Guardrail[B], ...] = ()

    async def run(self, value: A, *, context: RunContext) -> B:
        await _enforce("input", self.inputs, value, context)
        result = await self.step.run(value, context=context)
        await _enforce("output", self.outputs, result, context)
        return result


@dataclass(frozen=True)
class GuardedToolExecutor:
    """Checks each tool call before the inner executor sees it.

    A denied call is not executed. The denial comes back as an error `ToolResult`
    so the model learns why and can choose another action. Denials are still
    charged as tool calls by the agent, so a model cannot loop on them for free.
    """

    inner: ToolExecutor
    guards: tuple[Guardrail[ToolCall], ...]

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return self.inner.specs

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        try:
            await _enforce("input", self.guards, call, context)
        except GuardrailViolationError as exc:
            return ToolResult(call.id, f"Denied: {exc.reason}", is_error=True)
        return await self.inner.execute(call, context=context)


@dataclass(frozen=True)
class MaxLength:
    """Denies text longer than `limit` characters."""

    limit: int

    def __post_init__(self) -> None:
        if self.limit < 0:
            raise ValueError("limit must be nonnegative")

    @property
    def name(self) -> str:
        return "max_length"

    async def check(self, value: str, *, context: RunContext) -> Verdict:
        if len(value) > self.limit:
            return Verdict.deny(f"{len(value)} characters exceeds the limit of {self.limit}")
        return Verdict.allow()


@dataclass(frozen=True)
class DenyPatterns:
    """Denies text matching any regular expression (case-insensitive)."""

    patterns: tuple[str, ...]

    def __post_init__(self) -> None:
        for pattern in self.patterns:
            re.compile(pattern)

    @property
    def name(self) -> str:
        return "deny_patterns"

    async def check(self, value: str, *, context: RunContext) -> Verdict:
        for pattern in self.patterns:
            if re.search(pattern, value, re.IGNORECASE):
                return Verdict.deny(f"matches denied pattern {pattern!r}")
        return Verdict.allow()


@dataclass(frozen=True)
class ToolAllowlist:
    """Denies any tool call whose name is not listed."""

    allowed: frozenset[str]

    @property
    def name(self) -> str:
        return "tool_allowlist"

    async def check(self, value: ToolCall, *, context: RunContext) -> Verdict:
        if value.name not in self.allowed:
            return Verdict.deny(f"tool {value.name!r} is not allowed")
        return Verdict.allow()
```

### `packages/loops/src/llmgrid/loops/resample.py`

Add `ResampleStep` (retry until a guardrail accepts) and `BestOfStep` (highest-scored of N sequential samples).

```python
"""Resampling: run a step again until its result is acceptable, or pick the best of several."""

from __future__ import annotations

from dataclasses import dataclass

from llmgrid.interfaces import (
    RunContext,
    Step,
)
from llmgrid.interfaces.capabilities import (
    Guardrail,
    GuardrailViolationError,
    ResamplingExhaustedError,
)

__all__ = ["BestOfStep", "ResampleStep"]


@dataclass(frozen=True)
class ResampleStep[A, B]:
    """Runs `step` up to `max_attempts` times and returns the first accepted result.

    An attempt fails when `accept` denies its result or when it raises one of
    `retry_on`. Any other error, including budget exhaustion and timeout, ends
    the run at once: only the failures you name are retried. Every attempt is
    charged to the shared budget. Exhaustion raises `ResamplingExhaustedError`
    carrying each attempt's reason; the last result is never returned silently.
    """

    step: Step[A, B]
    accept: Guardrail[B]
    max_attempts: int = 3
    retry_on: tuple[type[Exception], ...] = (GuardrailViolationError,)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")

    async def run(self, value: A, *, context: RunContext) -> B:
        reasons: list[str] = []
        for _ in range(self.max_attempts):
            context.check()
            try:
                result = await self.step.run(value, context=context)
            except self.retry_on as exc:
                reasons.append(str(exc))
                continue
            verdict = await self.accept.check(result, context=context)
            if verdict.allowed:
                return result
            reasons.append(f"{self.accept.name}: {verdict.reason}")
        raise ResamplingExhaustedError(tuple(reasons))


@dataclass(frozen=True)
class BestOfStep[A, B]:
    """Runs `step` `samples` times, scores each result, and returns the highest.

    Samples run one after another, so budget use is exact. Ties go to the
    earliest sample. A failing sample or scorer fails the whole step.
    """

    step: Step[A, B]
    scorer: Step[B, float]
    samples: int = 3

    def __post_init__(self) -> None:
        if self.samples < 1:
            raise ValueError("samples must be positive")

    async def run(self, value: A, *, context: RunContext) -> B:
        best: B | None = None
        best_score = float("-inf")
        for index in range(self.samples):
            context.check()
            candidate = await self.step.run(value, context=context)
            score = await self.scorer.run(candidate, context=context)
            if index == 0 or score > best_score:
                best, best_score = candidate, score
        assert best is not None  # samples >= 1
        return best
```

### `packages/loops/src/llmgrid/loops/router.py`

Add `RouterStep`, the free `RuleClassifier`, and the one-call `ModelClassifier` that accepts only an exact label.

```python
"""Routing: classify an input, then hand it to the matching step."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from llmgrid.interfaces import (
    ChatModel,
    ChatRequest,
    Message,
    RunContext,
    Step,
)
from llmgrid.interfaces.capabilities import (
    RoutingError,
)
from llmgrid.loops.model_step import ModelStep

__all__ = ["ModelClassifier", "RouterStep", "RuleClassifier"]


@dataclass(frozen=True)
class RouterStep[A, B]:
    """Classifies the input into a label and runs the route registered for it.

    An unknown label raises `RoutingError` unless a `default` route is given.
    Falling back is a choice you make by passing `default`, never implicit.
    """

    classifier: Step[A, str]
    routes: Mapping[str, Step[A, B]]
    default: Step[A, B] | None = None

    def __post_init__(self) -> None:
        if not self.routes:
            raise ValueError("A router needs at least one route")

    async def run(self, value: A, *, context: RunContext) -> B:
        context.check()
        label = await self.classifier.run(value, context=context)
        route = self.routes.get(label, self.default)
        if route is None:
            raise RoutingError(f"No route for label {label!r}; known: {sorted(self.routes)}")
        context.check()
        return await route.run(value, context=context)


@dataclass(frozen=True)
class RuleClassifier[A]:
    """Returns the label of the first rule whose predicate accepts the input.

    Free and deterministic: no model call. Raises `RoutingError` if none match
    and no `otherwise` label is set.
    """

    rules: Sequence[tuple[Callable[[A], bool], str]]
    otherwise: str | None = None

    async def run(self, value: A, *, context: RunContext) -> str:
        context.check()
        for predicate, label in self.rules:
            if predicate(value):
                return label
        if self.otherwise is None:
            raise RoutingError("No classification rule matched")
        return self.otherwise


@dataclass(frozen=True)
class ModelClassifier:
    """Asks a model to choose one label for a text input. Costs one model call.

    `labels` maps each label to a description shown to the model. The reply
    must be exactly one label (surrounding whitespace and case are ignored);
    anything else raises `RoutingError` rather than guessing.
    """

    model: ChatModel
    labels: Mapping[str, str]

    def __post_init__(self) -> None:
        if len(self.labels) < 2:
            raise ValueError("A classifier needs at least two labels")

    async def run(self, value: str, *, context: RunContext) -> str:
        options = "\n".join(f"- {label}: {meaning}" for label, meaning in self.labels.items())
        instructions = (
            "Classify the request into exactly one of these labels. "
            f"Reply with the label only.\n{options}\n\nRequest:\n{value}"
        )
        response = await ModelStep(self.model).run(
            ChatRequest((Message("user", instructions),)), context=context
        )
        if response.finish != "stop":
            raise RoutingError(f"Classifier did not finish: {response.finish}")
        reply = response.message.text.strip().casefold()
        matches = [label for label in self.labels if label.casefold() == reply]
        if len(matches) != 1:
            raise RoutingError(f"Classifier reply is not a known label: {response.message.text!r}")
        return matches[0]
```

### `packages/loops/src/llmgrid/loops/errand.py`

Add `ErrandStep` with `Errand` and `Part`, plus `ModelDecomposer`, `ModelRecomposer`, and the strict `parse_plan` helper. Subtasks run sequentially and independently.

```python
"""Errands: decompose a complex task, run the parts, and recompose the results."""

from __future__ import annotations

import json
from dataclasses import dataclass

from llmgrid.interfaces import (
    ChatModel,
    ChatRequest,
    ContractError,
    Message,
    RunContext,
    Step,
)
from llmgrid.loops.model_step import ModelStep

__all__ = [
    "Errand",
    "ErrandStep",
    "ModelDecomposer",
    "ModelRecomposer",
    "Part",
]


@dataclass(frozen=True)
class Part[S, R]:
    """One subtask and the result its worker produced."""

    subtask: S
    result: R


@dataclass(frozen=True)
class Errand[A, S, R]:
    """What the recomposer receives: the original task and every completed part."""

    task: A
    parts: tuple[Part[S, R], ...]


@dataclass(frozen=True)
class ErrandStep[A, S, R, C]:
    """Splits a task into subtasks, runs each with `worker`, and combines the results.

    `decomposer` returns the subtasks, `worker` handles one at a time in order,
    and `recomposer` builds the final answer from an `Errand`. A plan with no
    subtasks or more than `max_subtasks` raises `ContractError`. If any worker
    fails the errand fails; partial results are not recomposed. Workers share
    the run budget, so the plan size bounds the work.
    """

    decomposer: Step[A, tuple[S, ...]]
    worker: Step[S, R]
    recomposer: Step[Errand[A, S, R], C]
    max_subtasks: int = 8

    def __post_init__(self) -> None:
        if self.max_subtasks < 1:
            raise ValueError("max_subtasks must be positive")

    async def run(self, value: A, *, context: RunContext) -> C:
        context.check()
        subtasks = await self.decomposer.run(value, context=context)
        if not subtasks:
            raise ContractError("Decomposition produced no subtasks")
        if len(subtasks) > self.max_subtasks:
            raise ContractError(
                f"Decomposition produced {len(subtasks)} subtasks; the limit is {self.max_subtasks}"
            )
        parts: list[Part[S, R]] = []
        for subtask in subtasks:
            context.check()
            parts.append(Part(subtask, await self.worker.run(subtask, context=context)))
        context.check()
        return await self.recomposer.run(Errand(value, tuple(parts)), context=context)


def parse_plan(text: str) -> tuple[str, ...]:
    """Strictly parses a model's JSON array of nonempty subtask strings."""
    try:
        plan = json.loads(text)
    except ValueError as exc:
        raise ContractError("Plan is not valid JSON") from exc
    if not isinstance(plan, list) or not all(isinstance(i, str) and i.strip() for i in plan):
        raise ContractError("Plan must be an array of nonempty strings")
    return tuple(plan)


@dataclass(frozen=True)
class ModelDecomposer:
    """Asks a model to split a task into a JSON array of subtask strings."""

    model: ChatModel

    async def run(self, value: str, *, context: RunContext) -> tuple[str, ...]:
        prompt = (
            "Break the task below into the smallest independent subtasks that, "
            "completed in order, accomplish it. Reply with a JSON array of strings "
            f"and nothing else.\n\nTask:\n{value}"
        )
        response = await ModelStep(self.model).run(
            ChatRequest((Message("user", prompt),)), context=context
        )
        if response.finish != "stop":
            raise ContractError(f"Decomposer did not finish: {response.finish}")
        return parse_plan(response.message.text)


@dataclass(frozen=True)
class ModelRecomposer:
    """Asks a model to merge text results into one answer to the original task."""

    model: ChatModel

    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> str:
        sections = "\n\n".join(
            f"Subtask {i}: {part.subtask}\nResult: {part.result}"
            for i, part in enumerate(value.parts, start=1)
        )
        prompt = (
            "Combine the subtask results into one complete answer to the task. "
            f"Use only what the results contain.\n\nTask:\n{value.task}\n\n{sections}"
        )
        response = await ModelStep(self.model).run(
            ChatRequest((Message("user", prompt),)), context=context
        )
        if response.finish != "stop":
            raise ContractError(f"Recomposer did not finish: {response.finish}")
        return response.message.text
```

### `packages/loops/src/llmgrid/loops/planner.py`

Add `PlannerStep`, which re-plans after every subtask, and `ModelPlanner`.

```python
"""Planner: choose the next subtasks from what has been done so far."""

from __future__ import annotations

from dataclasses import dataclass

from llmgrid.interfaces import (
    ChatModel,
    ChatRequest,
    ContractError,
    Message,
    ModelStoppedError,
    RunContext,
    Step,
)
from llmgrid.loops.errand import Errand, Part, parse_plan
from llmgrid.loops.model_step import ModelStep

__all__ = ["ModelPlanner", "PlannerStep"]


@dataclass(frozen=True)
class PlannerStep[A, S, R, C]:
    """Plans, runs one subtask, and plans again with its result in hand.

    `planner` sees an `Errand` (the task plus completed parts) and returns the
    remaining subtasks; an empty tuple means the task is done. Only the first
    remaining subtask runs before the next plan, so later subtasks can adapt to
    earlier results. If the planner still wants work after `max_steps` subtasks,
    `ModelStoppedError` is raised; an empty first plan raises `ContractError`.
    Unlike `ErrandStep`, the plan costs one planner call per subtask.
    """

    planner: Step[Errand[A, S, R], tuple[S, ...]]
    worker: Step[S, R]
    recomposer: Step[Errand[A, S, R], C]
    max_steps: int = 8

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")

    async def run(self, value: A, *, context: RunContext) -> C:
        parts: list[Part[S, R]] = []
        for _ in range(self.max_steps):
            context.check()
            remaining = await self.planner.run(Errand(value, tuple(parts)), context=context)
            if not remaining:
                if not parts:
                    raise ContractError("Planner produced no subtasks")
                context.check()
                return await self.recomposer.run(Errand(value, tuple(parts)), context=context)
            subtask = remaining[0]
            parts.append(Part(subtask, await self.worker.run(subtask, context=context)))
        raise ModelStoppedError("Step limit reached before the planner finished")


@dataclass(frozen=True)
class ModelPlanner:
    """Asks a model for the remaining subtasks as a JSON array; `[]` means done."""

    model: ChatModel

    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> tuple[str, ...]:
        done = "\n\n".join(f"Done: {part.subtask}\nResult: {part.result}" for part in value.parts)
        progress = done or "Nothing done yet."
        prompt = (
            "You are planning a task step by step. Given the work done so far, reply with "
            "a JSON array of the remaining subtasks in order, or [] if the task is "
            f"complete. Reply with the JSON only.\n\nTask:\n{value.task}\n\n{progress}"
        )
        response = await ModelStep(self.model).run(
            ChatRequest((Message("user", prompt),)), context=context
        )
        if response.finish != "stop":
            raise ContractError(f"Planner did not finish: {response.finish}")
        return parse_plan(response.message.text)
```

### `packages/loops/src/llmgrid/loops/refine.py`

Add `RefineStep`, `ModelCritic`, and `ModelReviser`. One critic is a Refiner; add `ModelCritic(model, stance="doubt")` for a Doubting Refiner. A Duet is the same step with a different model behind the critic.

```python
"""Refiners: draft, critique, revise, until every critic is satisfied."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from llmgrid.interfaces import (
    ChatModel,
    ChatRequest,
    ContractError,
    Message,
    RunContext,
    Step,
)
from llmgrid.interfaces.capabilities import (
    ResamplingExhaustedError,
    Verdict,
)
from llmgrid.loops.model_step import ModelStep

__all__ = ["Draft", "ModelCritic", "ModelReviser", "RefineStep", "Revision"]


@dataclass(frozen=True)
class Draft[A, B]:
    """A candidate output with the task it answers."""

    task: A
    output: B


@dataclass(frozen=True)
class Revision[A, B]:
    """A draft plus the critics' objections, handed to the reviser."""

    draft: Draft[A, B]
    feedback: tuple[str, ...]


@dataclass(frozen=True)
class RefineStep[A, B]:
    """Drafts, then revises until every critic allows the draft.

    Each round runs all `critics` on the current draft. A denial's reason is
    feedback; any feedback triggers one `reviser` call and another round. With
    one critic this is a Refiner. Add a second critic prompted to doubt the
    answer (see `ModelCritic(stance="doubt")`) for a Doubting Refiner: the draft
    is only returned once both agree. After `max_rounds` revisions without full
    approval, `ResamplingExhaustedError` carries the feedback; an unapproved
    draft is never returned. Budget use is up to one draft, `max_rounds`
    revisions, and critics on every round.
    """

    drafter: Step[A, B]
    critics: tuple[Step[Draft[A, B], Verdict], ...]
    reviser: Step[Revision[A, B], B]
    max_rounds: int = 3

    def __post_init__(self) -> None:
        if not self.critics:
            raise ValueError("At least one critic is required")
        if self.max_rounds < 0:
            raise ValueError("max_rounds must be nonnegative")

    async def run(self, value: A, *, context: RunContext) -> B:
        context.check()
        output = await self.drafter.run(value, context=context)
        history: list[str] = []
        for round_number in range(self.max_rounds + 1):
            draft = Draft(value, output)
            feedback: list[str] = []
            for critic in self.critics:
                context.check()
                verdict = await critic.run(draft, context=context)
                if not verdict.allowed:
                    feedback.append(verdict.reason)
            if not feedback:
                return output
            history.append(f"round {round_number}: " + "; ".join(feedback))
            if round_number == self.max_rounds:
                break
            context.check()
            output = await self.reviser.run(Revision(draft, tuple(feedback)), context=context)
        raise ResamplingExhaustedError(tuple(history))


_STANCES: dict[str, str] = {
    "review": "Review the answer for correctness, completeness, and clarity.",
    "doubt": (
        "Assume the answer is wrong and look hard for errors, unsupported claims, and missed cases."
    ),
}


@dataclass(frozen=True)
class ModelCritic:
    """Asks a model to critique a text draft. Costs one model call.

    The model must reply exactly `OK` to approve. Any other reply is treated as
    an objection and becomes feedback, so a rambling or off-format critic
    blocks rather than approves.
    """

    model: ChatModel
    stance: Literal["review", "doubt"] = "review"

    async def run(self, value: Draft[str, str], *, context: RunContext) -> Verdict:
        prompt = (
            f"{_STANCES[self.stance]} If you find no real problem, reply exactly OK. "
            f"Otherwise list the problems.\n\nTask:\n{value.task}\n\nAnswer:\n{value.output}"
        )
        response = await ModelStep(self.model).run(
            ChatRequest((Message("user", prompt),)), context=context
        )
        if response.finish != "stop":
            raise ContractError(f"Critic did not finish: {response.finish}")
        reply = response.message.text.strip()
        if reply == "OK":
            return Verdict.allow()
        return Verdict.deny(reply or "critic gave an empty reply")


@dataclass(frozen=True)
class ModelReviser:
    """Asks a model to rewrite a text draft to address the feedback."""

    model: ChatModel

    async def run(self, value: Revision[str, str], *, context: RunContext) -> str:
        problems = "\n".join(f"- {item}" for item in value.feedback)
        prompt = (
            "Rewrite the answer to fix every problem listed. Reply with the revised "
            f"answer only.\n\nTask:\n{value.draft.task}\n\nAnswer:\n{value.draft.output}"
            f"\n\nProblems:\n{problems}"
        )
        response = await ModelStep(self.model).run(
            ChatRequest((Message("user", prompt),)), context=context
        )
        if response.finish != "stop":
            raise ContractError(f"Reviser did not finish: {response.finish}")
        return response.message.text
```

### `packages/loops/tests/test_loops_capabilities.py`

Add behaviour tests using fakes. Run them with `.venv/bin/pytest packages/loops/tests/test_loops_capabilities.py`.

```python
"""Guardrail, errand, resampling, and router tests; fakes depend only on llmgrid.interfaces."""

import unittest
from collections.abc import Sequence

from llmgrid.interfaces import (
    Budget,
    BudgetExceededError,
    ChatRequest,
    ChatResponse,
    ContractError,
    Message,
    ModelCapabilities,
    ModelStoppedError,
    RunContext,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from llmgrid.interfaces.capabilities import (
    GuardrailViolationError,
    ResamplingExhaustedError,
    RoutingError,
    Verdict,
)
from llmgrid.loops.errand import (
    Errand,
    ErrandStep,
    ModelDecomposer,
    ModelRecomposer,
)
from llmgrid.loops.guarded import (
    DenyPatterns,
    GuardedStep,
    GuardedToolExecutor,
    MaxLength,
    ToolAllowlist,
)
from llmgrid.loops.planner import (
    ModelPlanner,
    PlannerStep,
)
from llmgrid.loops.refine import (
    Draft,
    ModelCritic,
    ModelReviser,
    RefineStep,
    Revision,
)
from llmgrid.loops.resample import (
    BestOfStep,
    ResampleStep,
)
from llmgrid.loops.router import (
    ModelClassifier,
    RouterStep,
    RuleClassifier,
)


class TextModel:
    """Replies with prepared texts and counts model calls through the budget."""

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)
        self.requests: list[ChatRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities()

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(Message("assistant", self._texts.pop(0)), "stop")


class Echo:
    async def run(self, value: str, *, context: RunContext) -> str:
        return value


class Sequenced:
    """Returns prepared outputs in order and records how often it ran."""

    def __init__(self, *outputs: str) -> None:
        self._outputs = list(outputs)
        self.runs = 0

    async def run(self, value: str, *, context: RunContext) -> str:
        self.runs += 1
        return self._outputs.pop(0)


class Tag:
    def __init__(self, tag: str) -> None:
        self.tag = tag

    async def run(self, value: str, *, context: RunContext) -> str:
        return f"{self.tag}:{value}"


class Accept:
    """Accepts results that contain the word `ok`."""

    name = "contains_ok"

    async def check(self, value: str, *, context: RunContext) -> Verdict:
        return Verdict.allow() if "ok" in value else Verdict.deny("missing ok")


class Length:
    async def run(self, value: str, *, context: RunContext) -> float:
        return float(len(value))


class Join:
    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> str:
        return "+".join(part.result for part in value.parts)


class Splitter:
    def __init__(self, *parts: str) -> None:
        self._parts = parts

    async def run(self, value: str, *, context: RunContext) -> tuple[str, ...]:
        return self._parts


class CountingExecutor:
    def __init__(self) -> None:
        self.executed: list[str] = []

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        return (ToolSpec("read", "Read", "{}"),)

    async def execute(self, call: ToolCall, *, context: RunContext) -> ToolResult:
        self.executed.append(call.name)
        return ToolResult(call.id, "done")


def make_context(model_calls: int = 8) -> RunContext:
    return RunContext("t", Budget(model_calls, 8))


def labels(texts: Sequence[str]) -> dict[str, str]:
    return {text: f"{text} requests" for text in texts}


class GuardrailTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_denial_skips_the_step(self) -> None:
        step = Sequenced("never")
        guarded = GuardedStep(step, inputs=(MaxLength(3),))
        with self.assertRaises(GuardrailViolationError) as raised:
            await guarded.run("too long", context=make_context())
        self.assertEqual(
            (raised.exception.stage, raised.exception.guardrail), ("input", "max_length")
        )
        self.assertEqual(step.runs, 0)

    async def test_output_denial_raises(self) -> None:
        guarded = GuardedStep(Echo(), outputs=(DenyPatterns((r"secret\d+",)),))
        with self.assertRaises(GuardrailViolationError) as raised:
            await guarded.run("the SECRET42 is", context=make_context())
        self.assertEqual(raised.exception.stage, "output")

    async def test_allowed_value_passes_through(self) -> None:
        guarded = GuardedStep(Echo(), (MaxLength(10),), (DenyPatterns(("bad",)),))
        self.assertEqual(await guarded.run("fine", context=make_context()), "fine")

    async def test_denial_requires_reason(self) -> None:
        with self.assertRaises(ContractError):
            Verdict(False)

    async def test_denied_tool_call_is_reported_not_executed(self) -> None:
        inner = CountingExecutor()
        executor = GuardedToolExecutor(inner, (ToolAllowlist(frozenset({"read"})),))
        denied = await executor.execute(ToolCall("1", "delete", "{}"), context=make_context())
        allowed = await executor.execute(ToolCall("2", "read", "{}"), context=make_context())
        self.assertTrue(denied.is_error)
        self.assertEqual((denied.call_id, inner.executed), ("1", ["read"]))
        self.assertFalse(allowed.is_error)


class ResampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_first_accepted_result(self) -> None:
        step = Sequenced("bad", "ok!", "ok again")
        result = await ResampleStep(step, Accept()).run("x", context=make_context())
        self.assertEqual((result, step.runs), ("ok!", 2))

    async def test_exhaustion_reports_every_reason(self) -> None:
        step = Sequenced("a", "b")
        with self.assertRaises(ResamplingExhaustedError) as raised:
            await ResampleStep(step, Accept(), max_attempts=2).run("x", context=make_context())
        self.assertEqual(len(raised.exception.reasons), 2)

    async def test_retries_named_failures_only(self) -> None:
        def guarded() -> GuardedStep[str, str]:
            return GuardedStep(Sequenced("long text", "ok"), outputs=(MaxLength(4),))

        result = await ResampleStep(guarded(), Accept()).run("x", context=make_context())
        self.assertEqual(result, "ok")
        with self.assertRaises(GuardrailViolationError):
            await ResampleStep(guarded(), Accept(), retry_on=()).run("x", context=make_context())

    async def test_budget_error_is_never_retried(self) -> None:
        model = TextModel("one", "two")
        step = ModelClassifier(model, labels(["a", "b"]))
        resample = ResampleStep(step, Accept(), max_attempts=5, retry_on=(RoutingError,))
        with self.assertRaises(BudgetExceededError):
            await resample.run("x", context=make_context(model_calls=1))

    async def test_best_of_picks_highest_score_earliest_on_tie(self) -> None:
        step = Sequenced("aa", "bbbb", "cccc")
        result = await BestOfStep(step, Length(), samples=3).run("x", context=make_context())
        self.assertEqual(result, "bbbb")


class ErrandTests(unittest.IsolatedAsyncioTestCase):
    async def test_decompose_work_recompose(self) -> None:
        errand = ErrandStep(Splitter("a", "b"), Tag("w"), Join())
        self.assertEqual(await errand.run("task", context=make_context()), "w:a+w:b")

    async def test_empty_and_oversized_plans_are_rejected(self) -> None:
        with self.assertRaises(ContractError):
            await ErrandStep(Splitter(), Tag("w"), Join()).run("t", context=make_context())
        oversized = ErrandStep(Splitter("a", "b", "c"), Tag("w"), Join(), max_subtasks=2)
        with self.assertRaises(ContractError):
            await oversized.run("t", context=make_context())

    async def test_model_decomposer_and_recomposer(self) -> None:
        planner = TextModel('["first", "second"]')
        merger = TextModel("final answer")
        errand = ErrandStep(ModelDecomposer(planner), Tag("w"), ModelRecomposer(merger))
        self.assertEqual(await errand.run("task", context=make_context()), "final answer")
        self.assertIn("Result: w:second", merger.requests[0].messages[0].text)

    async def test_malformed_plan_is_rejected(self) -> None:
        for reply in ("not json", '{"a": 1}', '["ok", ""]'):
            with self.subTest(reply=reply), self.assertRaises(ContractError):
                await ModelDecomposer(TextModel(reply)).run("t", context=make_context())


class RouterTests(unittest.IsolatedAsyncioTestCase):
    def router(
        self, classifier: RuleClassifier[str], *, default: bool = False
    ) -> RouterStep[str, str]:
        return RouterStep(
            classifier,
            {"code": Tag("code"), "chat": Tag("chat")},
            default=Tag("fallback") if default else None,
        )

    async def test_routes_by_rule(self) -> None:
        classifier = RuleClassifier([(lambda text: "def " in text, "code")], otherwise="chat")
        router = self.router(classifier)
        self.assertEqual(await router.run("def f()", context=make_context()), "code:def f()")
        self.assertEqual(await router.run("hello", context=make_context()), "chat:hello")

    async def test_unknown_label_needs_explicit_default(self) -> None:
        classifier = RuleClassifier([(lambda text: True, "other")])
        with self.assertRaises(RoutingError):
            await self.router(classifier).run("x", context=make_context())
        routed = await self.router(classifier, default=True).run("x", context=make_context())
        self.assertEqual(routed, "fallback:x")

    async def test_model_classifier_costs_one_call_and_is_strict(self) -> None:
        context = make_context()
        classifier = ModelClassifier(TextModel(" Code \n"), labels(["code", "chat"]))
        self.assertEqual(await classifier.run("def f()", context=context), "code")
        self.assertEqual(context.budget.model_calls, 1)
        with self.assertRaises(RoutingError):
            await ModelClassifier(TextModel("I think code"), labels(["code", "chat"])).run(
                "x", context=make_context()
            )


class Critic:
    """Denies drafts until one contains `good`."""

    async def run(self, value: Draft[str, str], *, context: RunContext) -> Verdict:
        return Verdict.allow() if "good" in value.output else Verdict.deny("not good yet")


class Doubter:
    async def run(self, value: Draft[str, str], *, context: RunContext) -> Verdict:
        return Verdict.allow() if value.output.endswith("!") else Verdict.deny("needs emphasis")


class Improve:
    def __init__(self) -> None:
        self.feedback: list[tuple[str, ...]] = []

    async def run(self, value: Revision[str, str], *, context: RunContext) -> str:
        self.feedback.append(value.feedback)
        return value.draft.output + " good!"


class RefineTests(unittest.IsolatedAsyncioTestCase):
    async def test_revises_until_critic_approves(self) -> None:
        reviser = Improve()
        refine = RefineStep(Echo(), (Critic(),), reviser)
        self.assertEqual(await refine.run("draft", context=make_context()), "draft good!")
        self.assertEqual(reviser.feedback, [("not good yet",)])

    async def test_approved_draft_is_not_revised(self) -> None:
        reviser = Improve()
        refine = RefineStep(Echo(), (Critic(),), reviser)
        self.assertEqual(await refine.run("good", context=make_context()), "good")
        self.assertEqual(reviser.feedback, [])

    async def test_every_critic_must_agree(self) -> None:
        refine = RefineStep(Echo(), (Critic(), Doubter()), Improve())
        self.assertEqual(await refine.run("x", context=make_context()), "x good!")
        reviser = Improve()
        both = RefineStep(Echo(), (Critic(), Doubter()), reviser)
        await both.run("x", context=make_context())
        self.assertEqual(reviser.feedback, [("not good yet", "needs emphasis")])

    async def test_unapproved_draft_is_never_returned(self) -> None:
        refine = RefineStep(Echo(), (Critic(),), Echo2(), max_rounds=2)
        with self.assertRaises(ResamplingExhaustedError) as raised:
            await refine.run("x", context=make_context())
        self.assertEqual(len(raised.exception.reasons), 3)

    async def test_model_critic_approves_only_on_exact_ok(self) -> None:
        draft = Draft("task", "answer")
        ok = await ModelCritic(TextModel(" OK\n")).run(draft, context=make_context())
        self.assertTrue(ok.allowed)
        chatty = await ModelCritic(TextModel("OK, but see below")).run(
            draft, context=make_context()
        )
        self.assertFalse(chatty.allowed)

    async def test_model_critic_and_reviser_round_trip(self) -> None:
        critic_model = TextModel("Missing detail", "OK")
        refine = RefineStep(
            Echo(),
            (ModelCritic(critic_model, stance="doubt"),),
            ModelReviser(TextModel("better answer")),
        )
        self.assertEqual(await refine.run("answer", context=make_context()), "better answer")
        self.assertIn("wrong", critic_model.requests[0].messages[0].text)


class Echo2:
    async def run(self, value: Revision[str, str], *, context: RunContext) -> str:
        return value.draft.output


class PlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_replans_after_each_result(self) -> None:
        seen: list[int] = []

        class Planner:
            async def run(
                self, value: Errand[str, str, str], *, context: RunContext
            ) -> tuple[str, ...]:
                seen.append(len(value.parts))
                return ("a", "b")[len(value.parts) :]

        step = PlannerStep(Planner(), Tag("w"), Join())
        self.assertEqual(await step.run("t", context=make_context()), "w:a+w:b")
        self.assertEqual(seen, [0, 1, 2])

    async def test_empty_first_plan_and_step_limit(self) -> None:
        with self.assertRaises(ContractError):
            await PlannerStep(Never(), Tag("w"), Join()).run("t", context=make_context())
        with self.assertRaises(ModelStoppedError):
            await PlannerStep(Forever(), Tag("w"), Join(), max_steps=2).run(
                "t", context=make_context()
            )

    async def test_model_planner(self) -> None:
        planner = ModelPlanner(TextModel('["first", "second"]', '["second"]', "[]"))
        step = PlannerStep(planner, Tag("w"), Join())
        self.assertEqual(await step.run("t", context=make_context()), "w:first+w:second")

    async def test_model_planner_rejects_bad_json(self) -> None:
        errand = Errand[str, str, str]("t", ())
        with self.assertRaises(ContractError):
            await ModelPlanner(TextModel("sure!")).run(errand, context=make_context())


class Never:
    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> tuple[str, ...]:
        return ()


class Forever:
    async def run(self, value: Errand[str, str, str], *, context: RunContext) -> tuple[str, ...]:
        return ("more",)
```

## Before moving on

- [ ] Guard a step and a tool executor; confirm an input denial charges no budget.
- [ ] Resample a failing step; confirm `ResamplingExhaustedError` lists every reason and a budget error is never retried.
- [ ] Route with and without a `default`; confirm an unknown label raises `RoutingError`.
- [ ] Reject an empty plan, an oversized plan, and malformed model JSON.
- [ ] Confirm a refiner never returns an unapproved draft.
- [ ] Run the [example](example-safe-router.md) and the tests above.
- [ ] Mark the new public types for export in Phase 8.
