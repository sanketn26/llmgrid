# 7. Recipes and patterns

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- Workflows are built from a handful of typed primitives: sequence, branch, repeat, parallel, map, and retry.
- Five recipes prove the primitives work together: a tool-calling agent, a grounded answer, draft-and-review, an MCP-backed agent, and a critic-supervised experiment loop.
- Well-known patterns (ReAct, self-correction, Reflexion, the Ralph loop, plan-and-execute) are configurations of these parts, not separate agent classes.
- A recipe is itself a `Step`, so recipes nest inside each other without changes.

## Composition primitives

Rolled out in roughly this order:

| Primitive | Shape | Rule |
| --- | --- | --- |
| Sequence | `A -> B -> C` | The first step's output must match the next step's input |
| Branch | `A -> B`, choosing among compatible branches | Routing is exhaustive, or there is an explicit "unmatched" outcome |
| Repeat | `S -> S` until a condition | A bound is mandatory; state and budget carry through |
| Parallel pair | `A -> (B, C)` | Structured concurrency; shared limits; defined behaviour when a sibling is cancelled |
| Map | `tuple[A, ...] -> tuple[B, ...]` | Bounded concurrency; documented ordering |
| Retry wrapper | `A -> B` | Explicitly retryable failures and a policy for when replay is safe |

Start with Python compositions. Do not build a graph DSL, a YAML workflow format, a dynamic expression language, or a distributed scheduler. Persisting arbitrary Python callables is not a strategy for durable workflows.

**A typing caveat.** mypy rejects an incompatible `SequenceStep`, but when type parameters are inferred the error says "cannot infer value of type parameter" rather than naming the mismatched types. Examples and docs should spell out type parameters on non-trivial compositions. A `then()` builder method is worth trying for clearer errors.

## Recipe 1: bounded tool-calling agent

The workhorse: call the model, run the tools it asks for, repeat until it answers.

1. Validate the model's capabilities and the configured tools.
2. Build a request from the current history and the tool declarations.
3. Reserve a model call and call the model.
4. Look at the finish reason. Stop, refusal, content filter, and truncation are handled differently.
5. For tool calls, record the assistant message first, including its provider state.
6. Validate the call IDs and run the calls under the tool budget.
7. Append the tool results, each matched to its call, in the documented order.
8. Repeat until a final answer, or until a limit or outcome interrupts.
9. **A final answer is a claim.** With a verifier configured, the claim triggers verification: a pass returns `Completed`; a failure sends the verifier's feedback back as a message and the loop continues (D-23). Without a verifier, a claim ends the recipe as `Stopped(claimed_unverified)`, with the answer attached. An application that is happy to trust the model (for example, a plain question-answering agent) configures the built-in `AcceptClaim()` verifier, and `Completed` then records `strength=self_report`.
10. **Default stop policy:** `any_of(MaxIterations(n), NoProgress(any_signal(RepeatedCalls(3), RepeatedErrors(3)), patience=2))`. Applications may replace it, but cannot remove the budget and deadline limits (D-22).

Tools run one at a time to start with. Running them in parallel needs independence and side-effect policies; a model asking for several tools at once does not establish either.

Before this recipe is public it needs two more inputs: an explicit instructions (system) input, and a typed input for continuing a conversation instead of a bare string.

## Recipe 2: grounded answer

```text
Question -> Retrieve -> Select and render evidence -> Generate -> Validate citations
```

- `Evidence` has a source ID, content, locator, metadata, and an optional score with its kind.
- `GroundedAnswer` has the answer text and references to the source IDs it was given.
- Decide explicitly whether "no evidence" means abstaining or a clearly marked ungrounded answer. It is a policy, not a hidden fallback.
- Context assembly reserves room for output tokens and overhead, keeps mandatory instructions, and never separates a tool call from its result or its provider state. The token estimator is injected, with documented accuracy.
- Citations are extracted with the structured-output step, so `GroundedAnswer` is decoded, not parsed with regular expressions.
- Citation validation is a `Verifier`, so this recipe certifies completion the same way as every other loop.

## Recipe 3: draft and review

```text
Task -> Draft -> Evaluate -> Accepted / Rejected / Revise -> bounded repeat
```

Use a typed state holding the original task, the current draft, the feedback, and the iteration count. When revisions run out, the result is an explicit unaccepted result or a stop outcome. The latest draft is never relabelled as accepted.

