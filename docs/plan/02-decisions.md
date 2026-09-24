# 2. Decisions

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- Every architectural decision has a stable ID (D-01 to D-30) so code reviews and ADRs can cite it. IDs never change, even though the decisions are grouped by theme below.
- Deferred decisions list what we are deliberately not doing yet, and what would make us reconsider.
- Open questions (Q-01 to Q-17) each have a current leaning and the phase by which they must be settled.

Each decision gets a short ADR in `docs/decisions/` (a Phase 0 task). If a change contradicts a decision, update this log and the ADR in the same change.

## Decision log

Each table has the same columns: the decision, why we made it, and how we check that the code still follows it.

### Project and packaging

| ID | Decision | Why | How it is verified |
| --- | --- | --- | --- |
| D-01 | The project is named `llmgrid`: distribution `llmgrid`, import `llmgrid` | Available on PyPI (checked 2026-09-23); avoids the crowded `llm-*` plugin namespace; the name no longer implies a provider port | `pip download llmgrid` returns nothing before the first publish |
| D-02 | Separate distributions (`llmgrid-interfaces`, `-network`, `-tools`, `-context`, `-rag`, `-loops`) share the `llmgrid` namespace package, plus an `llmgrid` meta-package | Each package can be developed, versioned, and published on its own, and consumers install only what they need. The cost is coordinated version ranges and a release order | `tests/architecture` enforces the dependency graph; `make smoke` installs every wheel into a clean environment |
| D-03 | `llmgrid.interfaces` is the one contracts package, and it uses the standard library only | Contracts must install and import without any SDK | The architecture test rejects any non-stdlib import in interfaces |
| D-10 | Mandatory dependencies are minimal; SDKs and databases are optional extras | Avoid pulling SDKs into every install | Inspect wheel dependency metadata |

### Programming model

| ID | Decision | Why | How it is verified |
| --- | --- | --- | --- |
| D-04 | Capability protocols (what an operation means) plus one generic execution protocol (`Step`) | Keep each capability's meaning while still allowing composition | A capability can be used directly without the loop runtime |
| D-05 | APIs are async-first | Model and tool operations are mostly I/O | Cancellation and timeout tests |
| D-06 | Inputs and outputs are typed | Make incompatible connections visible | Static negative tests reject invalid sequences |
| D-07 | Dependencies are passed explicitly through constructors | Make dependencies discoverable | No global service registry in interfaces or loops |
| D-08 | The runtime owns execution semantics | Make nested compositions predictable | Shared budget and cancellation tests |
| D-09 | Recipes are ordinary compositions or steps | Applications can replace or embed them | Run a recipe inside another sequence |
| D-11 | Sync code uses one explicit facade, `llmgrid.sync.run(step, value, context)`, which refuses to run inside an active event loop | Many users are sync, and duplicating every protocol in sync form would double the contract surface | A test shows the facade raises inside a running loop |
| D-12 | Capabilities are validated explicitly before use | Avoid silent feature degradation | Unsupported requests fail before reaching the provider |

### Messages, requests, and providers

| ID | Decision | Why | How it is verified |
| --- | --- | --- | --- |
| D-13 | Assistant messages carry opaque, provider-owned continuation state (`ProviderState`) | Some providers require reasoning or thinking blocks to be sent back unchanged during tool loops; a text-only message cannot hold them | Adapter contract test: state emitted on turn N appears unchanged in request N+1 |
| D-14 | Portable request options are typed fields; provider-specific options travel in typed objects keyed by adapter | Without an escape hatch the portable request becomes the lowest common denominator and users bypass it | Adapter tests for accepted, foreign, and malformed options |
| D-15 | Tool-call arguments are kept as raw JSON text (`arguments_json`); decoding belongs to the tool binding | Arguments that cannot be decoded must still reach the loop so the model can be told what was wrong | A malformed-argument test returns a correlated error result |
| D-16 | Provider adapters do syntactic recovery only; semantic correction always goes through the loop | Prevents a hidden second feedback loop and model calls nobody paid for | Adapter tests prove one `generate` call equals at most one provider attempt per transport retry policy, with no corrective model calls |
| D-17 | Usage fields are `int \| None`, where `None` means unknown | Zero and unknown are different facts | Contract test on adapters that omit usage |
| D-18 | Finish reasons are normalized to `stop`, `tool_calls`, `length`, `content_filter`, `refusal`. Errors are exceptions, not a finish reason | One vocabulary across adapters; an error is not a way of finishing | A mapping table and tests per provider |
| D-19 | No library exception shadows a builtin name | The old `errors.TimeoutError` shadowed the builtin raised by `asyncio.timeout` | Ruff `A` rules stay enabled without per-line suppressions |
| D-21 | The first-party adapters are Anthropic, OpenAI (Responses API), OpenAI-compatible (Chat Completions), and Gemini. Bedrock is the one planned addition. There is no gateway adapter | Four wire formats cover most hosted and local models, and each first-party adapter must meet the full contract, which a gateway cannot | Every first-party adapter passes the shared model contract suite. Adding a first-party adapter requires revising this decision |

