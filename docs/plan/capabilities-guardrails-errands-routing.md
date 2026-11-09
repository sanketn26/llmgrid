# Capabilities: guardrails, errands, resampling, routing, planners, and refiners

[All phases](../composable-agent-platform-plan.md)

This page is the overview and design notes. The code is in the
[Phase 4 addendum](phase-4-safety-patterns.md) as a proposed reference implementation, like
the other phases; the packages still contain the prototype. The runnable demo is
[example-safe-router](example-safe-router.md), executed by the guide checker.
Everything uses only `Step` and `RunContext`, so it carries over when Phase 1 replaces the
budget and context. No existing file is edited and no `__init__.py` changes, so import from
the modules (for example `llmgrid.loops.guarded`).

| Capability | Contracts (`llmgrid.interfaces.capabilities`) | Implementation (`llmgrid.loops`) |
| --- | --- | --- |
| Guardrails | `Guardrail`, `Verdict`, `GuardrailViolationError` | `GuardedStep`, `GuardedToolExecutor`, `MaxLength`, `DenyPatterns`, `ToolAllowlist` |
| Errands | none (uses `Step`) | `ErrandStep`, `Errand`, `Part`, `ModelDecomposer`, `ModelRecomposer` |
| Resampling | `ResamplingExhaustedError` | `ResampleStep`, `BestOfStep` |
| Routing | `RoutingError` | `RouterStep`, `RuleClassifier`, `ModelClassifier` |
| Planner | none (uses `Step`) | `PlannerStep`, `ModelPlanner` |
| Refiner, Doubting Refiner | `Verdict`, `ResamplingExhaustedError` | `RefineStep`, `ModelCritic`, `ModelReviser`, `Draft`, `Revision` |

Verify the code and the example with `.venv/bin/python tools/check_implementation_guide.py`.

## Guardrails

A `Guardrail[T]` inspects a value and returns a `Verdict` (`allow()` or `deny(reason)`).
A denial must carry a reason. Guardrails never rewrite the value.

- `GuardedStep(step, inputs=..., outputs=...)` checks the input, runs the step, then checks
  the output. Guards run in order and the first denial raises `GuardrailViolationError`
  (with `stage`, `guardrail`, and `reason`). An input denial means the step never ran, so
  nothing was charged to the budget.
- `GuardedToolExecutor(inner, guards)` checks each `ToolCall` before execution. A denied
  call is not executed; the model receives an error `ToolResult` saying why, so it can pick
  another action. The agent still charges the call to the tool budget, so denials cannot
  loop for free. Wrap the executor you pass to `ToolAgent`.
- A guardrail that cannot decide must raise rather than allow. Exceptions propagate, so
  checks fail closed.

The built-in guardrails are deliberately simple: length limits, case-insensitive regex
denylists, and a tool-name allowlist. Pattern matching is a tripwire, not a defence against
prompt injection or data leaks. Put real policy (classifiers, PII detectors, permission
checks) behind the same `Guardrail` protocol.

## Errands: decompose, work, recompose

`ErrandStep(decomposer, worker, recomposer, max_subtasks=8)`:

1. `decomposer: Step[A, tuple[S, ...]]` splits the task.
2. `worker: Step[S, R]` runs each subtask, one at a time and in order.
3. `recomposer: Step[Errand[A, S, R], C]` receives the original task and every
   `Part(subtask, result)` and builds the answer.

An empty plan or one larger than `max_subtasks` raises `ContractError`. If any worker fails
the errand fails; partial results are never recomposed. All workers share the run budget, so
the plan size bounds the work. `ModelDecomposer` asks for a JSON array of strings and rejects
anything else. `ModelRecomposer` merges text results with one model call.

Subtasks are independent and sequential. Dependencies between subtasks and parallel
execution belong with Phase 5's bounded parallel steps; use `worker` as a `ToolAgent` to give
each subtask tools.

## Resampling