**Choosing the evaluator.** The recipe accepts any `Evaluator`; which one is the application's decision. The trade-off is documented rather than hidden:

| Evaluator | Signal quality |
| --- | --- |
| An external check (tests, a schema, a verifier) | Strongest: the feedback reflects a real failure |
| A different model, or the same model with a fresh context and a rubric | Moderate: independent of the draft's reasoning |
| The same model in the same context | Weakest: models often miss their own mistakes and can turn a correct draft into a wrong one |

Every evaluation is a paid model or tool call, and the revision bound is mandatory, so a weak evaluator costs visible budget rather than looping silently.

## Recipe 4: MCP-backed tool agent

```text
MCP server(s) -> McpToolSource -> ToolExecutor -> Recipe 1
```

The real-world test of the `Tool` and `ToolExecutor` contracts, because someone else wrote the tools.

- `McpToolSource` lists a server's tools and produces bindings: the declaration is the MCP input schema, the decoder is JSON parsing plus validation with the chosen schema library (Q-03), and the output is the MCP result rendered as a `ToolResult`.
- Tool names are namespaced per server (for example `server.tool`) so two servers cannot collide. Duplicates are still rejected.
- MCP annotations such as read-only, destructive, or idempotent hints are **untrusted** unless the application marks the server as trusted. Side-effect policy, approval, and retry decisions must not rely on hints from an untrusted server.
- The application's composition root owns the server lifecycle (connect, list, close) through an async context manager. The runtime does not.
- The MCP SDK is an extra (`llmgrid-tools[mcp]`), imported only inside `llmgrid.tools.mcp`.

## Recipe 5: critic-supervised experiment loop

The worked example for [loop control](06-loop-control.md). An inner loop improves a codebase against a measured metric. An outer critic watches the trajectory, guides it, and stops it when it stops making progress.

```text
CriticLoop(critic, reserve, cadence)
  └─ Repeat(ExperimentIteration, stop=any_of(MaxIterations(n), NoProgress(MetricPlateau(...), patience), MaxConsecutiveFailures(k)))
       ExperimentIteration  (transactional, D-29)
         snapshot
         → Propose: tool loop (read code, edit through the workspace)   per-iteration caps
         → duplicate, empty-diff, and integrity checks                    D-27, D-28
         → Run: training or another measured action                       leaf call, e.g. 5-minute deadline
         → Verify: protected evaluator, noise policy                      D-23
         → Decide in code: commit if improved, else roll back             D-29
         → journal entry
```

**Inputs**, all supplied by the application:

| Input | Example |
| --- | --- |
| Goal statement | "Reduce validation loss of the 124M model within a 5-minute training budget" |
| Workspace | A git working tree; protected: `eval/`, `data/val/`, `measure.py`, `loop_config.toml` |
| Proposal model and tools | `read_file`, `search_code`, `edit_file` (workspace-scoped, `idempotent`), `read_artifact`; no commit tool, no shell |
| Measured action | A `train(config)` subprocess with a 5-minute deadline; its output offloaded |
| Verifier | Deterministic: reads `val_loss` from the protected harness; direction `minimise`; `min_delta` 0.002; held-out check every 5 commits |
| Stop policy | 50 iterations; plateau patience 8; 5 failures in a row |
| Critic | A different model; reviews every 5 iterations and after 3 rollbacks in a row; 10% reserve |
| Budget | Whole-run limits on model calls, tokens, and wall-clock time |

**Output:**

```text
Completed[ExperimentResult]              # only if a goal threshold was declared and verified
Stopped(reason, best=ExperimentResult)   # the usual ending: max_iterations, no_progress, critic_veto, budget, deadline

ExperimentResult
  best_commit: CommitId
  best_verification: VerificationResult  # including the held-out result when it ran
  baseline: VerificationResult
  journal: JournalRef
  usage: Counters
```

An open-ended optimisation ("make it as good as you can") has no completion condition, so it always ends `Stopped`, with the best verified commit. That is the honest outcome, not a failure. A loop with a declared target ("reach `val_loss` ≤ 3.20 on held-out data") can end `Completed`.

**Sketch** (illustrative, not the final API):

