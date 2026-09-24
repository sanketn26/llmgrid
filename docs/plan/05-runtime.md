# 5. Runtime behaviour

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- Every step receives a `RunContext` carrying the run's identity, trace position, budget ledger, deadline, event sink, clock, and ID source.
- Nested steps share one ledger and one cancellation source. A child can narrow its limits and deadline but never widen them.
- Only leaf calls (one model call or one tool call) open a timeout scope and reserve budget. Composition code just checks the deadline between operations.
- Failures are explicit: expected problems become typed results the model or caller can act on; bugs propagate; cancellation always propagates.

## The run context

The run context carries the run's identity, trace identity, deadline, cancellation, a shared budget ledger, an event sink, a clock, and an ID source (D-30). These are all execution concerns. The context is never a lookup container for arbitrary services or mutable application data.

- Nested steps share the same ledger and cancellation source.
- Child scopes may narrow deadlines and budgets. They must never reset or enlarge the parent's limits.
- A child's failure does not refund work already done outside the process.

The exact fields are in [Interfaces](04-interfaces.md#execution-and-outcomes).

## Deadlines

- Only leaf dispatches (a model call or a tool call issued by the runtime) open a timeout scope, through `RunContext.invoke`.
- Composition primitives and capabilities call `RunContext.check()` between operations. They never open nested timeout scopes.
- Code that uses a capability directly, outside the runtime (for example calling `ToolRegistry.execute` itself), owns its own timeout policy.
- Deadlines based on `loop.time()` only make sense within one process. Phase 6 checkpoints store a wall-clock deadline and convert it on resume.

## Resource accounting

The runtime tracks model requests, actual provider attempts where they can be observed, tool invocations, input and output tokens, elapsed time, and optionally cost. Each counter must be precisely defined.

- Check and reserve limits **before** dispatch.
- Settle known usage **after** completion.
- Failed or timed-out attempts can still cost money; do not refund them automatically.
- If the provider's usage is uncertain, the ledger records it as unknown.
- Parallel reservations need atomic updates in the runtime that owns them.
- Hard monetary limits need conservative reservations and provider support. Accounting after the response alone cannot enforce them.
- Transport retries inside an adapter are reported back as attempts on the response metadata and settled against the ledger. The reservation covers one logical model request; the attempt counter records what actually happened.

**Today:** the prototype enforces model and tool call counts and a monotonic deadline. It does not enforce token or cost limits and does not see retries inside providers.

## The hierarchical ledger

The prototype `Budget` is flat. Before it moves into `llmgrid.interfaces`, it is replaced by a ledger that supports narrowed child scopes:

```text
Ledger
  limits: Limits                 # this scope's own caps
  parent: Ledger | None
  used: Counters

  reserve(kind, amount=1):
      check this scope and every ancestor; fail if any would go over
      then increment this scope and every ancestor

  child(limits) -> Ledger        # limits may only be <= what remains in every ancestor

RunContext.child(*, name, deadline=None, limits=None) -> RunContext
  deadline = min(parent.deadline, deadline)
  ledger   = parent.ledger.child(limits)
  same cancellation source and run identity; a new span
```

- A reservation checks everything first and then increments everything, with no `await` in between, so it is atomic within one event loop. Thread-safe or cross-process ledgers are a Phase 5 and Phase 6 concern.
- A child's unused allowance is not handed to its siblings; it simply stays unused in the parent.
- Tests must show: a child cannot exceed its parent; two children share the parent's cap; a child that asks for more than the parent has left is rejected (the safer choice, to confirm in the ADR for Q-01).

## Failures and cancellation

| Situation | What happens |
| --- | --- |
| Tool arguments cannot be decoded | A correlated tool-error result, so the model can correct the call |
| The tool name does not exist | A correlated tool-error result |
| The tool fails in an expected, domain-specific way | An explicit error result, as the tool's contract defines |
| An unexpected programming or infrastructure error | Propagates. Never disguised as success |
| The parent is cancelled | Cancellation propagates; streams and owned resources are closed |
| The budget runs out | An explicit stopped or failed outcome. Partial text is never passed off as a final answer |
| The model truncates, refuses, or is filtered | An explicit outcome or a typed exception, as the recipe's contract says |
| The provider returns an unknown finish reason | `ProviderProtocolError` carrying the raw reason |
| An observer (event sink) fails | Telemetry is best-effort by default; a durable audit trail needs its own explicit policy |

Never catch `BaseException` in normal error conversion. Never turn cancellation into a tool error that invites more model calls.

## Retry versus repeat

These are different things and must not be confused:

- **Retry** runs a failed operation again under a specific retry policy.
- **Repeat** moves a workflow forward using a previous result or feedback.

Rules:

- Transport retries belong to the provider adapter.
- Corrective re-asks (bad tool arguments, structured output that did not decode) are repeats, not retries. They belong to the loop and consume budget (D-16).
- A tool may be retried only if it declares itself idempotent or supports an idempotency key.
- Never automatically retry a whole tool-agent iteration after one of its tools has succeeded.
- Document the maximum attempts at each layer, so retry counts do not multiply across layers.

## Observability

- Events are versioned dataclasses sent to an injected `EventSink`. The envelope, trace identity, decision records, and capture policy are specified in [Interfaces](04-interfaces.md#debuggability).
- Span and attribute names follow the OpenTelemetry GenAI semantic conventions where a convention exists (D-20). Pin the convention version in the ADR, because those conventions are still changing.
- An optional `llmgrid-loops[otel]` extra provides an `EventSink` that emits OpenTelemetry spans. Interfaces has no OpenTelemetry dependency.
- Loop-control events: iteration started and finished (with the observation), stop decision, verification result, critic verdict, compaction (with dropped ranges), offload (with the artifact reference), commit, rollback, and tampering detected.
- Redaction is a policy of the sink, not of the runtime. Message text, tool arguments, and provider state are excluded by default and included only by explicit configuration.

## Approval and durable side effects (later milestone)

A run ends as `Completed[T] | Suspended | Failed | Stopped`, each a data variant with its own fields. `Completed` carries its `VerificationResult` (D-23). `Stopped` carries a `StopReason` (D-22) and the best result so far, labelled with its verification status.

**Approval.** A tool call that needs approval produces a suspension record containing the exact call, a digest of its arguments, the approver's scope, and the checkpoint revision. Resuming checks that the approval matches that call and revision. An approval never authorises a different call generated later.

**Execution journal.** Before durable tools ship, implement an execution journal:

```text
proposed -> authorized -> dispatched -> succeeded / failed / outcome_unknown
```

- Store the operation ID before dispatch, and the result after.
- A crash between the external effect and saving the result creates `outcome_unknown`. Reconcile it using the provider's idempotency or status API, or require the application to intervene.
- A checkpoint alone cannot guarantee that an external effect happens exactly once.

**Limits to document.** Cancelling a coroutine cannot undo an external write that has already completed. Thread-backed synchronous adapters cannot reliably stop synchronous work that is already running.