- `ResampleStep(step, accept, max_attempts=3, retry_on=(GuardrailViolationError,))` reruns
  the step until `accept` (any `Guardrail` on the output) allows the result. An attempt also
  fails if it raises one of `retry_on`. Budget exhaustion, timeouts, and every other error end
  the run immediately. Exhaustion raises `ResamplingExhaustedError` with each attempt's reason;
  the last rejected result is never returned.
- `BestOfStep(step, scorer, samples=3)` takes `samples` results one after another, scores
  each with `scorer: Step[B, float]`, and returns the highest (earliest on ties).

Every attempt spends budget, so size `Budget` for the worst case. Resampling runs the same
input again; it does not feed the rejection back to the model.

## Routing

`RouterStep(classifier, routes, default=None)` runs `classifier: Step[A, str]`, then the route
registered for that label. An unknown label raises `RoutingError` unless you passed `default`;
falling back is always explicit.

- `RuleClassifier(rules, otherwise=None)` returns the label of the first matching predicate.
  No model call.
- `ModelClassifier(model, labels)` makes one model call and accepts only a reply that exactly
  names a label (whitespace and case ignored). Anything else raises `RoutingError`.

Routes can be any `Step`, including an `ErrandStep`, a `ToolAgent`, or another router.

## Planner

`PlannerStep(planner, worker, recomposer, max_steps=8)` is an errand that re-plans. The
`planner` sees an `Errand` (the task plus completed parts) and returns the remaining
subtasks; `()` means done. Only the first remaining subtask runs before the next plan, so
later work adapts to earlier results. It costs one planner call per subtask. An empty first
plan raises `ContractError`; still planning after `max_steps` raises `ModelStoppedError`.
`ModelPlanner` asks a model for a JSON array and rejects anything else. Use `ErrandStep`
when the plan can be fixed up front, `PlannerStep` when results change what comes next.

## Refiner and Doubting Refiner

`RefineStep(drafter, critics, reviser, max_rounds=3)` drafts once, then loops: every critic
(`Step[Draft, Verdict]`) checks the draft, any denial's reason becomes feedback, and the
`reviser` rewrites the draft from that feedback. The draft is returned only when all critics
allow it. If `max_rounds` revisions do not win approval, `ResamplingExhaustedError` carries
the feedback per round; an unapproved draft is never returned.

- **Refiner**: one critic. `ModelCritic(model)` reviews for correctness and clarity.
- **Doubting Refiner**: add a second critic, `ModelCritic(model, stance="doubt")`, prompted
  to assume the answer is wrong. The draft must satisfy both. Use a different model for the
  doubter when you can; a model tends to approve its own work.
- **Duet** (two agents trading drafts and critiques) is this same step with a different model
  behind the drafter/reviser and the critic. It has no separate class.

`ModelCritic` approves only on the exact reply `OK`; anything else is an objection, so an
off-format critic blocks instead of approving. Cost per run: one draft, up to `max_rounds`
revisions, and every critic each round.

## ReAct

`ToolAgent` is the ReAct loop (model reasons and requests a tool, the result is fed back,
repeat), bounded by `max_rounds` and the shared budget. Add guardrails with
`GuardedToolExecutor`.

## Not built yet

| Pattern | Why it waits |
| --- | --- |
| Memory | Belongs in `llmgrid-context` (history, compaction, artifacts in Phase 4). |
| Interlocutor, Deferrer | Need pause-for-human and resume, which is Phase 6 (approval, checkpoints). |
| Martingale | Definition not settled; as a doubling retry policy it would raise cost after each failure. |
| Self-improvement, Refiner-Dreamer-Learner | Designed below, not built. They rewrite the agent's own policy, so they need a scorer outside the proposer's control and a held-out set of asks. |

## Design: self-improving agents (not built)

A self-improving agent changes something about itself, keeps the change only if a
measurement says it helped, and otherwise restores the previous state. It does not mean the
model retrains itself. Refiner-Dreamer-Learner is one instance. The loop:

1. Snapshot the current policy.
2. Propose a changed policy.
3. Run the agent under it and measure.
4. Keep it if the score beats the best by more than a noise margin; otherwise restore.
5. Repeat until `max_rounds`.

