# 04 — The same tool call through five offline adapters

> Five provider adapters encode and decode the same tool-call conversation, fully offline.

← [03](03-replay.md) · [All features](README.md) · [05](05-guardrail.md) →

## Why

Real providers differ in wire format, finish reasons and opaque state (signatures, encrypted reasoning). Fixture round-trips prove the adapters are correct without credentials or network.

## Expects

**Behavior (end to end)**

- One fixture conversation (user question → `add` tool call → tool result `5`) round-trips through Anthropic, OpenAI Responses, OpenAI-compatible, Gemini and Bedrock adapters.
- Nothing opens a socket; no SDK is imported at import time.

**Rules**

- Every adapter except `OpenAICompatibleModel` keeps the fixture's provider state (`signed` or `opaque`) in the follow-up encoding.
- Unknown finish reasons fail.
- These adapters do not stream.
- Do not call a live factory and do not read an API key.
- Optional SDKs are imported inside the functions that need them.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/network/src/llmgrid/network/transport.py` | One-request transport. The fixture records the body and returns a canned response. |
| `packages/network/src/llmgrid/network/adapters.py` | Anthropic, OpenAI Responses, OpenAI-compatible, Gemini and Bedrock conversions. |
| `packages/network/src/llmgrid/network/clients.py` | Client factories with lazy optional imports. |

**Also update / keep green**

- `tests/architecture/test_dependencies.py`: allow the new optional imports, and only in the modules that own them.

## Acceptance

- [ ] `packages/network/tests/test_provider_roundtrip.py` passes.
- [ ] All five adapters round-trip tool call `add` and result `5`.
- [ ] No socket opened, no API key read.
- [ ] Provider state survives on every adapter except `OpenAICompatibleModel`.
- [ ] Importing the adapter module imports no optional SDK.
- [ ] `test_dependencies.py` allows those imports only where they are owned.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/network/tests/test_provider_roundtrip.py`

Expected unit test. The fixture payloads are the contract. The adapters are not included.

```python
import unittest

from llmgrid.interfaces import Budget, ChatRequest, Message, RunContext, ToolResult
from llmgrid.network.adapters import (
    AnthropicModel,
    BedrockModel,
    GeminiModel,
    OpenAICompatibleModel,
    OpenAIModel,
)


class FixtureTransport:
    def __init__(self, response: dict) -> None:
        self.response, self.requests = response, []

    async def send(self, body: dict) -> dict:
        self.requests.append(body)
        return self.response


class ProviderRoundtripTests(unittest.IsolatedAsyncioTestCase):
    async def test_five_adapters_roundtrip_the_add_call(self) -> None:
        fixtures = (
            (
                OpenAICompatibleModel,
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "c1",
                                        "type": "function",
                                        "function": {"name": "add", "arguments": '{"a":2,"b":3}'},
                                    }
                                ],
                            },
                        }
                    ]
                },
            ),
            (
                OpenAIModel,
                {
                    "status": "completed",
                    "output": [
                        {"type": "reasoning", "id": "r1", "encrypted_content": "opaque"},
                        {
                            "type": "function_call",
                            "call_id": "c1",
                            "name": "add",
                            "arguments": '{"a":2,"b":3}',
                        },
                    ],
                },
            ),
            (
                AnthropicModel,
                {
                    "stop_reason": "tool_use",
                    "content": [
                        {"type": "thinking", "thinking": "opaque", "signature": "signed"},
                        {"type": "tool_use", "id": "c1", "name": "add", "input": {"a": 2, "b": 3}},
                    ],
                },
            ),
            (
                GeminiModel,
                {
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "parts": [
                                    {
                                        "functionCall": {"name": "add", "args": {"a": 2, "b": 3}},
                                        "thoughtSignature": "signed",
                                    },
                                ]
                            },
                        }
                    ]
                },
            ),
            (
                BedrockModel,
                {
                    "stopReason": "tool_use",
                    "output": {
                        "message": {
                            "content": [
                                {
                                    "reasoningContent": {
                                        "reasoningText": {"text": "opaque", "signature": "signed"}
                                    }
                                },
                                {
                                    "toolUse": {
                                        "toolUseId": "c1",
                                        "name": "add",
                                        "input": {"a": 2, "b": 3},
                                    }
                                },
                            ]
                        }
                    },
                },
            ),
        )
        for adapter_type, raw in fixtures:
            transport = FixtureTransport(raw)
            adapter = adapter_type("fixture-model", transport)
            context = RunContext("fixture", Budget())
            response = await adapter.generate(
                ChatRequest((Message("user", "2 + 3?"),)), context=context
            )
            assert response.finish == "tool_calls"
            assert response.message.calls[0].name == "add"
            assert response.usage.input_tokens is None
            call = response.message.calls[0]
            followup = ChatRequest(
                (
                    Message("user", "2 + 3?"),
                    response.message,
                    Message("tool", result=ToolResult(call.id, "5")),
                )
            )
            encoded = adapter.encode(followup, "fixture-model")
            assert "5" in str(encoded)
            if adapter_type is not OpenAICompatibleModel:
                assert "signed" in str(encoded) or "opaque" in str(encoded)
            assert len(transport.requests) == 1
            print(adapter_type.__name__, "conversion and continuation passed")


if __name__ == "__main__":
    unittest.main()
```
