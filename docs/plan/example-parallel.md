# Phase 7 example: parallel launch investigation with streamed report

[Example phase](phase-7-examples.md) · [All phases](../composable-agent-platform-plan.md)

## Goal and starting point

Split a fictional launch review into engineering, support, and rollback questions.
Each worker retrieves and verifies its own short finding using a child context and
its own model. Two workers run at a time; results retain input order even when their
work completes in a different order. Merge only completed findings with citations.

Stream the assembled report through an OpenAI-compatible SSE fixture, expose text
deltas, and require the final event before publishing. This fixture demonstrates
transport assembly; its stream content is predetermined, not a live synthesis model.
A deliberately unsupported question yields Stopped and the report assembler refuses
it rather than silently publishing a partial investigation.

| Action | Starting file / role |
| --- | --- |
| Reuse | Phase 5 `ParallelMap`, `CompatibleStream`, and Phase 4 grounded research |
| Add | `examples/implementation/showcase_parallel.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

### `examples/implementation/showcase_parallel.py`

```python
import asyncio
import json
from dataclasses import dataclass

from showcase_research import ChargedRetriever, answer_model

from llmgrid.interfaces import Budget, ChatRequest, Message, RunContext
from llmgrid.interfaces.loop import Completed, Stopped
from llmgrid.interfaces.retrieval import Evidence
from llmgrid.interfaces.streaming import FinalResponse, TextDelta
from llmgrid.loops.grounded import GroundedAnswerStep
from llmgrid.loops.parallel import ParallelMap
from llmgrid.network.streaming import CompatibleStream
from llmgrid.rag.memory import MemoryRetriever

PACKET = {
    "engineering": "Engineering requires a staged rollout.",
    "support": "Support requires 24-hour coverage.",
    "rollback": "Rollback requires a named owner.",
}


@dataclass
class Investigate:
    active: int = 0
    maximum: int = 0

    async def run(self, topic, *, context):
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(0)
            text = PACKET.get(topic, "Unknown")
            retriever = ChargedRetriever(
                MemoryRetriever(
                    tuple(Evidence(key, value, "launch/" + key) for key, value in PACKET.items())
                )
            )
            return await GroundedAnswerStep(retriever, answer_model(text, [topic])).run(
                topic,
                context=context,
            )
        finally:
            self.active -= 1


def merge(topics, findings):
    if len(topics) != len(findings) or any(not isinstance(f, Completed) for f in findings):
        raise ValueError("Incomplete investigation; inspect stopped workers")
    return "\n".join(
        f"{topic}: {finding.value.text} [{','.join(finding.value.citations)}]"
        for topic, finding in zip(topics, findings, strict=True)
    )


class Response:
    status_code = 200

    def __init__(self, text):
        self.text = text

    async def aiter_lines(self):
        chunks = [self.text[: len(self.text) // 2], self.text[len(self.text) // 2 :]]
        for chunk in chunks:
            yield "data: " + json.dumps(
                {"choices": [{"delta": {"content": chunk}, "finish_reason": None}]}
            )
            yield ""
        yield "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        yield ""
        yield "data: [DONE]"
        yield ""


class Scope:
    def __init__(self, text):
        self.text = text

    async def __aenter__(self):
        return Response(self.text)

    async def __aexit__(self, *args):
        pass


class FixtureClient:
    def __init__(self, text):
        self.text = text

    def stream(self, *args, **kwargs):
        return Scope(self.text)


async def main():
    topics = ("engineering", "support", "rollback")
    context = RunContext("parallel-review", Budget(4, 3))
    worker = Investigate()
    findings = await ParallelMap(worker, 2).run(topics, context=context)
    assert worker.maximum == 2 and worker.active == 0
    report = merge(topics, findings)
    assert report.splitlines()[0].startswith("engineering:")
    model = CompatibleStream(FixtureClient(report), "https://fixture.invalid", {}, "fixture")
    events = [
        event
        async for event in model.stream(
            ChatRequest((Message("user", "Format these verified findings: " + report),)),
            context=context,
        )
    ]
    deltas = [event.text for event in events if isinstance(event, TextDelta)]
    assert len(deltas) == 2 and "".join(deltas) == report
    assert isinstance(events[-1], FinalResponse) and events[-1].response.message.text == report
    assert events[-1].response.finish == "stop"
    print("Concurrency: 2; verified findings in input order")
    for index, delta in enumerate(deltas):
        print(f"Stream chunk {index}: {delta!r}")
    print("Final report:\n" + report)
    assert context.budget.model_calls == 4 and context.budget.tool_calls == 3

    failed = await ParallelMap(Investigate(), 2).run(
        ("engineering", "quasar"),
        context=RunContext("partial", Budget(2, 2)),
    )
    assert isinstance(failed[1], Stopped)
    try:
        merge(("engineering", "quasar"), failed)
    except ValueError:
        print("Missing evidence: final report withheld")
    else:
        raise AssertionError("Partial report published")


if __name__ == "__main__":
    asyncio.run(main())
```

## Run and inspect

After applying the required phases and this file:

```bash
.venv/bin/python examples/implementation/showcase_parallel.py
```

The complete documented suite can be checked without modifying production packages:

```bash
.venv/bin/python tools/check_implementation_guide.py --through 7
```

The report lists engineering, support, and rollback in that order. Two visible chunks
assemble into the exact final response. Three findings plus one formatting stream cost
four model calls and three retrieval calls. The unsupported topic prevents publication.
Child contexts share the root budget; no independent worker can spend beyond it.

## Extend to live use

Inject a model factory per worker and use real retrievers. Retain a deliberate
policy for partial results; this recipe requires all workers to complete. Replace the
SSE fixture with a real compatible streaming client and distinguish preview text from
the final verified report. Recheck citations and claim support after live synthesis,
since formatting can introduce unsupported claims. Limit retrieved context per worker.

## Before moving on

- [ ] Observed worker concurrency reaches two and never exceeds it.
- [ ] Findings retain input order and cite their source IDs.
- [ ] All workers have independent models and share the root budget.
- [ ] Text deltas reconstruct the final response exactly.
- [ ] A stopped worker prevents final report assembly.
- [ ] Live integration additionally checks sibling cancellation and truncated streams.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