### The invariant is the user's ask

The reusable pattern fixes one thing and varies another:

| | Role | Rules |
| --- | --- | --- |
| **The ask** | Invariant | Frozen. Never in the proposer's editable surface. A digest is checked before and after every trial, so a candidate cannot win by redefining the task. |
| **The policy** | Variable | Everything that shapes how the agent answers: system prompt, plan template, critic prompts, tool allowlist, routing rules, sample counts. A small serialisable value, so it can be snapshotted and restored. |
| **The scorer** | Fixed, from the ask | Built from the ask (acceptance criteria, tests, or a rubric the user approved). It sits outside the proposer's reach; an agent that can edit its yardstick will game it. |
| **The search** | Plug-in | A linear keep-or-restore loop and a hypothesis tree differ only in how the next parent is chosen. |

### Two levels

- **Per ask:** `RefineStep` improves the answer to one ask. The policy is the draft.
- **Across asks:** the self-improving loop improves the agent for a class of asks, and the
  policy persists between runs. It needs training asks and a **held-out** set to test on;
  without one the policy overfits to the asks it has seen, which is the usual failure.

### Hypothesis tree

A tree keeps every attempt instead of only the best so far. Each node holds a hypothesis
("the agent fails because tool results are too long; truncate them"), the policy snapshot
with that change, its measured score, and the evidence. The search picks a parent (usually
the best, with some exploration), proposes a child, measures it, and records the branch
whether the score rose or fell. Failed branches are evidence, so later proposals do not
repeat them, and an insight may only generalise from nodes that support it. A tree beats a
linear loop when changes interact, when a worse step leads somewhere better, or when
directions can be explored in parallel.

### Planned shape

```python
SelfImprove(
    ask: A,                                  # invariant, digest-checked
    run: Step[Trial[Policy, A], B],          # executes the agent under a policy
    scorer: Step[Scored[A, B], float],       # outside the proposer's reach
    proposer: Step[Evidence[Policy], Policy],
    search: Linear | Tree,
    min_improvement=..., max_rounds=...,
)
```

It returns the best policy with its score and evidence. It never applies the policy by
itself; a person adopts it. Every round is charged to the shared budget.

### Status and first slice

The workspace, snapshot, and journal contracts exist only as reference code in
[Phase 4](phase-4-composition.md) (4E experiments, 4F tree), and
[example-improvement](example-improvement.md) shows the loop on a scheduling problem. The
first slice would hold the policy as an immutable value (no filesystem snapshots), with a
linear loop, an in-memory journal, and the ask-digest check, using only `Step` and
`RunContext`. The tree search comes after it.

## Composing them

The pieces nest because each is a `Step`:

```python
safe_agent = GuardedStep(agent, inputs=(MaxLength(4000),), outputs=(DenyPatterns(...),))
reliable = ResampleStep(safe_agent, accept=quality_check, max_attempts=3)
router = RouterStep(classifier, {"simple": reliable, "complex": ErrandStep(plan, reliable, merge)})
```

## Limits

- No hard token or cost limits: budgets count calls, as elsewhere in the reference.
- Built-in guardrails are string checks; none ship for PII, toxicity, or injection.
- Errands run subtasks sequentially, without dependencies or retries per subtask
  (wrap the worker in `ResampleStep` for that).
- Self-improvement is a design only; no reference code exists for it yet.
- `RefineStep` stops at a fixed round count; there is no convergence test beyond critic approval.
- `ModelClassifier`, `ModelDecomposer`, `ModelPlanner`, and `ModelCritic` use plain-text replies, not structured output.

Adjustment: added a Phase 4 addendum and a Phase 7 example guide for these capabilities.
Reason: they depend only on `Step` and `RunContext`, which survive Phase 1.
Affected files: `docs/plan/phase-4-safety-patterns.md`, `docs/plan/example-safe-router.md`; new files
`packages/interfaces/src/llmgrid/interfaces/capabilities.py`,
`packages/loops/src/llmgrid/loops/{guarded,errand,resample,router,planner,refine}.py`
