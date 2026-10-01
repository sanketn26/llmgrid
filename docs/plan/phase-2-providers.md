# Phase 2: all provider adapters

Depends on Phase 1. Implement transport, conversion, then client factories.
The client factory owns connection lifetime; `generate` makes one provider request.
Budgeting happens when a caller dispatches it through `RunContext.invoke`.

| Adapter | API | Client factory |
| --- | --- | --- |
| `AnthropicModel` | Messages | `anthropic`, `anthropic_bedrock`, `anthropic_vertex` |
| `OpenAIModel` | Responses | `openai`, `azure_openai` |
| `OpenAICompatibleModel` | Chat Completions | `openai_compatible` |
| `GeminiModel` | GenerateContent | `gemini`, `gemini_vertex` |
| `BedrockModel` | Converse | `bedrock` |

The conversion boundary uses JSON dictionaries; the library-facing API uses the
Phase 1 dataclasses. Serializers carry provider state unchanged, including reasoning
items, signed thinking blocks, and Gemini thought signatures.

Use a capability profile for the selected model/server. The defaults in the code are
for the fixtures; they do not mean every model supports tools or temperature.
Unsupported stop reasons fail explicitly. Incomplete responses never dispatch tools.
Multimodal input and provider-managed tools require additional serializers; this first
implementation covers text and application-executed tools.

## Starting point

| Action | Starting file / role |
| --- | --- |
| Keep | Phase 1 interfaces and existing `network/{scripted,__init__}.py` |
| Add | `network/{transport,adapters,clients}.py`: there are no existing live adapters |
| Update | `packages/network/pyproject.toml`: add the optional extras shown below |
| Update | `tests/architecture/test_dependencies.py`: allow optional integrations only in the modules that own them |
| Add | `examples/implementation/phase2.py`: offline fixtures for all five adapters |

## Implement these files

[All phases](../composable-agent-platform-plan.md)

### `packages/network/src/llmgrid/network/transport.py`

Add one-request HTTP and SDK transports. Optional SDK imports stay inside the paths that need them.

```python
from collections.abc import Mapping
from typing import Any, Protocol, cast

from llmgrid.interfaces.providers import ProviderError, ProviderTimeoutError, ProviderErrorCode

type Object = dict[str, Any]


class Transport(Protocol):
    async def send(self, body: Object) -> Object: ...


class HttpTransport:
    def __init__(self, client: Any, url: str, headers: Mapping[str, str]) -> None:
        self.client, self.url, self.headers = client, url, dict(headers)

    async def send(self, body: Object) -> Object:
        import httpx

        try:
            response = await self.client.post(self.url, headers=self.headers, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Provider timed out", code="timeout") from exc
        except httpx.RequestError as exc:
            raise ProviderError("Provider transport failed", code="server") from exc
        if response.status_code >= 400:
            status = response.status_code
            code: ProviderErrorCode = (
                "authentication"
                if status in (401, 403)
                else ("rate_limit" if status == 429 else "server" if status >= 500 else "request")
            )
            raise ProviderError(f"Provider HTTP {status}", code=code)
        try:
            value = response.json()
        except ValueError as exc:
            raise ProviderError("Provider returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ProviderError("Provider returned a non-object")
        return value


class SdkTransport:
    # Bind an async SDK method configured with retries disabled.
    def __init__(self, method: Any) -> None:
        self.method = method

    async def send(self, body: Object) -> Object:
        try:
            response = await self.method(**body)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status is None:
                raise
            code: ProviderErrorCode = (
                "authentication"
                if status in (401, 403)
                else ("rate_limit" if status == 429 else "server" if status >= 500 else "request")
            )
            raise ProviderError(f"Provider HTTP {status}", code=code) from exc
        if isinstance(response, dict):
            return response
        return cast(Object, response.model_dump(mode="json", exclude_none=True))
```

### `packages/network/src/llmgrid/network/adapters.py`

Add the five concrete serializers/parsers and model implementations. The functions are separate so fixtures can test conversion without credentials.

