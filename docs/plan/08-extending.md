# 8. Extending llmgrid

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- Every extension is a new implementation of an existing protocol, wired up in the application's composition root. None needs a change to the runtime.
- Each checklist below says what to implement, what to declare, and what to test.
- The design rules behind these checklists are in [SOLID in the interfaces](04-interfaces.md#solid-in-the-interfaces).

## Adding a provider

- Implement generation, plus only the extra capabilities the provider actually supports.
- Translate requests and results through provider serializers.
- Normalize errors, finish reasons (D-18), and usage (D-17) accurately.
- Round-trip provider continuation state (D-13), and define the adapter's `ProviderOptions` type (D-14).
- Do syntactic recovery only (D-16).
- Declare capabilities conservatively: unknown does not mean supported.
- Run the shared model contract suite, plus provider-specific serialization tests against recorded fixtures.
- Configure the adapter in the application. No loop changes.

## Adding a tool

**Design it well.**

- **One purpose.** If its description needs "or", it is probably two tools. If two tools could plausibly answer the same request, merge them or sharpen their descriptions until the choice is obvious.
- **A clear name:** a verb and an object (`search_code`, `edit_file`). Describe when to use it and when not to, in terms of its inputs.
- **Return only what the model needs.** Paginate or limit large results, return identifiers the next tool accepts, and treat offloading as a backstop, not a design.
- **Make writes safe to repeat:** "set" rather than "change by", "upsert" rather than "insert", and expected-version guards that fail with `conflict`. Use the runtime's idempotency key for external calls that accept one.

**Declare it honestly.**

- Define the input and output types, with a schema and codec that match.
- Declare its side effect using `ToolEffect`. An undeclared effect is treated as `non_idempotent` (D-26).
- Raise `ToolFailure` with an agent-facing `ToolError` for failures you anticipate: a stable code, what failed in terms of the declared inputs, how to fix it, and whether retrying could help. Let bugs propagate.
- Inject dependencies such as clients and credentials through the constructor.
- Register a binding; duplicate names are rejected.

**Test it.**

- Malformed arguments, cancellation, and representative results.
- Each anticipated failure renders as its documented `ToolError`.
- Oversized output is offloaded.

No provider or runtime changes.

## Adding an MCP server

- Construct an `McpToolSource` in the composition root and include it in the executor.
- Choose a namespace and a trust level.
- Configure an approval policy for tools whose effects are unknown.
- No provider or runtime changes.

## Adding a stop policy or progress signal

- Implement `StopPolicy` or `ProgressSignal` as a pure function of the observation history (and the journal view, for signals). No I/O, no model calls, no budget use.
- Return `None` from a signal when it cannot judge.
- Explain each stop in numbers: "best val_loss 3.412 unchanged for 8 iterations; min_delta 0.002".
- Test with scripted observation histories. No model is needed.

## Adding a verifier

- Declare its strength (`deterministic` or `judged`) honestly.
- Read the protected evaluator (a pristine copy, or hash-checked), never the agent's working copy (D-27).
- Return `inconclusive` rather than guessing, and include evidence someone can check later.
- If it calls a model, reserve every call, use a fresh context, and never share the working model's history.
- If measurements are noisy, declare `min_delta` and a sampling policy.

## Adding a critic

- Implement `Critic.review` over observations and the journal view, not the inner transcript.
- Keep it independent: a fresh context, and preferably a different model or different evidence from the working model.
- Give it no write tools.
- Keep `Guide` feedback short and actionable ("the last six changes all tuned the learning rate; try architecture changes") and `Stop` reasons specific.
- Test with scripted trajectories: it stops on a plateau, stays quiet during steady progress, and never runs outside its reserve.

## Adding a recipe

- Define its input, state, final output, and the ways it can end without completing.
- Compose existing primitives, or implement a `Step` directly.
- Inject the capabilities it needs.
- Specify its stopping and side-effect behaviour: its default stop policy, its verifier (or say it has none), its stop reasons, and the budget each nested level receives.
- Show it nesting inside another workflow.
- Extract a new primitive only when its behaviour is useful on its own.
