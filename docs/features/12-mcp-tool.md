# 12 — One allowed MCP tool against a fake session

> Expose a restricted subset of an MCP server's tools, tested against a fake session.

← [11](11-experiment.md) · [All features](README.md) · [13](13-parallel-stream.md) →

## Why

MCP servers can expose many tools; an agent should only see the ones it was granted, and an unknown call must never reach the server.

## Expects

**Behavior (end to end)**

- A restricted MCP tool list runs `add`.
- It refuses `delete` without calling the session.

**Rules**

- No real MCP server and no extra package.
- Discover, restrict, execute. No automatic retry.
- Restricting to a tool that was never discovered raises `ValueError`.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/tools/src/llmgrid/tools/mcp_source.py` | MCP session wrapper. |

## Acceptance

- [ ] `packages/tools/tests/test_mcp_source.py` passes.
- [ ] A fake session runs `add` and does not run an unknown tool.
- [ ] Restricting to an undiscovered tool raises `ValueError`.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/tools/tests/test_mcp_source.py`

Unit tests for an allowed call, an unknown call, and a bad restriction.

```python
import unittest

from llmgrid.interfaces import Budget, RunContext, ToolCall, ToolSpec
from llmgrid.tools.mcp_source import McpTools


class Content:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class Result:
    def __init__(self, text: str, is_error: bool = False) -> None:
        self.content = [Content(text)]
        self.isError = is_error


class Session:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, name: str, *, arguments: dict) -> Result:
        self.calls.append(name)
        return Result("ok")


class McpToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_allowed_tool_runs_and_unknown_tool_does_not(self) -> None:
        session = Session()
        tools = McpTools(session, (ToolSpec("add", "Add", "{}"),)).restricted({"add"})
        context = RunContext("mcp", Budget(0, 2))
        allowed = await tools.execute(ToolCall("1", "add", "{}"), context=context)
        denied = await tools.execute(ToolCall("2", "delete", "{}"), context=context)
        self.assertEqual(allowed.content, "ok")
        self.assertFalse(allowed.is_error)
        self.assertTrue(denied.is_error)
        self.assertEqual(session.calls, ["add"])

    def test_unknown_restriction_is_rejected(self) -> None:
        tools = McpTools(Session(), (ToolSpec("add", "Add", "{}"),))
        with self.assertRaises(ValueError):
            tools.restricted({"missing"})


if __name__ == "__main__":
    unittest.main()
```