```python
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from llmgrid.interfaces import (
    ChatRequest,
    ChatResponse,
    Message,
    ModelCapabilities,
    ProviderState,
    RunContext,
    ToolCall,
)
from llmgrid.interfaces.model import FinishReason, Usage
from llmgrid.interfaces.providers import ProviderError
from llmgrid.network.transport import Object, Transport


def state(message: Message, provider: str) -> Object | None:
    for item in message.provider_state:
        if item.provider == provider:
            raw = json.loads(item.payload_json)
            if not isinstance(raw, dict):
                raise ProviderError("Invalid continuation state")
            return raw
    return None


def usage(raw: Object, input_key: str, output_key: str) -> Usage:
    return Usage(raw.get(input_key), raw.get(output_key))


def finish(raw: str, mapping: dict[str, FinishReason], calls: tuple[ToolCall, ...]) -> FinishReason:
    if raw not in mapping:
        raise ProviderError(f"Unsupported stop reason: {raw}")
    result = mapping[raw]
    if result == "stop" and calls:
        result = "tool_calls"
    if result == "tool_calls" and not calls:
        raise ProviderError("Tool stop without complete calls")
    return result


def options(request: ChatRequest, output_key: str) -> Object:
    result: Object = {}
    if request.max_output_tokens is not None:
        result[output_key] = request.max_output_tokens
    if request.temperature is not None:
        result["temperature"] = request.temperature
    return result


@dataclass
class JsonModel:
    model_id: str
    transport: Transport
    encode: Callable[[ChatRequest, str], Object]
    decode: Callable[[Object], ChatResponse]
    capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True)

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        context.check()
        self.capabilities.validate(request)
        body = self.encode(request, self.model_id)
        raw = await self.transport.send(body)
        try:
            return self.decode(raw)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ProviderError("Malformed provider response") from exc


def encode_compat(request: ChatRequest, model_id: str) -> Object:
    messages: list[Object] = []
    for message in request.messages:
        saved = state(message, "openai_compat")
        if message.role == "assistant" and saved is not None:
            messages.append(saved)
            continue
        item: Object = {"role": message.role, "content": message.text}
        if message.result is not None:
            item.update(content=message.result.content, tool_call_id=message.result.call_id)
        if message.calls:
            item["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.name,
                        "arguments": c.arguments_json,
                    },
                }
                for c in message.calls
            ]
        messages.append(item)
    body: Object = {"model": model_id, "messages": messages, **options(request, "max_tokens")}
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": json.loads(t.input_schema_json),
                },
            }
            for t in request.tools
        ]
    return body


def decode_compat(raw: Object) -> ChatResponse:
    choice = raw["choices"][0]
    item = choice["message"]
    calls = tuple(
        ToolCall(c["id"], c["function"]["name"], c["function"]["arguments"])
        for c in item.get("tool_calls", ())
    )
    end = finish(
        choice["finish_reason"],
        {
            "stop": "stop",
            "tool_calls": "tool_calls",
            "length": "length",
            "content_filter": "content_filter",
        },
        calls,
    )
    if end != "tool_calls":
        calls = ()
        item = {k: v for k, v in item.items() if k != "tool_calls"}
    if item.get("refusal") and end == "stop":
        end = "refusal"
    return ChatResponse(
        Message(
            "assistant",
            item.get("content") or "",
            calls=calls,
            provider_state=(ProviderState("openai_compat", json.dumps(item)),),
        ),
        end,
        usage(raw.get("usage", {}), "prompt_tokens", "completion_tokens"),
    )


def encode_responses(request: ChatRequest, model_id: str) -> Object:
    items: list[Object] = []
    for message in request.messages:
        saved = state(message, "openai")
        if saved is not None and message.role == "assistant":
            items.extend(saved["output"])
            continue
        if message.result is not None:
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.result.call_id,
                    "output": message.result.content,
                }
            )
            continue
        if message.text:
            items.append({"role": message.role, "content": message.text})
        items.extend(
            {
                "type": "function_call",
                "call_id": c.id,
                "name": c.name,
                "arguments": c.arguments_json,
            }
            for c in message.calls
        )
    body: Object = {
        "model": model_id,
        "input": items,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        **options(request, "max_output_tokens"),
    }
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "name": t.name,
                "description": t.description,
                "parameters": json.loads(t.input_schema_json),
            }
            for t in request.tools
        ]
    return body


def decode_responses(raw: Object) -> ChatResponse:
    output = raw.get("output", [])
    text: list[str] = []
    calls: list[ToolCall] = []
    refused = False
    for item in output:
        if item["type"] == "function_call":
            calls.append(ToolCall(item["call_id"], item["name"], item["arguments"]))
        elif item["type"] == "message":
            for part in item["content"]:
                if part["type"] == "output_text":
                    text.append(part["text"])
                elif part["type"] == "refusal":
                    refused = True
                    text.append(part["refusal"])
    status = raw["status"]
    if status == "completed":
        end: FinishReason = "tool_calls" if calls else "refusal" if refused else "stop"
    elif status == "incomplete":
        reason = raw.get("incomplete_details", {}).get("reason")
        if reason not in ("max_output_tokens", "content_filter"):
            raise ProviderError(f"Unknown incomplete reason: {reason}")
        end = "length" if reason == "max_output_tokens" else "content_filter"
        calls.clear()
        output = [item for item in output if item.get("type") != "function_call"]
    else:
        raise ProviderError(f"Unsupported response status: {status}")
    return ChatResponse(
        Message(
            "assistant",
            "".join(text),
            calls=tuple(calls),
            provider_state=(ProviderState("openai", json.dumps({"output": output})),),
        ),
        end,
        usage(raw.get("usage", {}), "input_tokens", "output_tokens"),
    )


def encode_anthropic(request: ChatRequest, model_id: str) -> Object:
    messages: list[Object] = []
    system: list[str] = []
    for message in request.messages:
        if message.role == "system":
            system.append(message.text)
            continue
        saved = state(message, "anthropic")
        if message.role == "assistant" and saved is not None:
            content = saved["content"]
        elif message.result is not None:
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": message.result.call_id,
                    "content": message.result.content,
                    "is_error": message.result.is_error,
                }
            ]
        else:
            content = [{"type": "text", "text": message.text}] if message.text else []
            content += [
                {
                    "type": "tool_use",
                    "id": c.id,
                    "name": c.name,
                    "input": json.loads(c.arguments_json),
                }
                for c in message.calls
            ]
        role = "assistant" if message.role == "assistant" else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
        else:
            messages.append({"role": role, "content": content})
    body: Object = {
        "model": model_id,
        "messages": messages,
        "max_tokens": request.max_output_tokens or 1024,
    }
    if system:
        body["system"] = "\n".join(system)
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.tools:
        body["tools"] = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": json.loads(t.input_schema_json),
            }
            for t in request.tools
        ]
    return body


def decode_anthropic(raw: Object) -> ChatResponse:
    content = raw["content"]
    text = "".join(p["text"] for p in content if p["type"] == "text")
    calls = tuple(
        ToolCall(p["id"], p["name"], json.dumps(p["input"]))
        for p in content
        if p["type"] == "tool_use"
    )
    end = finish(
        raw["stop_reason"],
        {
            "end_turn": "stop",
            "stop_sequence": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
            "refusal": "refusal",
        },
        calls,
    )
    if end != "tool_calls":
        calls = ()
        content = [p for p in content if p["type"] != "tool_use"]
    return ChatResponse(
        Message(
            "assistant",
            text,
            calls=calls,
            provider_state=(ProviderState("anthropic", json.dumps({"content": content})),),
        ),
        end,
        usage(raw.get("usage", {}), "input_tokens", "output_tokens"),
    )


def encode_gemini(request: ChatRequest, model_id: str) -> Object:
    contents: list[Object] = []
    system: list[str] = []
    names = {c.id: c.name for m in request.messages for c in m.calls}
    for message in request.messages:
        if message.role == "system":
            system.append(message.text)
            continue
        saved = state(message, "gemini")
        if saved is not None and message.role == "assistant":
            parts = saved["parts"]
        elif message.result is not None:
            if message.result.call_id not in names:
                raise ProviderError("Tool result has no matching call")
            parts = [
                {
                    "functionResponse": {
                        "name": names[message.result.call_id],
                        "response": {
                            "error" if message.result.is_error else "result": message.result.content
                        },
                    }
                }
            ]
        else:
            parts = [{"text": message.text}] if message.text else []
            parts += [
                {"functionCall": {"name": c.name, "args": json.loads(c.arguments_json)}}
                for c in message.calls
            ]
        role = "model" if message.role == "assistant" else "user"
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": role, "parts": parts})
    config = options(request, "maxOutputTokens")
    body: Object = {"contents": contents, "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n".join(system)}]}
    if request.tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parametersJsonSchema": json.loads(t.input_schema_json),
                    }
                    for t in request.tools
                ]
            }
        ]
    return body


def decode_gemini(raw: Object) -> ChatResponse:
    candidates = raw.get("candidates", [])
    if not candidates:
        if raw.get("promptFeedback", {}).get("blockReason"):
            return ChatResponse(Message("assistant"), "content_filter")
        raise ProviderError("Gemini returned no candidate")
    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(p["text"] for p in parts if "text" in p and not p.get("thought"))
    calls = tuple(
        ToolCall(
            p["functionCall"].get("id") or f"gemini_{uuid4().hex}",
            p["functionCall"]["name"],
            json.dumps(p["functionCall"].get("args", {})),
        )
        for p in parts
        if "functionCall" in p
    )
    end = finish(
        candidate["finishReason"],
        {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "BLOCKLIST": "content_filter",
            "PROHIBITED_CONTENT": "content_filter",
            "SPII": "content_filter",
        },
        calls,
    )
    if end != "tool_calls":
        calls = ()
        parts = [p for p in parts if "functionCall" not in p]
    return ChatResponse(
        Message(
            "assistant",
            text,
            calls=calls,
            provider_state=(ProviderState("gemini", json.dumps({"parts": parts})),),
        ),
        end,
        usage(raw.get("usageMetadata", {}), "promptTokenCount", "candidatesTokenCount"),
    )


def encode_bedrock(request: ChatRequest, model_id: str) -> Object:
    messages: list[Object] = []
    system: list[Object] = []
    for message in request.messages:
        if message.role == "system":
            system.append({"text": message.text})
            continue
        saved = state(message, "bedrock")
        if saved is not None and message.role == "assistant":
            content = saved["content"]
        elif message.result is not None:
            content = [
                {
                    "toolResult": {
                        "toolUseId": message.result.call_id,
                        "content": [{"text": message.result.content}],
                        "status": "error" if message.result.is_error else "success",
                    }
                }
            ]
        else:
            content = [{"text": message.text}] if message.text else []
            content += [
                {
                    "toolUse": {
                        "toolUseId": c.id,
                        "name": c.name,
                        "input": json.loads(c.arguments_json),
                    }
                }
                for c in message.calls
            ]
        role = "assistant" if message.role == "assistant" else "user"
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(content)
        else:
            messages.append({"role": role, "content": content})
    body: Object = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": options(request, "maxTokens"),
    }
    if system:
        body["system"] = system
    if request.tools:
        body["toolConfig"] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": {"json": json.loads(t.input_schema_json)},
                    }
                }
                for t in request.tools
            ]
        }
    return body


def decode_bedrock(raw: Object) -> ChatResponse:
    content = raw["output"]["message"]["content"]
    calls = tuple(
        ToolCall(p["toolUse"]["toolUseId"], p["toolUse"]["name"], json.dumps(p["toolUse"]["input"]))
        for p in content
        if "toolUse" in p
    )
    end = finish(
        raw["stopReason"],
        {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
            "stop_sequence": "stop",
            "guardrail_intervened": "content_filter",
            "content_filtered": "content_filter",
        },
        calls,
    )
    if end != "tool_calls":
        calls = ()
        content = [p for p in content if "toolUse" not in p]
    return ChatResponse(
        Message(
            "assistant",
            "".join(p["text"] for p in content if "text" in p),
            calls=calls,
            provider_state=(ProviderState("bedrock", json.dumps({"content": content})),),
        ),
        end,
        usage(raw.get("usage", {}), "inputTokens", "outputTokens"),
    )


class OpenAICompatibleModel(JsonModel):
    def __init__(
        self,
        model_id: str,
        transport: Transport,
        capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
    ) -> None:
        super().__init__(model_id, transport, encode_compat, decode_compat, capabilities)


class OpenAIModel(JsonModel):
    def __init__(
        self,
        model_id: str,
        transport: Transport,
        capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
    ) -> None:
        super().__init__(model_id, transport, encode_responses, decode_responses, capabilities)


class AnthropicModel(JsonModel):
    def __init__(
        self,
        model_id: str,
        transport: Transport,
        capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
    ) -> None:
        super().__init__(model_id, transport, encode_anthropic, decode_anthropic, capabilities)


class GeminiModel(JsonModel):
    def __init__(
        self,
        model_id: str,
        transport: Transport,
        capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
    ) -> None:
        super().__init__(model_id, transport, encode_gemini, decode_gemini, capabilities)


class BedrockModel(JsonModel):
    def __init__(
        self,
        model_id: str,
        transport: Transport,
        capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
    ) -> None:
        super().__init__(model_id, transport, encode_bedrock, decode_bedrock, capabilities)
```