```python
workspace = GitWorkspace(repo, protected=("eval/**", "data/val/**", "measure.py", "loop_config.toml"))
journal = InMemoryJournal()

propose = ToolAgent(
    model=proposer,
    tools=registry.restricted(("read_file", "search_code", "edit_file", "read_artifact")),
    stop=any_of(MaxIterations(12), NoProgress(RepeatedCalls(3), patience=2)),
)

iteration = ExperimentIteration(
    workspace=workspace,
    journal=journal,
    propose=propose,
    run=TrainStep(deadline=timedelta(minutes=5)),
    verify=ValLossVerifier(harness=pristine_harness, noise=NoisePolicy(min_delta=0.002, max_samples=3)),
    decide=improves(direction="minimise"),
    limits=Limits(model_calls=15, tool_calls=40),
)

loop = CriticLoop(
    inner=Repeat(
        iteration,
        stop=any_of(
            MaxIterations(50),
            NoProgress(MetricPlateau(patience=8, min_delta=0.002, direction="minimise"), patience=1),
            MaxConsecutiveFailures(5),
        ),
    ),
    critic=ModelCritic(model=reviewer, goal=goal),
    cadence=Cadence(every=5, on=(ConsecutiveRollbacks(3), Regression(), Tampered(), ProxyDivergence())),
    reserve=Reserve(fraction=0.10),
)

outcome = await loop.run(ExperimentTask(goal=goal), context=root_context)
```

**What this recipe proves:**

- Three nested levels, each with its own stop policy and scope, share one ledger and one cancellation source.
- The critic's reserve survives an inner loop that exhausts its own budget (D-24).
- A proposal that edits a protected file is rejected, and tampering through a side channel aborts the iteration (D-27).
- A duplicate proposal is rejected before training runs (D-28).
- An iteration that does not improve leaves the workspace byte-identical (D-29).
- Killing the process mid-training and resuming rolls back the interrupted iteration and continues from the last commit.
- Swapping the proposal model, the measured action, or the verifier needs no runtime changes.

## Common loop patterns

llmgrid does not ship a class per pattern. Each is a configuration of the same parts, chosen by the application:

| Pattern | Built from | Completes when | Typical stop policy | Context strategy |
| --- | --- | --- | --- | --- |
| **ReAct** (reason, act, observe) | Recipe 1. Reasoning is model text or provider state (D-13); actions are tool calls, native or recovered from text (D-16) | The model claims completion, then the application's verifier (or `AcceptClaim()`) agrees | `MaxIterations`, `RepeatedCalls`, `RepeatedErrors` | `carry` or `compact` |
| **Self-correction from feedback** | Recipe 1 or Recipe 5; the correction signal is agent-facing tool errors and verifier feedback | A verifier passes | `MaxIterations`, `FalseClaims`, `MaxConsecutiveFailures` | `carry` or `compact` |
| **Self-refine / self-critique** | Recipe 3 with the application's chosen evaluator (see its evaluator table) | The evaluator accepts, or a verifier passes | The mandatory revision bound | `carry` |
| **Reflexion** | A `Repeat` over attempts with a journal; `JournalEntry.reflection` turned on; the journal view shown to each attempt | A verifier passes | `MaxIterations`, `FalseClaims` | `reset` or `compact` |
| **Ralph loop** (same prompt, fresh context, state on disk) | A `Repeat` whose iteration is a sub-agent over a `Workspace`, with the `no_regression()` commit rule | A verifier over the workspace passes (for example, the full test suite), not the agent's own TODO list | `MaxIterations`, `NoWorkspaceChange`, `RepeatedChange` | `reset` |
| **Critic-supervised experiment** | Recipe 5 | A verifier with a declared target passes; otherwise `Stopped` with the best commit | `MaxIterations`, `MetricPlateau`, the critic | Proposal: `carry`; loop: `reset` plus the journal |
| **Plan and execute** | A planning step (structured output) followed by a `Map` or `Repeat` over the plan's items, each a sub-agent | A verifier per item, and one for the whole | Per-item and whole-run bounds | `reset` per item |

These are starting points, not presets the library enforces. Mixing them (for example, Reflexion reflections inside a Ralph loop, or a critic over a ReAct agent) needs no new primitive.

## Recipes nest

A recipe must itself be a `Step[I, O]`. The concrete test: embed the grounded-answer recipe in a review workflow without modifying either one. Recipe 5 extends the test: the tool-agent recipe runs unchanged as the proposal step inside the experiment iteration.
