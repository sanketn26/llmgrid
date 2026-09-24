# 4. Interfaces

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- `llmgrid.interfaces` defines every contract in llmgrid: value types (frozen dataclasses) and capability protocols. It uses the standard library only and contains no behaviour beyond validating its own values.
- There are two kinds of contract. **Capabilities** say what an operation means (generate a reply, run a tool, verify a result). **Steps** say how a block takes part in a composition.
- Every record can be traced back to the step that produced it, every decision records who made it and why, and a run can be replayed offline.
- Other packages conform structurally, and prove it with a typing check and shared contract test suites.
- Contracts are added in the phase of their first real consumer, not all at once.

## How to read the signatures

Signatures in this chapter use a compact notation, not Python. The exact spelling is settled in the Phase 1 ADRs.

- `Name(field, field: Type)` is a frozen dataclass.
- An indented block under a name lists its fields or methods.
- `A | B` is a union, or a set of variants for discriminated types.
- `Name(Identified)` means the protocol also requires the small `Identified` protocol (see [Traceability](#traceability)).
- `# comments` explain intent.

## The contracts at a glance

Semantic capabilities describe what an operation means. The execution contract, `Step`, describes how any block takes part in a composition:

```text
Step[A, B].run(A, context=RunContext) -> B
Sequence(Step[A, B], Step[B, C]) -> Step[A, C]
```

Small adapters connect capabilities to steps. Capabilities must not depend on orchestration: calling a retriever directly, with no loop, is a normal supported use.

| Contract | What it does | Guarantees every implementation must keep |
| --- | --- | --- |
| `ChatModel` | Produces one assistant turn from a request | An explicit finish reason; normalized failures; never executes tools; no corrective model calls (D-16); provider state round-trips (D-13) |
| `StreamingChatModel` | Streams a turn as typed events | Defined event order; exactly one terminal event; cancellation closes resources; the assembled result equals what `generate` returns |
| `Tool[I, O]` | Runs one typed tool | Declared side effects; validated input; never swallows cancellation |
| `ToolExecutor` | Routes a tool call and returns its result | Result matched to the call; unknown tool names handled explicitly |
| `Retriever` | Finds evidence for a query | Records where evidence came from; defined ordering and score meaning |
| `MemoryReader` | Recalls stored memory within a scope | Scopes stay isolated; visibility and consistency documented |
| `MemoryWriter` | Stores memory with an operation ID | Deduplication, retention, and write acknowledgement documented |
| `ContextBuilder` | Assembles the model's input from history and evidence | Fits the declared input budget or fails explicitly; keeps messages, tool pairs, and provider state intact |
| `Evaluator[T]` | Judges a draft and gives feedback | Explicit accepted / revise / rejected; feedback when needed |
| `CheckpointStore` | Saves and restores execution state | Atomic compare-and-swap; versioned serialization |
| `StopPolicy` | Decides whether a loop continues | Pure and deterministic: no I/O, no model calls, no budget use; the same history always gives the same decision |
| `ProgressSignal` | Measures whether a loop is progressing | Pure; returns `None` when it cannot judge, never a guess |
| `Verifier[T]` | Certifies a result | States its strength (`deterministic`, `judged`, or `self_report` for `AcceptClaim` only); returns `inconclusive` rather than guessing; model-backed verifiers reserve budget; reads the protected evaluator, never the agent's copy |
| `Critic` | Reviews a loop's trajectory | Runs only within its reserved budget; has no write tools; its `Stop` verdict is binding |
| `CommitRule` | Decides whether an iteration's change is kept | Pure and deterministic |
| `Compactor` | Shrinks history to fit a budget | Charged to the ledger; keeps pinned content and tool pairs; fails explicitly when the target cannot be met |
| `ArtifactStore` | Holds large outputs outside the context | Scoped to the run; stable references; documented retention; bounded reads |
| `Workspace` | Snapshots, commits, and rolls back files | Rollback is idempotent; protected paths are enforced on every write path it controls; integrity is checkable by hash |
| `ExperimentJournal` | Records every attempt of an iterative loop | Append-only; ordered; survives compaction and resume; never edited by the agent |
| `EventSink` | Receives run events | Documented ordering and observer-failure policy |

These are target contracts. The code today implements only a subset (see [Changes from today's code](#changes-from-todays-code)).

**Streaming is a separate protocol.** `StreamingChatModel` is its own protocol, not an optional method on `ChatModel`. An adapter implementing both must pass a contract test showing the assembled stream equals the non-streamed response for the same scripted input. This is decided in Phase 1 because it shapes `ChatModel`, even though streaming ships in Phase 5.

## Design principles

### For protocols

1. **Shapes and guarantees only.** Nothing in interfaces calls a model, a tool, a store, or the clock, apart from `RunContext`'s deadline check. Protocols document their semantics next to their definition.
2. **Standard library only** (D-03): no `pydantic`, no `httpx`, no OpenTelemetry.
3. **Protocols, not base classes.** Every capability is a `typing.Protocol`. Implementations conform structurally and never inherit from an interfaces class.
4. **Pure contracts say so in their signature.** `StopPolicy`, `ProgressSignal`, and `CommitRule` are synchronous and take no `RunContext`, which makes "no I/O, no model calls, no budget use" visible in the type, not just in prose.
5. **Anything that can spend takes a `RunContext`.** `ChatModel`, `Tool`, `Verifier`, `Critic`, `Compactor`, `Retriever`, and `Step` receive the context, so their spending is charged to the ledger and bounded by the deadline.
6. **Every record is traceable.** Any value that records something that happened carries a `TraceRef` placing it in the run's span tree ([Traceability](#traceability)).
7. **Every decision is explainable.** Components that decide return a decision with a reason, and the runtime records it as a `DecisionRecord` naming the component, the reason, and a digest of its inputs ([Debuggability](#debuggability)).
8. **SOLID is enforced by the shape of the interfaces**, not only by review ([SOLID](#solid-in-the-interfaces)).

### For value types

1. **Concrete domain types**, not shared mutable bags of state. Value types are frozen dataclasses that validate their own invariants in `__post_init__`, as `Message` and `ChatResponse` already do.
2. **Tuples for ordered collections** where practical.
3. **Frozen is shallow.** Copy or freeze nested structures at boundaries; `frozen=True` does not protect dictionaries.
4. **Closed vocabularies are `Literal` aliases**: `FinishReason`, `StopReason`, `ToolEffect`, `ToolErrorCode`, `VerificationStrength`, `ContextStrategy`, `JournalStatus`. Adding a member is a breaking change and is versioned as one.
5. **Variants are discriminated types**: `Continue | Stop`, `Completed | Stopped | Failed | Suspended`, `Commit | Rollback`. Never a bag of unrelated optional fields.
6. **Keep response metadata separate from messages.** Usage and finish reason belong to the response, not the message.
7. **Tool-call IDs are preserved end to end.** Never make up a different result ID.
8. **Unknown is not zero.** Missing usage is `None`. Estimated usage must be distinguishable from measured usage.
9. **No raw provider payloads in portable results** by default. Diagnostic payloads are exposed separately, with an explicit retention policy.
10. **Provider continuation state is not a raw payload.** It is data the provider needs back, so it lives on the message (D-13), while diagnostic payloads stay out.
11. **Untrusted model text is labelled.** Fields holding model-written prose that must never drive a decision (`note`, `hypothesis`, `reflection`) are documented as untrusted, and no interface method takes them as a decision input.
12. **JSON validation happens at runtime boundaries.** Python type annotations do not validate the arguments a model sends.
13. **Identifiers and serialization versions are explicit** before persistent checkpoints ship.
14. **No exception class shadows a builtin name** (D-19).

## Module layout

Every public name is re-exported from `llmgrid.interfaces`, so consumers import from one place. "Lands" is the phase in which the contract is first needed by a real consumer.

| Module | Contents | Lands |
| --- | --- | --- |
| `values` | `Message`, `ToolCall`, `ToolResult`, `ToolSpec`, `ProviderState`, JSON value aliases | Exists; extended in Phase 1 |
| `model` | `ChatModel`, `StreamingChatModel` (shape only), `ChatRequest`, `ChatResponse`, `ResponseMetadata`, `Usage`, `FinishReason`, `ModelCapabilities`, `ProviderOptions` | Exists; extended in Phase 1 |
| `execution` | `RunContext`, `Step`, `Ledger`, `Limits`, `Counters`, `CounterKind`, `Clock`, `IdSource` | Exists as a flat `Budget`; ledger, clock, and IDs in Phase 1 |
| `tracing` | `TraceRef`, `ComponentInfo`, `Identified`, `DecisionRecord`, `DecisionKind` | Phase 1 |
| `outcomes` | `Outcome[T]` = `Completed[T] \| Stopped[T] \| Failed \| Suspended`, `StopReason`, `ErrorInfo` | Phase 3 (`Completed`, `Stopped`, `Failed`); `Suspended` in Phase 6 |
| `tools` | `Tool`, `ToolExecutor`, `ToolEffect`, `ToolInvocation`, `ToolError`, `ToolErrorCode` | Exists; extended in Phase 1 |
| `loop` | `IterationObservation`, `ToolCallDigest`, `StopDecision` (`Continue \| Stop`), `StopPolicy`, `ProgressSignal`, `ProgressReading`, `ContextStrategy` | Phase 1; first used in Phase 3 |
| `verification` | `Verifier`, `VerificationResult`, `VerificationStrength`, `EvidenceItem`, `Evaluator`, `Evaluation` | `Verifier` in Phase 1 (used in Phase 3); `Evaluator` in Phase 4 |
| `critic` | `Critic`, `CriticInput`, `CriticVerdict` (`Continue \| Guide \| Stop`) | Phase 4 |
| `workspace` | `Workspace`, `IntegritySource`, `SnapshotId`, `CommitId`, `WorkspaceDiff`, `DiffStats`, `PathPattern`, `CommitRule`, `CommitDecision` (`Commit \| Rollback`) | Phase 4 |
| `journal` | `JournalReader`, `ExperimentJournal`, `JournalEntry`, `JournalView`, `JournalStatus`, `JournalRef` | Phase 4 |
| `context` | `ContextBuilder`, `ContextRequest`, `ContextBundle`, `Compactor`, `CompactionRequest`, `CompactionResult`, `TokenEstimator`, `ArtifactStore`, `ArtifactRef`, `MemoryReader`, `MemoryWriter` | `ContextBuilder` in Phase 3 (Q-07); the rest in Phase 4 |
| `retrieval` | `Retriever`, `RetrievalQuery`, `RetrievalResult`, `Evidence` | Phase 4 |
| `events` | `EventSink`, the `Event` envelope, versioned event payloads, `CapturePolicy` | Phase 3 (envelope, in-memory and null sinks); OpenTelemetry export in Phase 5 |
| `checkpoint` | `CheckpointStore`, `Checkpoint` | Phase 6 |
| `errors` | The error families below, including `ToolFailure` and `ProtectedPathError` | Exists; extended in Phase 1 |

## Signatures

### Execution and outcomes

```text
Limits(model_calls, tool_calls, input_tokens, output_tokens, cost_micros)   # each int | None; None = unlimited
Counters(same fields, each int)                                             # usage so far
CounterKind = model_calls | tool_calls | input_tokens | output_tokens | cost_micros

Ledger
  limits: Limits
  used: Counters
  remaining() -> Limits
  reserve(kind: CounterKind, amount: int = 1) -> None   # check every ancestor, then increment every ancestor; raises on exhaustion
  settle(usage: Usage) -> None                          # record measured usage after a call
  child(limits: Limits) -> Ledger                       # rejects limits above what remains (Q-01)

RunContext
  run_id: str
  trace: TraceRef                                       # this step's span
  ledger: Ledger
  deadline: float | None                                # event-loop time
  events: EventSink                                     # NullSink by default
  clock: Clock                                          # injectable, for deterministic tests and replay
  ids: IdSource                                         # injectable, for deterministic tests and replay
  check() -> None                                       # raises on an expired deadline
  invoke(operation, *, kind: CounterKind, label: str) -> T
      # leaf dispatch only: reserves budget, opens the timeout scope,
      # opens a child span, and emits dispatch and settle events
  child(*, name: str, limits: Limits | None, deadline: float | None, reserve: Limits | None) -> RunContext
      # name extends the step path; new span ID; same run and cancellation source
      # reserve: budget set aside for a sibling (the critic, a final verification)

Clock.monotonic() -> float
Clock.wall() -> datetime
IdSource.new(prefix: str) -> str                        # "span_", "art_", "snap_", ...

Step[A, B].run(value: A, *, context: RunContext) -> B

Outcome[T] = Completed[T] | Stopped[T] | Failed | Suspended
Completed[T](value: T, verification: VerificationResult, usage: Counters, trace: TraceRef)
Stopped[T](reason: StopReason, decision: DecisionRecord, level: str, iterations: int,
           best: T | None, best_verification: VerificationResult | None,
           journal: JournalRef | None, usage: Counters, trace: TraceRef)
Failed(error: ErrorInfo, usage: Counters, trace: TraceRef)   # expected, typed failures only; defects propagate
ErrorInfo(type: str, message: str, code: str | None)         # a description of the error, not the exception object

StopReason = max_iterations | no_progress | repeated_failure | claimed_unverified
           | budget_exhausted | deadline | critic_veto | verification_inconclusive
```

A recipe is a `Step[I, Outcome[O]]`. Plain compositions such as `SequenceStep` stay `Step[A, B]`; only loops that can end without completing return an `Outcome`. How the ledger and deadlines behave is described in [Runtime](05-runtime.md).

### Messages

```text
Message
  role: system | user | assistant | tool
  text: str
  calls: tuple[ToolCall, ...]                # assistant only
  result: ToolResult | None                  # tool only, exactly one
  provider_state: tuple[ProviderState, ...]  # assistant only; opaque

ToolCall
  id: str                                    # nonempty, unique per run
  name: str
  arguments_json: str                        # raw text after syntactic recovery (D-15)
  origin: native | recovered

ProviderState
  provider: str                              # adapter-defined key, for example "anthropic"
  payload_json: str                          # opaque to everything except that adapter
```

Rules for `ProviderState`:

- The runtime and context builders carry it unchanged and never look inside it.
- An adapter serializes only state whose `provider` key is its own and ignores the rest. This is documented, not silent: switching providers mid-conversation drops the other provider's continuation, and the adapter's documentation says what that costs (for example, loss of earlier reasoning).
- A context builder that trims history must keep an assistant message's `provider_state` with that message, and must never keep tool calls while dropping the state the provider needs alongside them.
- Checkpoints store it verbatim.
- Phase 2 must verify each first-party provider's current round-trip requirements (at the time of writing: Anthropic thinking blocks with signatures during tool use, Gemini thought signatures, and OpenAI Responses reasoning items) and record them in the adapter's ADR rather than trusting this list.

A convenience method `ToolCall.parsed_arguments()` may parse the JSON and raise `InvalidArgumentsError`. It does not validate against a schema.

### Model

```text
ChatRequest
  messages: tuple[Message, ...]
  tools: tuple[ToolSpec, ...]
  max_output_tokens: int | None
  temperature: float | None
  tool_choice: auto | none | required | ToolName | None
  response_format: JsonSchemaFormat | None
  provider_options: tuple[ProviderOptions, ...]

ChatResponse(message: Message, finish: FinishReason, metadata: ResponseMetadata)
ResponseMetadata(usage: Usage, attempts: int | None, model_id: str | None)   # Q-02; also the provider's request ID when available
Usage(input_tokens, output_tokens, cached_input_tokens, reasoning_tokens)   # each int | None (D-17)

ModelCapabilities
  tool_calling: none | prompted | native | strict
  parallel_tool_calls: bool | None
  structured_output: none | prompted | native
  streaming: bool
  input_window: int | None
  max_output_tokens: int | None
  usage_reliable: bool                  # openai_compat profiles set this per endpoint
  finish_reason_reliable: bool

ChatModel
  capabilities: ModelCapabilities
  generate(request: ChatRequest, *, context: RunContext) -> ChatResponse
```

**Request options (D-14).**

- Portable fields are validated against `ModelCapabilities` before the request is sent (D-12). An unsupported portable field fails; it is never silently dropped.
- `ProviderOptions` is a protocol with a `provider` key. Each adapter defines its own frozen options type, for example `AnthropicOptions(thinking_budget_tokens=..., cache_breakpoints=...)`.
- An adapter uses the options with its own key, rejects malformed options for itself, and ignores other providers' options. One request can therefore carry options for several providers, which keeps fallback compositions possible.
- Adapters never accept untyped `extra_body` dictionaries through the portable request. If a raw-body escape hatch is kept, it lives on the adapter's constructor, where it is clearly provider-specific.

**Finish reasons (D-18).**

| Normalized | Meaning | What the adapter must do |
| --- | --- | --- |
| `stop` | Natural completion | There must be no tool calls |
| `tool_calls` | The model requested tools | There must be at least one complete tool call. Providers that report `stop` alongside tool calls are normalized to `tool_calls` |
| `length` | Output limit reached | Partial tool calls are discarded and never executed. The partial text may be reported, but recipes treat it as non-completion |
| `content_filter` | The provider's safety system stopped the output | Distinct from a model refusal |
| `refusal` | The model declined | Only when the provider reports it structurally |

An unknown provider reason raises `ProviderProtocolError` carrying the raw reason, rather than being mapped to a guess. Transport and API failures are exceptions, never a finish reason.

**Structured output.**

- `ModelCapabilities.structured_output` is `native`, `prompted`, or `none`.
- `ChatRequest.response_format` carries the schema.
- A `StructuredStep[T]` in `llmgrid.loops` pairs a schema with a decoder, exactly like a tool binding, and returns `T` or a typed decode failure.
- `prompted` mode is allowed only when the application opts in, because it is a weaker guarantee.
- A decoding failure is an explicit outcome. Asking again is a bounded `Repeat` that consumes budget, never a loop inside an adapter (D-16).

### Tools

```text
ToolEffect = read_only | idempotent | non_idempotent
ToolSpec(name, description, input_schema_json, effect: ToolEffect = non_idempotent, output_limit_chars: int | None)

ToolInvocation                         # passed to the tool alongside its decoded input
  call_id: str
  idempotency_key: str                 # stable: derived from the run ID and the call ID
  context: RunContext

ToolErrorCode = invalid_argument | not_found | conflict | permission_denied | precondition_failed
              | too_large | rate_limited | timeout | unavailable | protected_path
ToolError
  code: ToolErrorCode
  message: str                         # what failed, in terms of the tool's declared inputs
  hint: str | None                     # how to fix it: valid values, expected shape, next step
  retryable: bool                      # whether the same call may succeed later unchanged
  details_json: str | None             # for example, up to N valid alternatives

ToolResult(call_id, content: str, error: ToolError | None, artifact: ArtifactRef | None)
    # is_error is derived from error; artifact is set when the output was offloaded

Tool[I, O].invoke(value: I, *, invocation: ToolInvocation) -> O    # raises ToolFailure(ToolError) for anticipated failures

ToolExecutor
  specs: tuple[ToolSpec, ...]
  execute(call: ToolCall, *, context: RunContext) -> ToolResult
  restricted(names: Iterable[str]) -> ToolExecutor                  # a view with only these tools; unknown names rejected
```

#### Typed tools and schemas

Each registered tool binds four things: a declaration (the schema the model sees), a decoder, a typed implementation, and an encoder. The declaration and decoder must agree on required fields, unknown-field policy, nullability, numeric handling, and constraints.

- For now, use explicit decoders for small schemas. Later, choose one maintained validation library and define the supported JSON Schema dialect (Q-03). Do not grow a partial home-made validator and imply it implements the standard.
- The legacy `ArgSpec` checks in `legacy/llm_port/spec/tools.py` are exactly such a partial validator. Keep them only as an internal helper for rendering prompted-tool instructions until Q-03 is decided. Never expose them as validation.
- Provider schema restrictions belong in serializers. If a provider cannot express a requirement, keep the local validation and either reject the configuration or expose the documented approximation. Never claim stronger guarantees than the adapter delivers.

#### Side effects and idempotency (D-26)

| Effect | Meaning | Retry and scheduling |
| --- | --- | --- |
| `read_only` | No external effect | May be retried and cached, and run in parallel once Phase 5 allows it |
| `idempotent` | Repeating the call with the same input leaves the same end state, for example "set file X to content Y" or "upsert record K" | May be retried under the retry policy |
| `non_idempotent` | Repeating it repeats the effect, for example "append", "send email", "create order" | Never retried automatically. Needs approval or the Phase 6 journal before it may run in a durable context, and is rejected inside a transactional iteration ([Loop control](06-loop-control.md#transactional-iterations)) |

- An undeclared effect is treated as `non_idempotent`. MCP hints stay untrusted unless the server is trusted ([Recipe 4](07-recipes-and-patterns.md#recipe-4-mcp-backed-tool-agent)).
- The runtime's idempotency key covers retries of one call. It is deliberately not derived from the arguments: when a model issues the same write again under a new call ID, that is a new intent. A tool that must deduplicate by content (for example a write the model may repeat after compaction) derives its own key from its arguments and documents it (Q-13).
- Design writes to be safe to repeat where possible: prefer "set to" over "change by", "upsert" over "insert", and writes guarded by an expected version (`if_match`) that fail with `conflict` instead of overwriting.

#### Errors written for the agent (D-26)

Anticipated tool failures are written for the model that has to act on them, not for a human reading logs. Rendering rules:

1. **Use the declared argument names.** "`path` is required; received keys `file`, `mode`", not "KeyError: 'path'".
2. **Say how to recover.** List valid values (bounded, for example the first 20), give the expected shape, or name the tool that finds the missing thing ("use `list_files` to see available paths").
3. **Leak nothing.** No stack traces, internal hostnames, credentials, or raw provider payloads.
4. **Keep it short.** The rendered error has a size limit (default 1,000 characters), and truncation says it truncated.
5. **Decoder rejections look the same.** A rejected argument (D-15) renders through the same shape with `code=invalid_argument`, so malformed arguments and domain failures look alike to the model.
6. **Repetition is flagged.** When the same call fails with the same code twice in a row, the second error says so ("this is the second identical failure"). The repetition is also a no-progress signal ([Loop control](06-loop-control.md#detecting-no-progress)).
7. **Defects still propagate.** Unexpected exceptions are not converted ([Runtime](05-runtime.md#failures-and-cancellation)). An agent-facing error is for failures the tool anticipated; it never disguises a bug as something the model can fix.

#### Keeping the tool set tight

A small set of focused, non-overlapping tools beats a large one: every extra tool costs context and invites the wrong choice. The runtime enforces what it can check:

- Unique names, nonempty descriptions within a length limit, and declared effects.
- **Per-step allow-lists.** `ToolExecutor.restricted(names)` returns a view exposing only those tools. Each recipe step and each sub-agent gets its own view, so for example Recipe 5's proposal step never sees the critic's tools, and vice versa.
- **A tool-count ceiling per step** (default: warn above 20; can be configured to fail).
- **Tool-output size limits**, with offloading ([Loop control](06-loop-control.md#offloading)).

Whether two tools overlap in purpose cannot be checked; [Extending llmgrid](08-extending.md#adding-a-tool) gives design guidance.

### Errors

The useful parts of the old `errors.py` carry over into `llmgrid.interfaces.errors`, renamed so nothing shadows a builtin (D-19):

| Family | Examples | Raised by |
| --- | --- | --- |
| `ContractError` | Invalid message shape, correlation mismatch, reused call ID | Core values, runtime |
| `ConfigurationError` | Missing credentials, unsupported capability requested | Adapters, runtime pre-dispatch validation |
| `ProviderError` | `AuthenticationError`, `RateLimitError`, `ServerError`, `ContextLengthError`, `ProviderTimeoutError`, `ProviderProtocolError` | Adapters |
| `BudgetExceededError`, `ModelStoppedError` | Ledger exhaustion, non-completion | Runtime, prototype only; replaced by outcomes in Phase 3 |
| `InvalidArgumentsError` | Decoder rejection | Tool bindings; converted to a correlated error result |
| `ToolFailure` | A tool's anticipated failure, carrying a `ToolError` | Tools; converted to a correlated agent-facing error result |
| `ProtectedPathError` | A write to a protected path (D-27) | `Workspace`; converted to an agent-facing error with `code=protected_path` |

- `ProviderTimeoutError` subclasses both `ProviderError` and the builtin `TimeoutError`, so `except TimeoutError` still catches it.
- Run-deadline expiry raises the builtin `TimeoutError` from `asyncio.timeout`.
- Library exceptions carry the `TraceRef` of the span where they were raised, and the call ID for tool errors ([Debuggability](#debuggability)).

### Loop control

How these are used is explained in [Loop control](06-loop-control.md).

```text
ToolCallDigest(name: str, arguments_sha256: str)       # name + canonical hash of arguments_json

IterationObservation
  trace: TraceRef
  level: str                                # for example "experiment"
  index: int                                # 0-based within this level
  elapsed_seconds: float
  usage: Counters                           # this iteration's ledger delta
  tool_calls: tuple[ToolCallDigest, ...]
  tool_errors: tuple[ToolErrorCode, ...]    # in order
  workspace_changed: bool | None            # None when the level has no workspace
  change_digest: str | None                 # hash of the workspace diff
  verification: VerificationResult | None
  decision: committed | rolled_back | aborted | none
  claimed_done: bool                        # the model said it was finished
  note: str                                 # the model's own summary; untrusted, never used for decisions

StopDecision = Continue | Stop(reason: StopReason, detail: str)
StopPolicy(Identified).check(history: tuple[IterationObservation, ...]) -> StopDecision                  # sync, pure

ProgressReading(progressed: bool | None, detail: str)
ProgressSignal(Identified).read(history: tuple[IterationObservation, ...],
                                journal: JournalView | None) -> ProgressReading                         # sync, pure

ContextStrategy = carry | compact | reset
```

### Verification and evaluation

```text
VerificationStrength = deterministic | judged | self_report
EvidenceItem(kind: str, summary: str, artifact: ArtifactRef | None)   # for example a test report digest

VerificationResult
  trace: TraceRef
  verdict: passed | failed | inconclusive
  strength: VerificationStrength
  verifier: ComponentInfo
  metric: float | None
  samples: tuple[float, ...]            # repeated measurements, when the verifier repeats to handle noise
  evidence: tuple[EvidenceItem, ...]
  feedback: str | None                  # shown to the model when verification fails

Verifier[T](Identified).verify(candidate: T, *, context: RunContext) -> VerificationResult

Evaluation(decision: accepted | revise | rejected, feedback: str | None)
Evaluator[T].evaluate(candidate: T, *, context: RunContext) -> Evaluation
```

### Critic

```text
CriticInput
  goal: str                                      # the application's statement of the goal
  trajectory: tuple[IterationObservation, ...]   # possibly windowed
  journal: JournalView | None                    # a digest of all attempts; recent ones in full
  metric_history: tuple[float, ...]
  remaining: Limits                              # what the inner loop has left

CriticVerdict = Continue | Guide(feedback: str) | Stop(reason: str)
Critic(Identified).review(value: CriticInput, *, context: RunContext) -> CriticVerdict
```

### Workspace and commit rules

```text
SnapshotId, CommitId, PathPattern = str (distinct NewType aliases)
DiffStats(files_changed: int, lines_added: int, lines_removed: int)
WorkspaceDiff(digest: str, stats: DiffStats, paths: tuple[str, ...])

IntegritySource.integrity() -> str        # digest over protected paths; all a verifier needs

Workspace (also an IntegritySource)
  protected: tuple[PathPattern, ...]      # D-27
  integrity() -> str
  snapshot() -> SnapshotId
  diff(since: SnapshotId) -> WorkspaceDiff
  commit(since: SnapshotId, message: str) -> CommitId
  rollback(to: SnapshotId) -> None        # idempotent: rolling back twice is the same as once

CommitDecision = Commit | Rollback(reason: str)
CommitRule(Identified).decide(candidate: VerificationResult, best: VerificationResult | None,
                              diff: WorkspaceDiff) -> CommitDecision                                     # sync, pure
```

`Workspace` methods are async because they touch the filesystem or run git. `CommitRule` is sync and pure.

### Journal

```text
JournalStatus = started | committed | rolled_back | aborted | tampered | duplicate

JournalEntry
  trace: TraceRef
  iteration: int
  status: JournalStatus
  snapshot: SnapshotId
  hypothesis: str                       # the model's stated intent; untrusted
  reflection: str | None                # the model's lesson from this attempt (Reflexion); untrusted
  change_digest: str | None
  diff_stats: DiffStats | None
  verification: VerificationResult | None
  decision_reason: str                  # written by code, for example "mean +0.012 > threshold 0.008"
  usage: Counters
  commit: CommitId | None
  decisions: tuple[DecisionRecord, ...]

JournalView(recent: tuple[JournalEntry, ...], digest: tuple[str, ...])   # older entries as one-line digests
JournalRef(journal_id: str)

JournalReader                           # what critics, signals, and debugging tools receive
  ref: JournalRef
  entries() -> tuple[JournalEntry, ...]
  view(recent: int) -> JournalView
  seen(change_digest: str) -> bool

ExperimentJournal (also a JournalReader) # only the loop that owns the journal may write
  append(entry: JournalEntry) -> None
```

### Context and artifacts

```text
TokenEstimator.estimate(messages: tuple[Message, ...]) -> int              # sync; documented accuracy

ContextRequest(history, pinned: tuple[int, ...], journal: JournalView | None, evidence: tuple[Evidence, ...],
               input_budget_tokens: int, strategy: ContextStrategy)
ContextBundle(messages: tuple[Message, ...], dropped: tuple[tuple[int, int], ...], estimated_tokens: int)
ContextBuilder.build(request: ContextRequest, *, context: RunContext) -> ContextBundle

CompactionRequest(history, pinned, target_tokens)
    # pinned: instructions, the task statement, and critic guidance still in force
CompactionResult(history, summary: Message | None, dropped: tuple[tuple[int, int], ...])
    # summary is marked as a compaction summary; dropped ranges are recorded in events
Compactor(Identified).compact(request: CompactionRequest, *, context: RunContext) -> CompactionResult

ArtifactRef(id: str, size: int, media_type: str, preview: str, sha256: str, trace: TraceRef)
    # preview: the first N lines, or a tool-supplied summary; trace: the span that produced it
ArtifactStore
  put(content: str | bytes, media_type: str, *, run_id: str) -> ArtifactRef   # scoped to the run
  read(ref: ArtifactRef, offset: int, limit: int) -> str                      # bounded

MemoryReader.recall(query: MemoryQuery) -> tuple[MemoryRecord, ...]          # scoped; shapes settled in Phase 4
MemoryWriter.remember(command: RememberCommand) -> MemoryReceipt             # carries an operation ID
```

### Retrieval

```text
Evidence(source_id, content, locator: str | None, metadata_json: str | None, score: float | None, score_kind: str | None)
RetrievalQuery(text, filters_json: str | None, limit: int)
RetrievalResult(evidence: tuple[Evidence, ...])
Retriever.retrieve(query: RetrievalQuery, *, context: RunContext) -> RetrievalResult
```

## Seven kinds of state

These may share storage, but they must never be merged into one `Memory` interface.

| State | Example | Lifetime |
| --- | --- | --- |
| Conversation | User and model messages, tool results, provider continuation state | A session |
| Long-term memory | A persisted user preference | Across sessions |
| Evidence | Retrieved passages with source IDs | Usually one query or run |
| Assembled model context | The messages and evidence selected to fit a token budget | One model call |
| Execution checkpoint | Pending call, completed steps, budget ledger, approval status | Until completion or expiry |
| Offloaded artifact | A 40,000-line tool output replaced in the context by a handle | One run, or the store's declared retention |
| Experiment journal | Each attempt's hypothesis, change digest, verification, and commit or rollback decision | The loop that owns it, plus resume |

## Traceability

**Goal:** from any outcome, journal entry, artifact, or event, you can walk back to the exact step, model call, tool call, and decision that produced it, and forward from any step to everything it caused.

```text
TraceRef
  run_id: str
  span_id: str
  parent_span_id: str | None
  step_path: str        # readable position, e.g. "critic_loop/experiment[7]/propose/tool_loop[3]/tool:edit_file"

ComponentInfo
  kind: str             # "stop_policy", "verifier", "chat_model", "tool", ...
  name: str             # "MetricPlateau", "ValLossVerifier", "anthropic"
  version: str | None   # package or component version
  config_json: str      # the configuration that affects decisions (thresholds, model ID); never secrets

Identified.component: ComponentInfo    # a small protocol required by every decision-making protocol
```

Rules:

1. **One span per step and per leaf dispatch.** `RunContext.child(name=...)` creates a span and extends `step_path`; `RunContext.invoke` creates a span for each model or tool call. Span IDs come from the injected `IdSource`.
2. **IDs link; they are never regenerated.** `ToolCall.id` → `ToolResult.call_id` → the tool span → the observation's `ToolCallDigest` → the journal entry. The provider's own request ID, when available, goes into `ResponseMetadata` and the dispatch event.
3. **Every record carries a `TraceRef`:** `IterationObservation`, `VerificationResult`, `JournalEntry`, `DecisionRecord`, `ArtifactRef`, every `Outcome` variant, and every `Event`. A record that points at another record uses its ID (`JournalRef`, `ArtifactRef.id`, `SnapshotId`, `CommitId`, span IDs), never a copy.
4. **Every decision names its decider** through `ComponentInfo`, including its configuration, so "which threshold stopped this run?" can be answered from the record.
5. **Commits made by a `Workspace` carry git trailers** with the run ID, span ID, and journal iteration, so repository history links back to the trace.
6. **Trace identity maps onto OpenTelemetry** in Phase 5 (D-20): `run_id` becomes the trace ID, `span_id` the span ID, and `step_path` and `ComponentInfo` become attributes. Interfaces stay free of the OpenTelemetry dependency.

| Question | Where the answer is |
| --- | --- |
| Why did the run stop? | `Stopped.decision`: kind, decider, reason, input digest, span |
| Which verifier certified this, and with what evidence? | `Completed.verification`: `ComponentInfo`, strength, evidence, artifact references |
| What did iteration 7 try, and why was it rolled back? | `JournalEntry` 7: hypothesis, diff stats, verification, and the commit decision record |
| Which model call produced this tool call? | The tool span's parent is the model dispatch span; the event carries the request digest |
| Where did this artifact come from? | `ArtifactRef.trace` |
| What did compaction drop? | The `DecisionRecord` with `kind=compaction`, which lists the dropped ranges, and the compaction event |
| What did the critic say, and did the loop follow it? | The `DecisionRecord` with `kind=critic`, and the guidance message in history under the next iteration's span |

## Debuggability

**Goal:** a failed or surprising run can be understood from its records, reproduced offline, and narrowed down to one component.

```text
DecisionKind = stop | progress | commit | critic | verification | compaction | offload | claim

DecisionRecord
  kind: DecisionKind
  decided_by: ComponentInfo
  outcome: str                  # "stop:no_progress", "rollback", "guide", "passed", ...
  reason: str                   # numbers, not adjectives: "best 3.412 unchanged for 8 iterations; min_delta 0.002"
  inputs_sha256: str            # digest of the inputs the decider saw
  trace: TraceRef

Event
  schema_version: int
  event_id: str
  kind: str                     # run.started, step.started, model.dispatched, model.settled,
                                # tool.dispatched, tool.settled, iteration.finished, decision.recorded,
                                # artifact.offloaded, workspace.committed, workspace.rolled_back,
                                # tamper.detected, run.finished
  at_wall: datetime
  at_monotonic: float
  trace: TraceRef
  payload_json: str             # versioned per kind; subject to CapturePolicy

EventSink.emit(event: Event) -> None    # must not raise into the run; failures are counted

CapturePolicy
  message_text: bool = False
  tool_arguments: bool = False
  tool_output: bool = False
  provider_state: bool = False
  max_payload_chars: int
```

Rules:

1. **Decisions are records, not side effects.** A pure decider returns a decision with a reason. The runtime turns it into a `DecisionRecord`, attaches it to the observation or journal entry, and emits `decision.recorded`. A component never has to know about tracing to be traceable.
2. **Runs can be replayed.** With `CapturePolicy` fully enabled, a run's events contain every model request and response and every tool result. A `ReplayModel` and a replaying `ToolExecutor` (test utilities, not interfaces) re-run the same composition offline and must reproduce the same decisions. The injected `Clock` and `IdSource` make IDs and timings deterministic. Replay is how a live failure becomes a regression test.
3. **Decisions can be tested in isolation.** Because `StopPolicy`, `ProgressSignal`, and `CommitRule` are pure and receive recorded values, a surprising decision is reproduced by feeding the recorded observations back into the component, with no model and no network.
4. **Values print readably.** Opaque or large fields (`ProviderState.payload_json`, artifact content, `config_json`) are excluded from `repr`, and `inputs_sha256` stands in for large inputs. A printed `Stopped` or `JournalEntry` fits on a screen and says what happened.
5. **Exceptions say where they happened.** Library exceptions carry the `TraceRef` of the span that raised them (and the call ID for tool errors), so a traceback names the step path, not only the Python frame.
6. **Redaction is sink policy.** By default, capture excludes message text, arguments, outputs, and provider state. Debugging and replay turn them on explicitly.
7. **Sinks never change behaviour.** A run with a `NullSink` and a run with a recording sink make the same decisions. A failing sink cannot fail the run unless the application chose a durable-audit policy.

## SOLID in the interfaces

| Principle | Rule | How the interface shape enforces it | Example | Warning sign |
| --- | --- | --- | --- | --- |
| **Single responsibility** | Keep provider conversion, control flow, context selection, and tools separate | One protocol per decision or capability. Measuring, deciding, certifying, recording, and storing are separate contracts, and the runtime (not each component) does tracing | `ProgressSignal` measures, `StopPolicy` decides, `Verifier` certifies, `Critic` reviews, `CommitRule` decides commits, `ExperimentJournal` records, `Workspace` stores. `Evaluator` (guides revision) is separate from `Verifier` (certifies); `Compactor` is separate from `ContextBuilder` | One agent class handles HTTP, prompts, persistence, and scheduling |
| **Open/closed** | Add behaviour through contracts and constructor injection | New behaviour is a new implementation injected in the composition root, or a combinator over existing ones. The runtime has no switch over implementations. Closed vocabularies are the deliberate exception and change only in a versioned revision | A new stop rule is a new `StopPolicy`; `any_of`, `all_of`, and `any_signal` combine them. A new provider is a new `ChatModel`. Neither needs a runtime edit | Every new integration edits a switch statement in the runtime |
| **Liskov substitution** | Specify observable behaviour and test it with shared suites | Every protocol has documented semantics and a shared contract suite. An implementation that type-checks but misbehaves fails its suite | Any `StopPolicy` is pure and deterministic; any `Verifier` returns `inconclusive` rather than guessing; any `ChatModel` reports unknown usage as `None`; any `Workspace` rollback is byte-identical and idempotent | Same signature, different correlation, error, or cancellation behaviour |
| **Interface segregation** | Split capabilities so no one implements what they cannot support | Consumers get the narrowest protocol they need. Reading and writing, streaming and non-streaming, and integrity checks and full workspace control are separate | `JournalReader` for critics and signals, `ExperimentJournal` only for the owning loop. `IntegritySource` for verifiers, the full `Workspace` only for the iteration. `StreamingChatModel` separate from `ChatModel`; `MemoryReader` separate from `MemoryWriter`. `ToolExecutor.restricted` gives each step only its tools. `Identified` is required only by protocols that make decisions | Implementations fill required methods with `NotImplementedError` |
| **Dependency inversion** | The runtime and implementations depend on portable interfaces | `llmgrid.loops` and every recipe depend only on interfaces protocols. Concrete adapters, tools, stores, and workspaces are built in the application's composition root and injected. `RunContext` carries only execution concerns, never services | `ExperimentIteration` receives a `Workspace`, a `Verifier`, a `CommitRule`, and a proposal `Step`. It never imports git, a model SDK, or a filesystem store | Loops import a concrete SDK or vector database |

Open/closed does not forbid fixing or versioning a contract. It means routine extensions should not require broad edits to unrelated code.

**`RunContext` is not a service locator.** It carries `events`, `clock`, and `ids` because every step needs them for tracing and determinism, and none of them gives access to application services. Anything else a step needs arrives through its constructor (D-07).

## How each package conforms

Each package implements some protocols and consumes others, always through `llmgrid.interfaces` and never through a sibling package.

| Package | Implements | Uses | Must never |
| --- | --- | --- | --- |
| `llmgrid-network` | `ChatModel` (every adapter and `ScriptedModel`, each `Identified` with its provider and model ID); a `RecordingModel` wrapper for capture; later `StreamingChatModel`; its own `ProviderOptions` types; the `ModelCapabilities` catalogue and `openai_compat` profiles | `RunContext` (`check` only), value types | Reserve or settle the ledger (the runtime does that); execute tools; make corrective model calls (D-16); read `StopPolicy`, `Verifier`, or journal types |
| `llmgrid-tools` | `ToolExecutor` (`ToolRegistry`, restricted views, `McpToolSource`); `Tool` (built-ins, `read_artifact`, `search_artifact`); `Workspace` (`GitWorkspace`) | `ToolInvocation`, `ToolError`, `ToolFailure`, `ArtifactStore` (to offload oversized output), `ProtectedPathError` | Decide scheduling, retries, or stopping; run a model; swallow cancellation |
| `llmgrid-context` | `ContextBuilder` (with `carry`, `compact`, `reset`); `Compactor` (mechanical and summarising); `ArtifactStore` (in-memory, filesystem); `TokenEstimator`; `MemoryReader` and `MemoryWriter` | `ChatModel` (for the summarising compactor), `RunContext`, `JournalView`, `Evidence` | Separate a tool call from its result or provider state; truncate silently; construct a provider client |
| `llmgrid-rag` | `Retriever` implementations and rerankers; citation validation as a `Verifier[GroundedAnswer]` with `deterministic` strength; the grounded-answer retrieval steps as `Step`s | `Evidence`, `RetrievalQuery`, `ChatModel` where a step generates, `RunContext` | Import `llmgrid.context` (evidence reaches context builders through interfaces types) |
| `llmgrid-loops` | `Step` compositions (`SequenceStep`, `Repeat`, `Branch`, `Map`); recipes as `Step[I, Outcome[O]]`; `StopPolicy` and `ProgressSignal` built-ins and combinators; `CommitRule` built-ins (`improves`, `no_regression`, `all_of`); `Verifier` adapters (`AcceptClaim`, an evaluator-backed judged verifier); `Critic` (`ModelCritic`); the in-memory `ExperimentJournal`; `AgentTool` (a `Step` adapted into a `Tool`) | Every capability protocol, by injection | Import a concrete adapter, tool, store, or workspace; call a model or tool except through `RunContext.invoke` with a reservation |
| The application | Domain verifiers, protected paths, goal statements, critic instructions, the choice of commit rule, context strategy, and stop policies | Everything above | — |

Two placements worth calling out:

- **`AgentTool` lives in loops, not tools.** It runs a sub-agent with a child context and turns a `Stopped` outcome into an agent-facing error (Q-16). It depends only on the `Step`, `Tool`, and `Outcome` protocols.
- **Citation validation is a `Verifier`**, so the grounded-answer recipe certifies completion through the same path (D-23) as every other loop. A recipe in loops can use it without importing rag, because the application injects it.

## Proving conformance

**Static conformance.** `tests/typing/conformance.py` assigns an instance of every public implementation to a variable typed as its protocol, for example `_: ChatModel = ScriptedModel(...)`, `_: ToolExecutor = ToolRegistry(...)`, `_: StopPolicy = MaxIterations(3)`. mypy in strict mode fails the build if an implementation drifts from its protocol.

**Behavioural conformance.** `tests/contracts/` holds one shared suite per protocol, parameterised over implementations. Every implementation must pass its suite, and third-party implementations can import the suites to prove themselves.

| Suite | What it checks |
| --- | --- |
| `chat_model` | Finish-reason consistency, call IDs, provider-state round trip, unknown usage as `None`, cancellation, no tool execution, no corrective calls |
| `tool_executor` | Result correlation, unknown tool, `restricted` hides and rejects, decoder rejection as `invalid_argument`, offloading above the output limit |
| `tool` | Declared effect, `ToolFailure` rendering, cancellation propagates, idempotency key used where declared |
| `stop_policy`, `progress_signal`, `commit_rule` | Determinism (same history, same answer); no I/O (run with the event loop closed and the filesystem blocked); reasons stated in numbers; `ComponentInfo` present |
| `tracing` | Every record type carries a `TraceRef`; child spans link to parents; `step_path` extends correctly through nested loops; every decision yields a `DecisionRecord` |
| `replay` | A captured run of Recipes 1 and 5 replays offline with identical decisions and IDs |
| `event_sink` | Versioned envelope; `CapturePolicy` respected; a failing sink does not fail the run; `NullSink` and recording-sink runs make the same decisions |
| `verifier` | Declared strength, `inconclusive` on missing evidence, budget charged when model-backed, reads the protected evaluator only |
| `critic` | Runs within its reserve, has no write tools, returns valid verdicts |
| `workspace` | Rollback is byte-identical and idempotent, protected-path rejection, integrity digest changes on tampering |
| `experiment_journal` | Append-only, ordered, `seen`, view digests, survives reload where persistent |
| `context_builder`, `compactor` | Fits the budget or fails explicitly, keeps pinned content, keeps tool pairs and provider state, budget charged |
| `artifact_store` | Stable references, bounded reads, run scoping |
| `retriever` | Provenance, ordering, score meaning |

**Architecture test.** The existing rule stays (sibling packages never import each other), plus: interfaces modules import only the standard library and other interfaces modules, and `tests/typing/conformance.py` is the only non-application place that imports every package.

**Versioning.** Any change to an interfaces signature, value field, or closed vocabulary is a breaking change for every package, released as a coordinated version range ([Packages](03-packages.md#versioning)).

## Changes from today's code

What exists on the `interfaces` branch today, and what changes to reach the specification above:

| Today | Target | Change |
| --- | --- | --- |
| `Budget`: flat, two counters, `consume` | `Ledger`, `Limits`, `Counters`, held as `RunContext.ledger` | Replace; `consume` becomes `reserve` plus `settle`; add `child` |
| `RunContext(run_id, budget, deadline)` | Adds `trace`, `events`, `clock`, `ids`, and `child(...)` with name, limits, deadline, and reserve; `invoke` gains kind and label | Extend |
| No trace identity | `TraceRef`, `ComponentInfo`, `Identified`, `DecisionRecord` | Add in Phase 1 |
| Default dataclass `repr` everywhere | Concise `repr`s; opaque and large fields excluded | Change |
| `ChatRequest(messages, tools)` | Adds the portable fields (D-14) and `provider_options` | Extend |
| `ChatResponse(message, finish)` | Adds `metadata: ResponseMetadata` | Extend |
| `ModelCapabilities(tool_calling: bool)` | The full capability set, including reliability flags | Replace the boolean with the richer set |
| `ToolSpec(name, description, input_schema_json)` | Adds `effect` (default `non_idempotent`) and `output_limit_chars` | Extend |
| `ToolResult(call_id, content, is_error)` | `error: ToolError \| None` and `artifact: ArtifactRef \| None`; `is_error` derived | Change |
| `Tool.invoke(value, *, context)` | `Tool.invoke(value, *, invocation)`, with the context at `invocation.context` | Change (breaking, but nothing is published yet) |
| `ToolExecutor(specs, execute)` | Adds `restricted(names)` | Extend |
| `ModelStoppedError`, `BudgetExceededError` | `Stopped` outcomes with a `StopReason` | Keep as internal signals until Phase 3, then remove from the public surface |
| No outcome types | The `outcomes` module | Add in Phase 3 |
| No loop-control, verification, critic, workspace, journal, context, retrieval, or event contracts | The modules above | Add phase by phase |
| Exceptions carry only a message | Library exceptions carry the raising span's `TraceRef`, and the call ID for tool errors | Extend |
