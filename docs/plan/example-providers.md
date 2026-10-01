# Phase 7 example: one research workflow across five provider adapters

[Example phase](phase-7-examples.md) · [All phases](../composable-agent-platform-plan.md)

## Goal and starting point

Run the same question, document, verifier, and call limits through five actual
adapter classes backed by provider-shaped response fixtures. Compare normalized
outcomes and usage in a table. Repeat each adapter with an invented citation to
show that application verification does not depend on provider response format.

This is an adapter portability demonstration. Fixtures provide no evidence about
real model quality, latency, price, or current provider availability.

| Action | Starting file / role |
| --- | --- |
| Reuse | Phase 2 adapters and Phase 4 grounded research workflow |
| Add | `examples/implementation/showcase_providers.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

### `examples/implementation/showcase_providers.py`

```python
import asyncio
import json

from showcase_research import ChargedRetriever

from llmgrid.interfaces import Budget, RunContext
from llmgrid.interfaces.loop import Completed, Stopped
from llmgrid.interfaces.retrieval import Evidence
from llmgrid.loops.grounded import GroundedAnswerStep
from llmgrid.network.adapters import (
    AnthropicModel,
    BedrockModel,
    GeminiModel,
    OpenAICompatibleModel,
    OpenAIModel,
)
from llmgrid.rag.memory import MemoryRetriever


class FixtureTransport:
    def __init__(self, response):
        self.response, self.requests = response, []

    async def send(self, body):
        self.requests.append(body)
        return self.response


def fixtures(text):
    return (
        (
            OpenAICompatibleModel,
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"role": "assistant", "content": text}}
                ]
            },
        ),
        (
            OpenAIModel,
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text}],
                    }
                ],
            },
        ),
        (AnthropicModel, {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}),
        (
            GeminiModel,
            {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]},
        ),
        (
            BedrockModel,
            {"stopReason": "end_turn", "output": {"message": {"content": [{"text": text}]}}},
        ),
    )


async def main():
    print("Adapter | outcome | model calls | retrieval calls")
    for citation in ("launch", "invented"):
        text = json.dumps({"text": "Use a staged rollout.", "citations": [citation]})
        for adapter_type, raw in fixtures(text):
            transport = FixtureTransport(raw)
            model = adapter_type("offline-fixture-model", transport)
            retriever = ChargedRetriever(
                MemoryRetriever(
                    (
                        Evidence(
                            "launch",
                            "Atlas launch requires a staged rollout.",
                        ),
                    )
                )
            )
            context = RunContext(adapter_type.__name__ + citation, Budget(1, 1))
            result = await GroundedAnswerStep(retriever, model).run("Atlas launch", context=context)
            if citation == "launch":
                assert isinstance(result, Completed)
                assert result.value.text == "Use a staged rollout."
            else:
                assert isinstance(result, Stopped) and result.reason == "claimed_unverified"
            assert len(transport.requests) == 1
            assert "Atlas launch" in json.dumps(transport.requests[0])
            assert context.budget.model_calls == 1 and context.budget.tool_calls == 1
            print(f"{adapter_type.__name__} | {type(result).__name__} | 1 | 1")
    print("All five adapters share the workflow and reject invented citations")


if __name__ == "__main__":
    asyncio.run(main())
```

## Run and inspect

After applying the required phases and this file:

```bash
.venv/bin/python examples/implementation/showcase_providers.py
```

The complete documented suite can be checked without modifying production packages:

```bash
.venv/bin/python tools/check_implementation_guide.py --through 7
```

The table has ten rows: five Completed fixture runs and five Stopped invalid-citation
runs. Every row uses one model call and one retrieval call. The transport captures the
actual serialized request and the assertions check that the common question survived
encoding.

## Extend to live use

Construct adapters using Phase 2 client lifecycle wiring and credentials supplied
outside source code. Run a fixed held-out dataset and record model identifiers,
settings, verified success rate, latency, tokens when supplied, and failures. Set
compatible options explicitly; provider defaults are not equivalent. Keep non-streaming
and streaming comparisons separate and report missing usage fields as unknown.

## Before moving on

- [ ] Five adapter formats normalize into the same verified answer.
- [ ] Each serialized request includes the same question.
- [ ] All adapters reject the invented citation at the application layer.
- [ ] Every run has its own context and fixture transport.
- [ ] No fixture result is presented as a live provider benchmark.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
