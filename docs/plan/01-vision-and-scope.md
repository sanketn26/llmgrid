# 1. Vision and scope

[← Back to the plan](../composable-agent-platform-plan.md)

**In short**

- llmgrid is a toolkit of typed, composable building blocks for agents. Its selling point is honest execution: every call is paid for, every stop has a reason, and "done" has to be proven.
- It is a library. It ships parts and guarantees; the application decides how to use them.
- It deliberately does not chase provider breadth, visual builders, or built-in prompts.

## Where llmgrid came from

The project started as `llm-port`: one API across many LLM providers, with reliable tool calling. Its value was breadth.

llmgrid changes the goal. It is a toolkit of typed, composable agent building blocks, and its value is **honest execution semantics**. Providers become pluggable dependencies instead of the product.

## The core bet

> Typed, composable agent building blocks with explicit budgets, cancellation, and outcomes — no hidden loops, no silent fallbacks.

Every scope decision should trace back to this sentence. If a feature can only be delivered with a hidden loop, an unaccounted model call, or a silent downgrade, redesign it or reject it.

## Mechanism, not policy

llmgrid is a library. It ships parts and enforces the guarantees each part promises:

- budgets are charged,
- calls are correlated,
- stops have reasons,
- completion carries its verification,
- rollback leaves no trace.

The **application** chooses everything else: the loop pattern, the thresholds, the prompts, the verifier, the commit rule, the context strategy, and how much to trust a model's own claim of success. Defaults exist so the examples run. Every default can be replaced where the application wires its objects together (its *composition root*), and none is required.

Common patterns such as ReAct, self-correction, Reflexion, the Ralph loop, and critic-supervised experiments are assembled from the same parts rather than shipped as separate agent types. See [Recipes and patterns](07-recipes-and-patterns.md#common-loop-patterns).

## What llmgrid should be better at

Provider gateways (for example LiteLLM), vendor agent SDKs, and agent frameworks (for example pydantic-ai and LangGraph) already exist. llmgrid does not try to out-feature them. It competes on properties that are hard to add later:

| Property | What it means in practice |
| --- | --- |
| Explicit accounting | Every model and tool call is reserved against one shared budget (the *ledger*), including repair attempts |
| Explicit outcomes | Running out of budget, truncation, refusal, and hitting a round limit are distinct results. A partial answer is never relabelled as a final one |
| Structural contracts | Third parties implement protocols. There are no base classes to inherit |
| Typed composition | Connecting incompatible steps fails static type checking |
| Weak and local model reliability | Tool calls that a model writes as plain text are recovered syntactically (carried over from the llm-port work) |
| Honest side effects | Tool results are matched to their calls. Later, a journal reports `outcome_unknown` instead of silently replaying an action |
| Enforced stopping | Users choose how a loop ends (iterations, lack of progress, a critic) but cannot switch off budgets and deadlines. Every stop has a named reason |
| Certified completion | A loop completes only when a verifier says so, and the result carries that verifier's evidence. The agent saying "done" is a claim, not a result |
| Loops that cannot game themselves | The evaluator is outside the agent's write access, and every iteration either commits a verified improvement or leaves no trace |

## Non-goals

llmgrid will not provide:

- **Many first-party provider adapters.** It ships a fixed, tested set (Anthropic, OpenAI, OpenAI-compatible, Gemini; Bedrock planned). Other providers come through the OpenAI-compatible adapter or community adapters that pass the contract suite. See [Packages](03-packages.md#provider-adapters).
- **A gateway adapter** (for example over LiteLLM). It would inherit the gateway's behaviour and limits, which undermines the accounting and outcome guarantees above.
- **A graph DSL, YAML workflows, or a visual builder.**
- **A hosted service, scheduler, or vector database.**
- **Prompt libraries or domain-specific agents** inside the runtime.
- **Judgement on tool design.** llmgrid enforces the tool hygiene it can check: unique names, per-step allow-lists, size limits, declared side effects, and a standard error shape. Whether two tools overlap in purpose is the application author's call. [Extending llmgrid](08-extending.md#adding-a-tool) gives guidance; the runtime does not guess.
- **Built-in critic prompts or goal definitions.** The runtime provides the critic and verifier hooks and enforces their verdicts. What counts as progress or success is an application input.
- **Hidden async.** A sync facade exists (D-11), but the core is async.

## Standards we use instead of reinventing

- **MCP (Model Context Protocol)** is the main source of third-party tools ([Recipe 4](07-recipes-and-patterns.md#recipe-4-mcp-backed-tool-agent)).
- **OpenTelemetry GenAI semantic conventions** name trace and event attributes ([Runtime](05-runtime.md#observability)).
- **The OpenAI Chat Completions wire format** reaches providers without a first-party adapter (for example vLLM, Ollama, Groq, OpenRouter). Per-endpoint capability profiles declare known gaps instead of hiding them ([Packages](03-packages.md#openai-compatible-endpoints-differ)).

## Objective

Build a collection of typed capabilities that developers can use directly or compose into agent workflows. Ship useful recipes without forcing applications to adopt a universal agent abstraction.

**The core promise:** an application can replace a conforming component, or introduce a new composition, without modifying existing runtime code.

"Supports any agentic use case" means there is an open path for extension. It does not mean every workflow can be expressed as configuration, that every provider supports every feature, or that every block can connect to every other block.

## Scope

### First: the foundation

- Text messages, normalized tool calls, and opaque provider continuation state (D-13).
- Async model generation.
- Typed tools with explicit decoding and encoding.
- Sequence composition and a bounded tool-calling recipe.
- In-process run limits, deadlines, and cooperative cancellation.
- Stop policies you can inject, with `MaxIterations` and `NoProgress` built in, and a distinct reason for every stop (D-22).
- Claim-then-verify completion in the tool-agent recipe (D-23).
- Declared tool side effects, runtime idempotency keys, agent-facing tool errors, per-step tool allow-lists, and tool-output size limits (D-26).
- Scripted models and tools for offline development.
- Two first-party adapters: Anthropic, and the OpenAI-compatible wire format (which also covers Ollama, vLLM, LM Studio, llama.cpp, and TGI). The OpenAI (Responses API) and Gemini adapters complete the set after Phase 2.

### Next: once the foundation is proven

- Typed branches, bounded repetition, and parallel execution.
- Retrieval, context construction, memory, and evaluation.
- Structured output as a capability and a step.
- MCP tool sources.
- Streaming as a separate capability.
- Human approval with suspension and resumption.
- Durable checkpoints and side-effect recovery.
- An Amazon Bedrock adapter over the Converse API.
- Compaction, offloading, and sub-agent isolation (D-25).
- Verifiers, the loop critic, the experiment journal, and transactional workspaces (D-23, D-24, D-27 to D-29), proven by [Recipe 5](07-recipes-and-patterns.md#recipe-5-critic-supervised-experiment-loop).

### Do not claim yet

Do not advertise durable execution, exactly-once side effects, multimodal support, or arbitrary JSON Schema validation on the strength of the starter code.
