# legacy/llm_port

The original `llm-port` code, kept as reference while its useful parts move into the llmgrid packages. It is not built, tested, linted, or type-checked, and nothing imports it.

Migration targets (see `docs/composable-agent-platform-plan.md`, Section 9):

| Legacy module | Destination |
| --- | --- |
| `types.py` | Superseded by `llmgrid.interfaces` values; reuse `Usage` fields and `ToolCall.origin` ideas |
| `errors.py` | `llmgrid.interfaces.errors` taxonomy (rename `TimeoutError` to `ProviderTimeoutError`) |
| `config.py` | Adapter constructor arguments in `llmgrid.network`; keep `RetryPolicy`; drop `tool_repair_attempts` |
| `spec/models.py` | `ModelCapabilities` in interfaces; catalogue and lookup in `llmgrid.network` |
| `tools.py`, `spec/tools.py` | One `ToolSpec` in interfaces; provider rendering in network serializers; `ArgSpec` only for prompted-tool instructions |

Delete this directory once Phase 2 has absorbed it.
