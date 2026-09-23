# llmgrid

Typed, composable agent building blocks with explicit budgets, cancellation, and outcomes. No hidden loops, no silent fallbacks.

This meta-package installs every llmgrid distribution. Install individual packages to take only what you need:

| Package | Import | Contents |
| --- | --- | --- |
| `llmgrid-interfaces` | `llmgrid.interfaces` | Contracts: messages, models, tools, steps, run context |
| `llmgrid-network` | `llmgrid.network` | Model adapters |
| `llmgrid-tools` | `llmgrid.tools` | Typed tool bindings and dispatch |
| `llmgrid-context` | `llmgrid.context` | Context assembly and memory (planned) |
| `llmgrid-rag` | `llmgrid.rag` | Retrieval-augmented generation (planned) |
| `llmgrid-loops` | `llmgrid.loops` | Composition runtime and agent recipes |

**Status:** alpha. See [the project](https://github.com/sanketn26/llmgrid).
