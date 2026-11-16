# 13 — Parallel steps, then one streamed answer

> Run steps in parallel with ordered results, and stream one Chat Completions answer.

← [12](12-mcp-tool.md) · [All features](README.md) · [14](14-approval.md) →

## Why

Parallelism must not reorder results or bypass the shared budget; streaming must not act on half-received tool calls.

## Expects

**Behavior (end to end)**

- Doubling `(3, 1, 2)` with two workers returns `(6, 2, 4)`, in that order.
- A canned Chat Completions stream yields text `5`, then a final stop, and charges one model call.

**Rules**

- Parallel children share the parent ledger.
- Never execute a tool from a partial delta.
- Do not claim streaming for the other four adapters.
- The fixture host is never contacted.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/loops/src/llmgrid/loops/parallel.py` | Ordered results, bounded workers, parent budget. |
| `packages/interfaces/src/llmgrid/interfaces/streaming.py` | Text deltas and the final response. |
| `packages/network/src/llmgrid/network/streaming.py` | Assemble one Chat Completions SSE body. |
| `packages/loops/src/llmgrid/loops/telemetry.py` | Subscriber for the dispatch events `invoke` already emits. |

## Acceptance

- [ ] `packages/loops/tests/test_parallel_stream.py` passes.
- [ ] Doubling `(3, 1, 2)` with two workers returns `(6, 2, 4)`.
- [ ] The stream starts with text `5`, ends on finish `stop`, and leaves `model_calls == 1`.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_parallel_stream.py`

Expected unit test. The fake client never contacts the fixture host.

```python
import asyncio
import json
import unittest
from collections.abc import AsyncIterator
from types import TracebackType

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

    async def aiter_lines(self) -> AsyncIterator[str]:
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
    async def __aenter__(self) -> Response:
        return Response()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class FakeClient:
    def stream(self, *args: object, **kwargs: object) -> StreamScope:
        return StreamScope()


class ParallelStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_and_single_stream_charge(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
```
