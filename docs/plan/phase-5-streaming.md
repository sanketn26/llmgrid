# Phase 5: streaming, bounded concurrency, and telemetry

Depends on Phase 3. `ParallelMap` uses a bounded worker pool and shared parent budget.
`CompatibleStream` is a complete first streaming adapter: text deltas are emitted
immediately, while tool calls are buffered until the final validated response.

Close a stream with `contextlib.aclosing` when stopping consumption early. A stream
reserves its model call itself because an async iterator cannot use the ordinary
`invoke` return shape; do not also reserve it around `stream`.
The HTTP client is owned by the caller. Add `httpx` as an optional network extra.

## Starting point

| Action | Starting file / role |
| --- | --- |
| Keep | Phase 1 context/budget, Phase 2 request/response converters, and Phase 3 agent |
| Add | `interfaces/streaming.py`, `network/streaming.py`, `loops/{parallel,telemetry}.py` |
| Reuse | `encode_compat` and `decode_compat` instead of duplicating provider conversion |
| Update | Optional network HTTP and loops telemetry extras; expose streaming capability only after its checks pass |

## Implement these files

[All phases](../composable-agent-platform-plan.md)

### `packages/loops/src/llmgrid/loops/parallel.py`

Add bounded workers; task-group failure cancels siblings and preserves input order.

```python
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from llmgrid.interfaces import RunContext, Step


@dataclass
class ParallelMap[I, O]:
    step: Step[I, O]
    concurrency: int = 4

    async def run(self, values: Sequence[I], *, context: RunContext) -> tuple[O, ...]:
        if self.concurrency < 1:
            raise ValueError("concurrency must be positive")
        context.check()
        iterator = iter(enumerate(values))
        results: dict[int, O] = {}

        async def worker() -> None:
            # Iteration and reservations contain no await, so one event loop owns them.
            for index, value in iterator:
                child = context.child(f"item-{index}")
                results[index] = await self.step.run(value, context=child)

        async with asyncio.TaskGroup() as group:
            for _ in range(min(self.concurrency, len(values))):
                group.create_task(worker())
        return tuple(results[i] for i in range(len(values)))
```

### `packages/interfaces/src/llmgrid/interfaces/streaming.py`

Add the stream event types. Only `FinalResponse` contains dispatchable tool calls.

```python
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from llmgrid.interfaces import ChatRequest, ChatResponse, RunContext


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class FinalResponse:
    response: ChatResponse


type StreamEvent = TextDelta | FinalResponse


class StreamingChatModel(Protocol):
    def stream(
        self, request: ChatRequest, *, context: RunContext
    ) -> AsyncIterator[StreamEvent]: ...
```

### `packages/network/src/llmgrid/network/streaming.py`

Add SSE parsing and a Chat Completions stream assembler. Reject a stream with no final reason.

```python
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from llmgrid.interfaces import ChatRequest, ModelCapabilities, RunContext
from llmgrid.interfaces.providers import ProviderError
from llmgrid.interfaces.streaming import FinalResponse, StreamEvent, TextDelta
from llmgrid.network.adapters import decode_compat, encode_compat
from llmgrid.network.transport import Object


async def sse_json(lines: AsyncIterator[str]) -> AsyncIterator[Object]:
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                payload = "\n".join(data)
                data.clear()
                if payload == "[DONE]":
                    return
                yield json.loads(payload)
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        raise ProviderError("Stream ended inside an SSE event")


class CompatibleStream:
    def __init__(self, client: Any, url: str, headers: dict[str, str], model_id: str) -> None:
        self.client, self.url, self.headers, self.model_id = client, url, headers, model_id
        self.capabilities = ModelCapabilities(tool_calling=True, streaming=True)

    async def stream(
        self, request: ChatRequest, *, context: RunContext
    ) -> AsyncIterator[StreamEvent]:
        context.check()
        self.capabilities.validate(request)
        context.budget.consume("model")
        body = encode_compat(request, self.model_id)
        body.update(stream=True, stream_options={"include_usage": True})
        calls: dict[int, Object] = {}
        text: list[str] = []
        reason = None
        usage: Object = {}
        async with __import__("asyncio").timeout_at(context.deadline):
            async with self.client.stream(
                "POST", self.url, headers=self.headers, json=body
            ) as response:
                if response.status_code >= 400:
                    raise ProviderError(f"Provider HTTP {response.status_code}")
                async for event in sse_json(response.aiter_lines()):
                    if event.get("usage"):
                        usage = event["usage"]
                    if not event.get("choices"):
                        continue
                    choice = event["choices"][0]
                    delta = choice["delta"]
                    if delta.get("content"):
                        text.append(delta["content"])
                        yield TextDelta(delta["content"])
                    for part in delta.get("tool_calls", []):
                        call = calls.setdefault(
                            part["index"],
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        call["id"] += part.get("id") or ""
                        function = part.get("function", {})
                        call["function"]["name"] += function.get("name") or ""
                        call["function"]["arguments"] += function.get("arguments") or ""
                    if choice.get("finish_reason") is not None:
                        reason = choice["finish_reason"]
        if reason is None:
            raise ProviderError("Stream ended without a finish reason")
        raw = {
            "choices": [
                {
                    "finish_reason": reason,
                    "message": {
                        "role": "assistant",
                        "content": "".join(text),
                        "tool_calls": [calls[i] for i in sorted(calls)],
                    },
                }
            ],
            "usage": usage,
        }
        yield FinalResponse(decode_compat(raw))
```