### `packages/network/src/llmgrid/network/clients.py`

Add async context managers for every planned provider and platform route. Callers supply model IDs, credentials, and capabilities.

```python
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, cast
from collections.abc import AsyncIterator

from llmgrid.interfaces import ModelCapabilities
from llmgrid.interfaces.providers import ProviderError, ProviderErrorCode
from llmgrid.network.adapters import (
    AnthropicModel,
    BedrockModel,
    GeminiModel,
    OpenAICompatibleModel,
    OpenAIModel,
)
from llmgrid.network.transport import HttpTransport, Object, SdkTransport


@asynccontextmanager
async def openai_compatible(
    model_id: str, base_url: str, api_key: str = "", *, capabilities: ModelCapabilities
) -> AsyncIterator[OpenAICompatibleModel]:
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        transport = HttpTransport(client, base_url.rstrip("/") + "/chat/completions", headers)
        yield OpenAICompatibleModel(model_id, transport, capabilities)


@asynccontextmanager
async def openai(
    model_id: str,
    *,
    api_key: str,
    base_url: str = "https://api.openai.com/v1",
    capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
) -> AsyncIterator[OpenAIModel]:
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        transport = HttpTransport(
            client, base_url.rstrip("/") + "/responses", {"Authorization": f"Bearer {api_key}"}
        )
        yield OpenAIModel(model_id, transport, capabilities)


@asynccontextmanager
async def azure_openai(
    deployment: str,
    *,
    endpoint: str,
    api_key: str,
    capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
) -> AsyncIterator[OpenAIModel]:
    # Azure's v1 Responses endpoint uses the deployment name in the model field.
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        transport = HttpTransport(
            client, endpoint.rstrip("/") + "/openai/v1/responses", {"api-key": api_key}
        )
        yield OpenAIModel(deployment, transport, capabilities)


@asynccontextmanager
async def anthropic(
    model_id: str,
    *,
    api_key: str,
    capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
) -> AsyncIterator[AnthropicModel]:
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        transport = HttpTransport(
            client,
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
        yield AnthropicModel(model_id, transport, capabilities)


@asynccontextmanager
async def anthropic_bedrock(model_id: str, *, region: str) -> AsyncIterator[AnthropicModel]:
    from anthropic import AsyncAnthropicBedrock

    async with AsyncAnthropicBedrock(aws_region=region, max_retries=0) as client:
        yield AnthropicModel(model_id, SdkTransport(client.messages.create))


@asynccontextmanager
async def anthropic_vertex(
    model_id: str, *, project: str, region: str
) -> AsyncIterator[AnthropicModel]:
    from anthropic import AsyncAnthropicVertex

    async with AsyncAnthropicVertex(project_id=project, region=region, max_retries=0) as client:
        yield AnthropicModel(model_id, SdkTransport(client.messages.create))


@asynccontextmanager
async def gemini(
    model_id: str,
    *,
    api_key: str,
    capabilities: ModelCapabilities = ModelCapabilities(tool_calling=True),
) -> AsyncIterator[GeminiModel]:
    import httpx

    async with httpx.AsyncClient(timeout=60) as client:
        transport = HttpTransport(
            client,
            f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent",
            {"x-goog-api-key": api_key},
        )
        yield GeminiModel(model_id, transport, capabilities)


class VertexTransport:
    def __init__(self, client: Any, url: str, credentials: Any) -> None:
        self.client, self.url, self.credentials = client, url, credentials
        self.lock = asyncio.Lock()

    async def send(self, body: Object) -> Object:
        from google.auth.transport.requests import Request

        async with self.lock:
            if not self.credentials.valid:
                await asyncio.to_thread(self.credentials.refresh, Request())
        return await HttpTransport(
            self.client, self.url, {"Authorization": f"Bearer {self.credentials.token}"}
        ).send(body)


@asynccontextmanager
async def gemini_vertex(model_id: str, *, project: str, region: str) -> AsyncIterator[GeminiModel]:
    import google.auth
    import httpx

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    host = (
        "aiplatform.googleapis.com" if region == "global" else f"{region}-aiplatform.googleapis.com"
    )
    url = (
        f"https://{host}/v1/projects/{project}/locations/{region}"
        f"/publishers/google/models/{model_id}:generateContent"
    )
    async with httpx.AsyncClient(timeout=60) as client:
        yield GeminiModel(model_id, VertexTransport(client, url, credentials))


class BedrockTransport:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def send(self, body: Object) -> Object:
        from botocore.exceptions import ClientError, ReadTimeoutError

        try:
            return cast(Object, await self.client.converse(**body))
        except ReadTimeoutError as exc:
            from llmgrid.interfaces.providers import ProviderTimeoutError

            raise ProviderTimeoutError("Bedrock timed out", code="timeout") from exc
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            mapped: ProviderErrorCode = (
                "authentication"
                if code in ("AccessDeniedException", "UnrecognizedClientException")
                else ("rate_limit" if code == "ThrottlingException" else "server")
            )
            raise ProviderError(f"Bedrock error: {code}", code=mapped) from exc


@asynccontextmanager
async def bedrock(model_id: str, *, region: str) -> AsyncIterator[BedrockModel]:
    from aiobotocore.session import get_session
    from botocore.config import Config

    session = get_session()
    config = Config(retries={"total_max_attempts": 1}, read_timeout=60)
    async with session.create_client(
        "bedrock-runtime", region_name=region, config=config
    ) as client:
        yield BedrockModel(model_id, BedrockTransport(client))
```

