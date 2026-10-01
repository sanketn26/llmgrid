# Phase 0: start from zero

[All phases](../composable-agent-platform-plan.md)

Start here with no assumed project setup or familiarity with the code. The repository
already contains a small offline prototype. Reuse that code as the baseline, then apply
the later phases. Their implementations are still in the Markdown, not in the packages.

## 1. Establish the project directory

Use this checkout as your project root. It contains the files listed below; you do not
need to recreate them before following the guide. All commands run from that root.

If you want a separate project starting with an empty directory, copy the baseline from
this checkout first. The following script creates a new destination and copies the
existing code, package metadata, checks, and this guide. Change both paths before running.
It refuses an existing destination.

```python
from pathlib import Path
import shutil

source = Path("/absolute/path/to/llmgrid")
destination = Path("/absolute/path/to/new-llmgrid")

if not (source / "packages/interfaces/pyproject.toml").is_file():
    raise ValueError("Source must be the llmgrid checkout")
destination.mkdir(parents=True, exist_ok=False)
for name in ("packages", "examples", "tests", "docs", "tools", ".github"):
    shutil.copytree(
        source / name,
        destination / name,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.egg-info",
            "dist",
            "build",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
        ),
    )
for name in (
    "Makefile",
    "pyproject.toml",
    "requirements-dev.txt",
    "README.md",
    "LICENSE",
    ".gitignore",
):
    shutil.copy2(source / name, destination / name)
print(f"Baseline copied to {destination}")
```

`legacy/` is optional reference material; nothing in the baseline imports it.
The guide checker uses the same baseline source, applies phase code in a temporary
checkout, and runs the examples. It does not require the later code to exist beforehand.

## 2. Understand the layout

```text
llmgrid/
  pyproject.toml                         shared lint/type/test configuration
  requirements-dev.txt                   development dependencies
  Makefile                               setup, checks, demos, builds
  packages/
    interfaces/src/llmgrid/interfaces/    shared values and protocols
    network/src/llmgrid/network/          scripted model; later provider adapters
    tools/src/llmgrid/tools/              typed bindings and registry
    loops/src/llmgrid/loops/              composition and agent recipes
    context/src/llmgrid/context/          currently an empty package
    rag/src/llmgrid/rag/                  currently an empty package
    llmgrid/                             meta-package; no Python implementation
  examples/tool_agent/demo.py             current offline example
  tests/                                 integration, architecture, typing checks
  tools/check_implementation_guide.py     runs the proposed phase examples
  docs/plan/                              implementation phases
```

Each code package also has a `pyproject.toml`, README, LICENSE, tests, and a `py.typed`
marker. `llmgrid` is a namespace: there is no `src/llmgrid/__init__.py` at its shared root.
Keep that structure when adding files.

## 3. Pre-existing Python code to reuse

These are real source files already in the checkout, not proposed APIs.

| Existing file | What it implements now | Later action |
| --- | --- | --- |
| [interfaces/errors.py](../../packages/interfaces/src/llmgrid/interfaces/errors.py) | `ContractError`, `BudgetExceededError`, `InvalidArgumentsError`, `ModelStoppedError` | Keep; add provider errors separately in Phase 1 |
| [interfaces/values.py](../../packages/interfaces/src/llmgrid/interfaces/values.py) | `ToolSpec`, `ToolCall`, `ToolResult`, `ProviderState`, validated `Message` | Keep as the shared message/tool values |
| [interfaces/tools.py](../../packages/interfaces/src/llmgrid/interfaces/tools.py) | `Tool[I, O]`, `ToolExecutor` protocols | Keep; concrete implementations follow these shapes |
| [interfaces/execution.py](../../packages/interfaces/src/llmgrid/interfaces/execution.py) | Flat `Budget`, deadline-aware `RunContext`, `Step[I, O]` | Replace with nested accounting in Phase 1 |
| [interfaces/model.py](../../packages/interfaces/src/llmgrid/interfaces/model.py) | Requests/responses, finish reasons, capabilities, `ChatModel` | Replace with the validated extensions in Phase 1 |
| [interfaces/__init__.py](../../packages/interfaces/src/llmgrid/interfaces/__init__.py) | Public exports used by every package | Keep exports working; add new public types deliberately |
| [tools/binding.py](../../packages/tools/src/llmgrid/tools/binding.py) | `BoundTool`, `ToolBinding[I, O]`, argument decoding and result encoding | Reuse; extend expected failure handling in Phase 4 |
| [tools/registry.py](../../packages/tools/src/llmgrid/tools/registry.py) | Tool lookup and unique-name validation | Replace with restricted views and output limits in Phase 3 |
| [tools/__init__.py](../../packages/tools/src/llmgrid/tools/__init__.py) | Binding/registry exports | Keep |
| [network/scripted.py](../../packages/network/src/llmgrid/network/scripted.py) | `ScriptedModel`, recorded requests, prepared responses | Keep as the offline model throughout the guide |
| [network/__init__.py](../../packages/network/src/llmgrid/network/__init__.py) | Scripted-model export | Keep; real adapters are new files in Phase 2 |
| [loops/composition.py](../../packages/loops/src/llmgrid/loops/composition.py) | `SequenceStep[A, B, C]` | Keep; do not rewrite step chaining |
| [loops/model_step.py](../../packages/loops/src/llmgrid/loops/model_step.py) | Capability check, model charge, timed generation | Replace in Phase 3 when dispatch owns the charge |
| [loops/tool_agent.py](../../packages/loops/src/llmgrid/loops/tool_agent.py) | Bounded tool cycle returning `AgentResult` | Replace with outcomes and verification in Phase 3 |
| [loops/__init__.py](../../packages/loops/src/llmgrid/loops/__init__.py) | Composition/agent exports | Keep exports coherent during the Phase 3 migration |
| [context/__init__.py](../../packages/context/src/llmgrid/context/__init__.py) / [rag/__init__.py](../../packages/rag/src/llmgrid/rag/__init__.py) | Package placeholders | Add implementations in Phase 4 |
| [examples/tool_agent/demo.py](../../examples/tool_agent/demo.py) | `AddInput`, `AddTool`, decoder, registry, scripted model, composition | Run now; migrate its outcome handling in Phase 3 |