### `packages/loops/src/llmgrid/loops/telemetry.py`

Add an optional event exporter. This exports event spans, not complete operation-duration spans.

```python
from typing import Any
from llmgrid.interfaces.execution import Event


class OpenTelemetrySink:
    def __init__(self, tracer: Any) -> None:
        self.tracer = tracer

    def emit(self, event: Event) -> None:
        # Event export; full-duration operation spans can be added at invoke boundaries.
        with self.tracer.start_as_current_span(event.label) as span:
            span.set_attribute("llmgrid.run_id", event.run_id)
            span.set_attribute("llmgrid.path", "/".join(event.path))
            span.add_event(event.status)
```

## Run this phase

### `examples/implementation/phase5.py`

```python
import asyncio
import json

from llmgrid.interfaces import Budget, ChatRequest, Message, RunContext
from llmgrid.interfaces.streaming import FinalResponse, TextDelta
from llmgrid.loops.parallel import ParallelMap
from llmgrid.network.streaming import CompatibleStream


class Echo:
    async def run(self, value: int, *, context: RunContext) -> int:
        context.check()
        await asyncio.sleep(0)
        return value * 2


class Response:
    status_code = 200

    async def aiter_lines(self):
        chunks = (
            {"choices": [{"delta": {"content": "5"}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        )
        for chunk in chunks:
            yield "data: " + json.dumps(chunk)
            yield ""
        yield "data: [DONE]"
        yield ""


class StreamScope:
    async def __aenter__(self):
        return Response()

    async def __aexit__(self, *args):
        pass


class FakeClient:
    def stream(self, *args, **kwargs):
        return StreamScope()


async def main() -> None:
    context = RunContext("parallel", Budget(2, 0))
    assert await ParallelMap(Echo(), 2).run((3, 1, 2), context=context) == (6, 2, 4)
    model = CompatibleStream(FakeClient(), "https://fixture.invalid", {}, "fixture")
    events = [
        event
        async for event in model.stream(ChatRequest((Message("user", "2+3"),)), context=context)
    ]
    assert isinstance(events[0], TextDelta) and events[0].text == "5"
    assert isinstance(events[-1], FinalResponse) and events[-1].response.finish == "stop"
    assert context.budget.model_calls == 1
    print("Phase 5: ordered parallel steps and streamed final response passed")


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
.venv/bin/python examples/implementation/phase5.py
```

## Connect a stream to the agent

```python
from contextlib import aclosing
from llmgrid.interfaces.streaming import FinalResponse, TextDelta


# Run inside async code with an HTTP client and a prepared context.
async def collect(stream_model, request, context):
    async with aclosing(stream_model.stream(request, context=context)) as events:
        async for event in events:
            if isinstance(event, TextDelta):
                print(event.text, end="")
            elif isinstance(event, FinalResponse):
                return event.response
    raise ValueError("No final response")
```

For the other Phase 2 APIs, use these concrete aggregation rules before calling their
existing decoder. Reuse `sse_json` for HTTP SSE; use the SDK event iterator for Bedrock.

| API | Accumulate | Final response |
| --- | --- | --- |
| Responses | `response.output_text.delta` for display; preserve output item state | Decode `response.completed.response` or `response.incomplete.response` |
| Anthropic | `message_start.message`; content block starts/deltas; JSON argument fragments; thinking/signature deltas | Apply `message_delta.stop_reason` and usage, then decode after `message_stop` |
| Gemini | Candidate text/parts and thought signatures across GenerateContent chunks | Decode the merged candidate only after `finishReason` |
| Bedrock | `messageStart`, content block start/deltas, reasoning/signatures, `messageStop`, `metadata` | Build the Converse response object and call `decode_bedrock` |

The complete Chat Completions implementation above is the starting point. Provider
stream assemblers need provider fixtures before claiming streaming support; the Phase 2
adapters remain non-streaming until those assemblers pass their checks.

## Before moving on

- [ ] The streaming/parallel example passes.
- [ ] Cancellation closes streams and cancels sibling tasks.
- [ ] No partial tool arguments reach an executor; concurrent children respect parent limits.

Next: [Phase 6](phase-6-recovery.md).