### Observability and debugging

| ID | Decision | Why | How it is verified |
| --- | --- | --- | --- |
| D-20 | Event and trace attributes follow the OpenTelemetry GenAI semantic conventions where a convention exists | Avoid inventing a schema every consumer must map | Review the event schema against the convention version pinned in the ADR |
| D-30 | Traceability and debuggability are part of the interfaces: every record carries a `TraceRef`, every decision becomes a `DecisionRecord` naming who decided and why, events share one versioned envelope, and the clock and ID source are injectable so runs replay deterministically | A loop that stops, commits, or completes must be explainable afterwards and reproducible offline. Adding identity to records later would break every consumer | Tracing, replay, and event-sink contract suites ([Interfaces](04-interfaces.md#proving-conformance)) |

### Loop control

These decisions are explained in depth in [Loop control](06-loop-control.md).

| ID | Decision | Why | How it is verified |
| --- | --- | --- | --- |
| D-22 | Stopping is an injected, deterministic `StopPolicy`, checked by the runtime at every iteration boundary. Budgets and deadlines stay in the ledger, and no policy can disable them. Every stop reason is a distinct `Stopped` variant | Users need to customise when a loop ends without being able to remove the hard limits, and "why did it stop?" must be answerable from the outcome alone | Each built-in policy yields its own reason; a policy that says `Continue` cannot override an exhausted ledger; a `Repeat` without a bound fails when constructed |
| D-23 | Only a `Verifier` certifies completion. A model's claim that it is done triggers verification. `Completed` carries the verifier's identity, verdict, strength, and evidence | Self-reported success is the most common way agent loops falsely complete | A scripted model that claims success against a failing verifier never produces `Completed` |
| D-24 | The loop critic is structural: its `Stop` verdict ends the loop unconditionally, it runs on budget and time set aside before the inner loop starts, and its `Guide` feedback enters history as a visible, recorded message | An advisory critic can be ignored, and a critic sharing the inner loop's budget runs out exactly when it is needed | An inner loop that exhausts its own budget still gets a critic review; `Stop` ends the loop; guidance appears in history and events |
| D-25 | Context hygiene is explicit: compaction is a budgeted step with a declared trigger; tool outputs over a size limit are offloaded to an `ArtifactStore` and replaced by handles; sub-agents return typed results, never transcripts; each iteration declares a context strategy (`carry`, `compact`, or `reset`) | Hidden compaction is a hidden model call, and transcripts leaking into the parent defeat the point of a sub-agent | Compaction is charged to the ledger; oversized output is offloaded; a parent's history contains only the sub-agent's call and result |
| D-26 | Tools declare one of three side-effect kinds (`read_only`, `idempotent`, `non_idempotent`); the runtime gives every tool call a stable idempotency key; expected tool failures return a structured error written for the agent | Safe repetition and self-correction must be part of the contract, not conventions each tool reinvents | The key is stable across retries of one call; `non_idempotent` tools are never retried automatically; decoder rejections use the agent-facing shape |
| D-27 | The evaluator is outside the agent's write access. Verifier code, evaluation data, and metric definitions are protected by the workspace and checked by hash before every verification, not protected by instructions | A loop that can edit its evaluator eventually optimises the evaluator instead of the task | A write to a protected path is rejected with an agent-facing error; a tampered protected file aborts and rolls back the iteration |
| D-28 | Iterative loops keep an `ExperimentJournal`: an append-only, structured record of attempts, separate from conversation history and never compacted | After compaction a loop forgets what failed and tries it again, and the critic and no-progress checks need facts, not prose | The journal survives compaction and resume; duplicate proposals are detected from it; progress signals read from it |
| D-29 | Iterations are transactional: an iteration that changes a `Workspace` runs between a snapshot and a commit or rollback, and code decides which using an application-chosen `CommitRule`. The model never decides | Every iteration either lands a change its commit rule accepts or leaves no trace, so the workspace is always at the last accepted state | A failing or non-improving iteration leaves the workspace byte-identical to its snapshot; a crash mid-iteration resumes at the last commit |

## Deferred decisions

Things we are deliberately not doing yet, and the evidence that would make us reconsider.

| Not now | Reconsider when |
| --- | --- |
| Merging the packages back into one distribution | Coordinated releases prove more costly than the independence is worth |
| A standalone composition/runtime distribution | Non-LLM consumers actually use it on its own |
| Dynamic plugin discovery | Explicit registration becomes demonstrably burdensome |
| YAML/JSON workflow definitions | External authoring and versioned serialization are required |
| Distributed scheduling | A measured workload needs multiple workers |
| Automatic model routing and fallback | Applications have established routing, fallback, and budget semantics |
| A broad multimodal message hierarchy | At least two adapters and one real use case validate the design |
| Corrective retries inside adapters | Profiling on weak models shows loop-level correction is materially worse (D-16) |
| The Bedrock adapter | The four D-21 adapters pass the contract suite and the async client question (Q-09) is settled |
| A universal memory abstraction | Never: keep separate storage and query responsibilities |
| Parallel experiments (several proposals per iteration, population or beam search) | The sequential experiment loop is proven and the workspace supports isolated branches or worktrees |
| Model-based progress detection inside `StopPolicy` | Deterministic signals demonstrably miss stalls that matter. Until then, model judgement belongs to the critic |
| Semantic duplicate detection for proposals | Digest-based duplicate rejection plus the critic demonstrably miss repeated ideas |

## Open questions

Settle each in an ADR before the phase that needs it. Sorted by when the answer is needed.

| ID | Question | Needed by | Current leaning |
| --- | --- | --- | --- |
| Q-01 | A child budget asks for more than the parent has left: clamp it or reject it? | Phase 1 | Reject |
| Q-02 | Should `ChatResponse` carry usage and attempt count directly, or through a separate `ResponseMetadata`? | Phase 1 | A separate metadata object on the response |
| Q-05 | Is `httpx` a hard dependency of `llmgrid-network`, or only of its extras? | Phase 2 | Extras only |
| Q-03 | Which schema/validation library backs decoders and MCP tools (for example `jsonschema`, `msgspec`, or pydantic), and which JSON Schema dialect is supported? | Phase 3 | Undecided; must be an extra, not an interfaces dependency |
| Q-04 | Is `ToolResult.content` text only, or a typed union (text, JSON, file reference)? | Phase 3 | Text only until MCP forces the question in Phase 4 |
| Q-07 | Does the tool-agent recipe expose history trimming, or require an injected `ContextBuilder`? | Phase 3 | An injected `ContextBuilder` with a default that does not trim |
| Q-13 | Should the idempotency key be per call, or derived from the arguments, by default? | Phase 3 | The runtime key is per call; tools opt into argument-derived keys and document them |
| Q-06 | How does an application express provider fallback without automatic routing? | Phase 4 | A plain composition step that catches specific `ProviderError`s and charges both attempts |
| Q-10 | What is the default commit rule when measurements are noisy? | Phase 4 | Commit when `mean(candidate) - mean(best) > max(min_delta, 2 × standard error)`; re-measure when within twice the noise floor; at most three samples |
| Q-11 | If the critic fails, does the loop fail open (continue) or closed (stop)? | Phase 4 | Continue after one failure using the deterministic policies; stop after two in a row; fail open only when explicitly configured |
| Q-12 | What are the default compaction trigger and target, and which token estimator? | Phase 4 | Trigger at 70% of the declared input window, compact to 40%; an injected estimator with documented accuracy; the provider's token counting where available |
| Q-14 | How are protected paths enforced against tools that run arbitrary commands? | Phase 4 | Hash-check protected files before every verification and run verifiers from a pristine copy; sandboxing is the application's choice |
| Q-15 | Does the experiment journal live in the checkpoint store or in its own store? | Phase 4 | Its own append-only store, referenced from checkpoints |
| Q-16 | When a sub-agent stops without completing, does its caller get a tool error or the `Stopped` outcome? | Phase 4 | An agent-facing error result when it was called as a tool; the outcome itself when it was composed as a step |
| Q-17 | What are the default critic reserve and review cadence? | Phase 4 | 10% of model calls and tokens (enough for at least two reviews); every 5 iterations plus triggers |
| Q-08 | Which OpenTelemetry GenAI convention version do we pin? | Phase 5 | The latest stable version when Phase 5 starts |
| Q-09 | Which async client backs the Bedrock adapter, given that `boto3` is synchronous? | Bedrock adapter | Undecided: `aiobotocore`, `boto3` in a worker thread, or signed `httpx` requests |