No real provider adapter, verifier, retrieval implementation, checkpoint store, or
stream assembler exists in the package source yet. The later phases supply those files.

## 4. Create the development environment

Install Python 3.12 or later and use this project's root directory:

```bash
python3 --version
make setup
make check
make demo
```

`make setup` creates `.venv`, installs development tools, and installs all six code
packages in editable mode. `make check` runs Ruff, strict mypy, and offline tests.
`make demo` runs the pre-existing scripted example; no provider credentials are needed.

Expected demo output:

```text
The answer is 5.
2 1
```

If working without `make`, the equivalent setup is:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt \
  -e packages/interfaces -e packages/network -e packages/tools \
  -e packages/loops -e packages/context -e packages/rag
.venv/bin/python examples/tool_agent/demo.py
```

## 5. Trace one existing run

The existing demo follows this sequence:

```text
RunContext + Budget
  → ToolAgent
  → ModelStep → ScriptedModel asks for add(2, 3)
  → ToolRegistry → ToolBinding → AddTool returns 5
  → ModelStep → ScriptedModel returns a final answer
  → AgentResult → ExtractText
```

Open the linked files in that order. The baseline charges calls in `ModelStep` and the
agent, while `RunContext.invoke` owns the timeout. Phase 3 moves the charge into
`invoke`; remove the old charge then so a call is not counted twice.

## 6. Keep the existing checks

| Existing checks | What they cover | What changes later |
| --- | --- | --- |
| [interfaces tests](../../packages/interfaces/tests/test_interfaces_contracts.py) | Value contracts, call budgets, deadlines, cancellation | Extend for nested budgets and request/usage validation in Phase 1 |
| [network tests](../../packages/network/tests/test_network_scripted.py) | Scripted responses and recorded requests | Keep; add provider fixtures in Phase 2 |
| [tools tests](../../packages/tools/tests/test_tools_registry.py) | Typed decoding, routing, unknown tools | Extend for restricted views, output limits, expected failures |
| [loops tests](../../packages/loops/tests/test_loops_tool_agent.py) | Model/step composition and tool-loop behaviour | Migrate result assertions to outcomes in Phase 3 |
| [integration test](../../tests/integration/test_tool_agent_flow.py) | Full offline tool cycle | Migrate completion/stopping assertions in Phase 3 |
| [architecture test](../../tests/architecture/test_dependencies.py) | Package dependencies and shared namespace layout | Allow optional dependencies only in their owning integration modules when adding extras |
| [negative typing tests](../../tests/typing/typing_negative.py) | Reject invalid step composition | Update the agent output type to `Outcome[AgentResult]` in Phase 3 |

The architecture test currently rejects every third-party import. Phase 2 adds optional
HTTP/SDK dependencies, so update that check alongside those files; do not remove the
sibling-package dependency rule.

## Before moving on

- [ ] You can locate the source and package metadata from the tree above.
- [ ] The environment is installed and the existing checks pass.
- [ ] The current demo produces the expected answer and call counts.
- [ ] You know which files Phase 1 replaces and which it keeps.

Next: [Phase 1](phase-1-contracts.md).