## Run this phase

### `examples/implementation/phase2.py`

```python
import asyncio

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


async def main() -> None:
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
    asyncio.run(main())
```

```bash
.venv/bin/python examples/implementation/phase2.py
```

## Wire a live provider

Add optional extras to `packages/network/pyproject.toml`:

```toml
[project.optional-dependencies]
http = ["httpx"]
anthropic = ["httpx", "anthropic[bedrock,vertex]"]
openai = ["httpx"]
gemini = ["httpx", "google-auth", "requests"]
bedrock = ["aiobotocore"]
```

Use one of the factories with a model/deployment ID available in your account:

```python
import asyncio
import os
from functools import partial
from llmgrid.interfaces import Budget, ChatRequest, Message, RunContext
from llmgrid.network.clients import openai


async def main() -> None:
    async with openai(os.environ["OPENAI_MODEL"], api_key=os.environ["OPENAI_API_KEY"]) as model:
        context = RunContext("live", Budget(1, 0))
        response = await context.invoke(
            partial(model.generate, ChatRequest((Message("user", "Say hello"),)), context=context),
            kind="model",
            label="live-generate",
        )
        print(response.message.text)


asyncio.run(main())
```

For a reasoning model that rejects temperature, pass
`ModelCapabilities(tool_calling=True, temperature=False)` to its factory.
Test optional clients against pinned dependency versions before releasing them.
No credentials or real API calls are needed for the fixture example.

The wire formats and client lifecycles follow the official references:
[OpenAI Chat](https://developers.openai.com/api/reference/resources/chat),
[OpenAI reasoning state](https://developers.openai.com/api/docs/guides/reasoning),
[Azure Responses](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses?view=foundry-classic),
[Anthropic tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools),
[Anthropic platform clients](https://github.com/anthropics/anthropic-sdk-python),
[Gemini GenerateContent](https://ai.google.dev/api/generate-content),
[Bedrock Converse](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html),
[aiobotocore](https://aiobotocore.aio-libs.org/en/stable/tutorial.html), and
[HTTPX async](https://www.python-httpx.org/async/).

## Before moving on

- [ ] All five adapter fixtures pass without optional packages.
- [ ] Run one optional live tool cycle per provider/platform you intend to ship.
- [ ] Add captured fixtures for malformed responses, refusal, truncation, and unsupported settings.

Next: [Phase 3](phase-3-tool-agent.md).
