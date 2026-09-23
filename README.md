# llmgrid

[![CI](https://github.com/sanketn26/llmgrid/actions/workflows/ci.yml/badge.svg)](https://github.com/sanketn26/llmgrid/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Typed, composable agent building blocks with explicit budgets, cancellation, and outcomes. No hidden loops, no silent fallbacks.**

> **Status:** early alpha (`0.1.0a1`). The contracts and a bounded tool-calling agent work offline against a scripted model. There are no real provider adapters yet. APIs will change between `0.x` releases. The design and roadmap are in [docs/composable-agent-platform-plan.md](docs/composable-agent-platform-plan.md).

## Packages

Each package is published on its own and imported from the shared `llmgrid` namespace. Install only what you need, or `pip install llmgrid` for all of them.

| Distribution | Import | Contents | State |
| --- | --- | --- | --- |
| `llmgrid-interfaces` | `llmgrid.interfaces` | Messages, tool calls, `ChatModel`, `Tool`, `Step`, `RunContext`, errors. Standard library only | Prototype |
| `llmgrid-network` | `llmgrid.network` | Model adapters. Today: `ScriptedModel` for offline use | Prototype |
| `llmgrid-tools` | `llmgrid.tools` | Typed tool bindings and a registry | Prototype |
| `llmgrid-loops` | `llmgrid.loops` | `SequenceStep`, `ModelStep`, bounded `ToolAgent` recipe | Prototype |
| `llmgrid-context` | `llmgrid.context` | Context assembly and memory | Planned |
| `llmgrid-rag` | `llmgrid.rag` | Retrieval-augmented generation | Planned |
| `llmgrid` | — | Meta-package that installs all of the above | — |

Every package except `llmgrid-interfaces` depends only on `llmgrid-interfaces`. An architecture test enforces this.

## Example

[examples/tool_agent/demo.py](examples/tool_agent/demo.py) runs a scripted model that calls an `add` tool:

```python
agent = ToolAgent(make_model(), make_registry())
workflow = SequenceStep[str, AgentResult, str](agent, ExtractText())
context = RunContext("demo-1", Budget(max_model_calls=2, max_tool_calls=1))
print(await workflow.run("What is 2 + 3?", context=context))  # The answer is 5.
```

## Development

Requires Python 3.12 or later. One virtualenv holds every package in editable mode.

```bash
make setup          # create .venv and install all packages
make check          # lint, strict type check, and all offline tests
make demo           # run the example
make packages       # list packages, distribution names, and versions
```

Work on one package with `make <target>-<pkg>`, where `<pkg>` is `interfaces`, `network`, `tools`, `context`, `rag`, `loops`, or `llmgrid`:

```bash
make test-tools         # that package's tests
make lint-tools         # ruff
make typecheck-tools    # mypy --strict
make check-tools        # all three
make build-tools        # sdist and wheel in packages/tools/dist, checked with twine
```

`make build` builds every package, and `make smoke` installs the built wheels into a clean virtualenv and imports them.

### Publishing

```bash
make publish-interfaces                      # to PyPI
make publish-interfaces REPOSITORY=testpypi  # to TestPyPI
```

`publish-<pkg>` refuses to run unless you are on `main` with a clean working tree, then runs the package's checks, builds it, and uploads with twine. Twine prompts for a PyPI API token unless `TWINE_PASSWORD` is set. Publish `interfaces` before the packages that depend on it, and the `llmgrid` meta-package last.

## Repository layout

```text
packages/<pkg>/          one distribution each: pyproject.toml, src/llmgrid/<pkg>/, tests/
tests/integration/       offline flows across packages
tests/architecture/      dependency rules between packages
tests/typing/            compositions that must fail type checking
examples/                runnable examples
legacy/llm_port/         the pre-pivot llm-port code, kept for reference only
docs/                    design plan and decisions
```

## License

MIT. See [LICENSE](LICENSE).
