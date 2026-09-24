# 9. Roadmap

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- Work is split into eight phases (0 to 7). Each phase ends with an exit gate: the phase is done when its behaviour is demonstrated, not when files exist.
- Phase 0 (baseline and rename) is done locally. The first target is Phases 0 to 3: contracts, the first provider adapters, and a working tool agent with loop control.
- The old `llm-port` code was never published, so migration makes breaking changes directly.

## Where things stand

| Phase | Goal | Status |
| --- | --- | --- |
| 0 | Baseline, rename, and decisions | Done locally; ADRs and CI on `main` pending |
| 1 | Minimal contracts | Not started (prototype contracts exist) |
| 2 | Provider boundary | Not started |
| 3 | Runtime and first vertical slice | Not started (prototype tool agent exists) |
| 4 | Prove composition across five recipes | Not started |
| 5 | Observability, streaming, and concurrency | Not started |
| 6 | Approval and durability | Not started |
| 7 | Release and ecosystem | Not started |

**First target:** complete Phases 0 to 3, using the [starter code](appendix-starter-code.md) as a reference. Then prove the remaining abstractions through the five recipes before adding more integrations.

## Phases

### Phase 0: Baseline, rename, and decisions

- [x] Preserve the working tree and record the inventory ([below](#what-the-old-checkout-contained)).
- [x] Run the existing lint, type, test, and build commands and record the baseline. (The old checkout had no tests to run.)
- [x] Rewrite the README for llmgrid.
- [x] Rename to `llmgrid`, adopt the [package layout](03-packages.md#repository-layout), and add the architecture test.
- [ ] Write ADRs for D-01 to D-30. Short ones are fine; the point is traceability.
- [ ] List the initially supported model, message, and tool semantics.

**Exit gate:** an accurate inventory, a README that matches the code, a green CI run on `main`, and the architecture test passing. (Green locally on 2026-09-23; CI waits for the merge.)

### Phase 1: Minimal contracts

- [ ] Create `llmgrid.interfaces` with `py.typed`.
- [ ] Define JSON values, messages (with provider state), tool calls and results, requests with portable and provider options, responses, usage, finish reasons, and errors.
- [ ] Add `ChatModel`, `StreamingChatModel` (shape only), `Tool`, `ToolExecutor`, `Step`, and the execution-context contracts.
- [ ] Implement the hierarchical ledger and `RunContext.child`.
- [ ] Define the loop-control values (`IterationObservation`, `StopDecision`, `StopReason`, `ProgressReading`, `VerificationResult`) and the `StopPolicy`, `ProgressSignal`, and `Verifier` protocols.
- [ ] Define `ToolEffect`, `ToolInvocation` (with the idempotency key), `ToolError`, and `ToolFailure`.
- [ ] Define `TraceRef`, `ComponentInfo`, `Identified`, `DecisionRecord`, `Clock`, and `IdSource`, and add trace, events, clock, and IDs to `RunContext` (D-30).
- [ ] Apply the Phase 1 rows of [Changes from today's code](04-interfaces.md#changes-from-todays-code), and add `tests/typing/conformance.py`.
- [ ] Document the rules for correlation, ownership, unknown usage, cancellation, and deadline ownership.
- [ ] Add a scripted model and one deterministic typed tool as test fixtures.
- [ ] Add static negative typing tests and shared behavioural tests.

**Exit gate:** a third-party implementation satisfies the protocols without inheriting framework classes, and `llmgrid.interfaces` imports with no dependencies installed.

### Phase 2: Provider boundary

- [ ] Consolidate the tool specifications and move serialization into the network package.
- [ ] Introduce model capability checks.
- [ ] Implement the Anthropic adapter and the OpenAI-compatible adapter.
- [ ] Verify and document each adapter's provider-state round-trip requirements.
- [ ] Implement syntactic tool-call recovery for the OpenAI-compatible adapter, tested against local-model fixtures.
- [ ] Define OpenAI-compatible capability profiles and run the contract suite against vLLM, Ollama, and one hosted endpoint.
- [ ] Test finish-reason mapping, usage accounting, and option handling at the boundary.
- [ ] Prove that no tool runs and no corrective model call is made inside an adapter.

**Exit gate:** scripted and real adapters pass the same model contract suite; offline tests cover the actual wire conversion using recorded fixtures; one opt-in live test per adapter completes a tool round trip.

### Phase 3: Runtime and first vertical slice

- [ ] Implement sequence composition and the model-step adapter.
- [ ] Implement shared invocation budgets, deadlines, and cancellation using the Phase 1 ledger.
- [ ] Implement typed tool binding and the registry.
- [ ] Implement the bounded, sequential tool-agent recipe, with instructions and conversation-continuation inputs.
- [ ] Return explicit outcomes; stop on non-completion.
- [ ] Implement `MaxIterations`, `NoProgress`, `MaxConsecutiveFailures`, `any_of`, and the `RepeatedCalls`, `RepeatedErrors`, and `FalseClaims` signals, and enforce the [end-of-iteration order](06-loop-control.md#what-happens-at-the-end-of-each-iteration).
- [ ] Implement claim-then-verify completion in the tool-agent recipe.
- [ ] Implement the event envelope, `NullSink`, an in-memory recording sink, `CapturePolicy`, decision records for every stop, and replay of Recipe 1 from captured events.
- [ ] Implement agent-facing error rendering (including decoder rejections), runtime idempotency keys, effect validation, restricted executor views, and tool-output size limits.
- [ ] Add the sync facade.
- [ ] Add an offline runnable example and a live example.

**Exit gate:**

- The whole tool-call, result, final-answer cycle works offline, including malformed calls and budget exhaustion, without importing a provider SDK.
- The same code runs against a real model with only the adapter changed.
- A scripted model that repeats a call is stopped with `no_progress`.
- A scripted false claim against a failing verifier never completes.
- Every stop reason in the tool agent is reachable in an offline test.

### Phase 4: Prove composition across five recipes

- [ ] Implement the retrieval, evidence, and context contracts, with in-memory implementations.
- [ ] Implement the structured-output step.
- [ ] Implement the grounded-answer recipe and citation validation.
- [ ] Implement the evaluator and the draft-and-review recipe.
- [ ] Implement `McpToolSource` and the MCP agent example.
- [ ] Implement compaction (mechanical, then summarising), the `ArtifactStore` (in-memory and filesystem), the read-back tools, and offloading.
- [ ] Implement sub-agents as steps and `AgentTool`, with transcript isolation.
- [ ] Implement `GitWorkspace` with protected paths and integrity hashing, the in-memory `ExperimentJournal`, the noise policy, and the remaining progress signals.
- [ ] Implement the critic hook with its reserve, cadence, triggers, guidance, and failure policy.
- [ ] Implement `CommitRule` with `improves`, `no_regression`, and `all_of`; the `carry`, `compact`, and `reset` context strategies; and the journal's `reflection` field.
- [ ] Implement Recipe 5 offline with a scripted proposer and a fake training step, plus one opt-in live example.
- [ ] Build the Ralph loop and Reflexion rows of the [patterns table](07-recipes-and-patterns.md#common-loop-patterns) as offline tests, from existing parts, with no new primitive.
- [ ] Add branch and bounded repeat only as those recipes require.
- [ ] Compose a recipe inside another recipe using the same context.
- [ ] Show that a model, retriever, or tool can be replaced without runtime changes.

**Exit gate:**

- All five use cases share primitives, with no domain-specific branches in the runtime.
- An MCP server written by someone else works through the unchanged tool-agent recipe.
- Recipe 5 demonstrates everything in its ["What this recipe proves"](07-recipes-and-patterns.md#recipe-5-critic-supervised-experiment-loop) list offline, including the critic's reserve surviving an exhausted inner loop, tamper detection, duplicate rejection, and a byte-identical rollback.

### Phase 5: Observability, streaming, and concurrency

- [ ] Export the Phase 3 events and trace identity to OpenTelemetry, aligned with D-20. (The envelope and IDs already exist from D-30.)
- [ ] Define streaming variants (text, tool, usage, terminal) and their ordering.
- [ ] Make stream closure and backpressure explicit.
- [ ] Add bounded parallel composition with structured cancellation.
- [ ] Make shared reservations safe under concurrency.
- [ ] Define tool independence and side-effect requirements before dispatching tools in parallel.

**Exit gate:** cancellation leaves no orphaned tasks or resources; parallel consumers cannot bypass their parent's limits; incomplete streamed arguments never reach a tool.

### Phase 6: Approval and durability

- [ ] Add the discriminated completed, suspended, failed, and stopped outcomes.
- [ ] Define versioned, serializable checkpoints and stable step IDs.
- [ ] Add atomic checkpoint revision checks.
- [ ] Persist pending effects and operation IDs before dispatch.
- [ ] Tie approvals to exact requests and revisions.
- [ ] Implement recovery and reconciliation for unknown outcomes.
- [ ] Test crashes at every effect and checkpoint boundary.
- [ ] Persist the experiment journal and resume Recipe 5 from the last commit, rolling back an interrupted iteration.

**Exit gate:** restarting preserves intent and completed work; ambiguous external effects are reported, not silently replayed.

### Phase 7: Release and ecosystem

- [ ] Confirm all four first-party adapters (Anthropic, OpenAI, OpenAI-compatible, Gemini) pass the contract suite.
- [ ] Build the distributions and inspect their dependency metadata and extras.
- [ ] Test installing from the wheel in a clean environment, with and without each extra.
- [ ] Publish a tested compatibility matrix.
- [ ] Include five working examples and a guide for third-party extensions.
- [ ] Publish the supported Python versions.
- [ ] Document the guarantees and known limits before calling the API stable.

**Exit gate:** users can install only the extras they need and complete each example from the published artifacts.

## Production hardening checklist

Before treating the starter as a public foundation:

- [x] Run a strict type checker and add negative typing tests. (Done for the prototype; repeat for the real packages.)
- [ ] Validate public configuration and serialized inputs at boundaries. `Literal` annotations do not validate at runtime.
- [ ] Add model usage and normalized provider errors.
- [ ] Replace the prototype's stop exceptions with explicit outcomes carrying partial state where appropriate.
- [ ] Replace the flat `Budget` with the hierarchical ledger.
- [ ] Add lifecycle management for owned clients, and stream clean-up semantics.
- [ ] Add a supported schema validator or codec, and prove the declaration and decoder agree.
- [ ] Define the instruction input and conversation continuation explicitly.
- [ ] Add request options (portable and provider-keyed) with capability validation.
- [ ] Add authorization hooks before exposing tools that need them.
- [ ] Add tool-output size limits and a deliberate truncation policy: offloading to an `ArtifactStore` with read-back tools (D-25).
- [ ] Replace every implicit loop bound with a `StopPolicy`, and make every stop reason reachable in tests (D-22).
- [ ] Route every completion through a verifier, with `AcceptClaim()` as the explicit opt-in for self-reported completion (D-23).
- [ ] Render every anticipated tool failure as an agent-facing `ToolError` (D-26).
- [ ] Protect evaluator paths and check their integrity before measuring, in any iterative loop (D-27).
- [ ] Add context-window accounting and evidence provenance.
- [ ] Make reservations concurrency-safe before parallel or distributed execution.
- [ ] Add event ordering, trace propagation, and a redaction policy.
- [ ] Add persistence only with versioned state and documented recovery semantics.
- [ ] Verify package isolation, imports without extras, and imports from installed wheels.

## Migrating from llm-port

### What the old checkout contained

Inventory of branch `optional_providers` as of 2026-09-23, measured rather than assumed:

| Item | State |
| --- | --- |
| Source | About 1,100 lines: `types.py`, `config.py`, `errors.py`, `tools.py`, `spec/tools.py`, `spec/models.py` (untracked) |
| Client and provider adapters | Missing. `LLMClient`, which the README documented, did not exist |
| Tests | `tests/unit` and `tests/integration` existed and were empty |
| README | Claimed a "settled" public surface, 18 providers, streaming, and tool-call repair; none were implemented |
| PyPI | `llm-port` was never published (PyPI returned 404), so there are no external users to migrate |
| Duplicated `ToolSpec` | One in `tools.py` (with `from_callable` and `to_openai`/`to_anthropic`/`to_gemini`) and one in `spec/tools.py` (with `ArgSpec`, `to_wire`, instruction rendering) |
| `ModelSpec` | Useful capability fields (`ToolSupport` none/prompted/native/strict, `structured_output`, `reasoning`, context limits), but coupled to `config.Provider` |
| `LLMConfig` | Contained `tool_repair_attempts`, a hidden corrective loop that conflicts with D-16 |
| `errors.py` | A reasonable taxonomy, but its `TimeoutError` shadowed the builtin (conflicts with D-19) |

### Old types versus the new contracts

| Old | New | Action |
| --- | --- | --- |
| `ToolCall.arguments: dict` | `arguments_json: str` (D-15) | Change; keep `origin: native/recovered` |
| `Message.content` | `Message.text` | Rename |
| `finish_reason`, `usage`, `raw` on the message | Metadata on `ChatResponse`; no raw payload | Move; drop `raw` |
| No continuation field | `Message.provider_state` (D-13) | Add |
| `Message.name` | Not in the portable contract | Drop, unless a provider needs it; then carry it in provider state |
| `Usage` fields default to `0` | `int \| None` (D-17) | Change; keep `cached_input_tokens` |
| `FinishReason` includes `content_filter`, `error` | The D-18 vocabulary; errors are exceptions | Drop `error`; add `refusal` |
| `StreamEvent` with a `kind` string and optional fields | A discriminated event union | Redesign in Phase 5 |
| `Message.coerce` from dicts | Not in interfaces | Move to an optional convenience helper, or drop |
| `errors.TimeoutError` | `ProviderTimeoutError` (D-19) | Rename |
| `ModelSpec` / `ModelRegistry` / `ToolSupport` | `ModelCapabilities` in interfaces; the catalogue in `llmgrid.network.capabilities` | Split; remove the `config` import from the capability type |
| `LLMConfig` | Adapter constructor arguments | Split per adapter; drop `tool_repair_attempts`; keep `RetryPolicy` |
| Two `ToolSpec`s | One declaration type in interfaces; serializers in network | Consolidate |
| `ToolSpec.from_callable` | A candidate helper in `llmgrid.tools` | Keep only if it produces a binding with a matching decoder |
| `Provider` enum with 18 base URLs | The OpenAI-compatible adapter takes a `base_url`; presets are optional | Shrink to presets for the first-party adapters |

### Migration steps

Nothing was published, so there is no compatibility layer to build. Breaking changes are made directly.

1. [x] Preserve the working tree. The old code, including uncommitted edits, moved to `legacy/llm_port/`.
2. [x] Rewrite the README to describe llmgrid honestly.
3. [x] Adopt the per-package layout, the architecture test, and per-package Make targets.
4. [x] Move the starter prototype into `interfaces`, `network` (`ScriptedModel`), `tools`, and `loops`, with tests. The tables above are not yet applied beyond the prototype.
5. [ ] Consolidate the two `ToolSpec`s into the interfaces declaration. Move provider rendering into network serializers. Keep `ArgSpec` rendering only for prompted-tool instructions.
6. [ ] Split `ModelSpec` into interfaces `ModelCapabilities` and a provider-side catalogue.
7. [ ] Build the shared model contract suite (the scripted model already exists).
8. [ ] Build the first real adapter against that suite (Phase 2).
9. [ ] Add the runtime and the first recipe (Phase 3).

Do not combine the repository move, the public type redesign, and adapter work in one commit. Each stage should be reviewable and testable on its own.

### Repository and naming follow-ups

- [x] Rename the GitHub repository to `llmgrid` (done 2026-09-23: `github.com/sanketn26/llmgrid`; the old `llm-port` URL redirects). The badge and `project.urls` now point to it; they previously named the wrong account (`sanketnaik`).
- [ ] Publish `0.1.0a1` of all seven distributions with `make publish-<pkg>` after merging to `main` (interfaces first, `llmgrid` last). `llmgrid-context` and `llmgrid-rag` have no functionality yet, so under PEP 541 they are the most exposed to a name claim; give them real code early.
- [ ] Rename the local checkout directory from `llm-port` (optional; nothing depends on it).
- [ ] Check that no other package already installs a top-level `llmgrid` module.
