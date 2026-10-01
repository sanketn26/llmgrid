# Phase 7 example: research brief with inspectable citations

[Example phase](phase-7-examples.md) · [All phases](../composable-agent-platform-plan.md)

## Goal and starting point

Answer “What does the Atlas launch require?” from a bundled fictional launch packet.
Return a short brief with source IDs and display the source text next to it. Save the
brief as an artifact that can be searched without resending the whole document.

The happy path, invented citation, and empty retrieval all run offline. A charged
retriever wrapper makes retrieval visible in the tool budget. The existing grounding
step validates citation membership, not whether every claim is entailed by its cited
source. Show that boundary explicitly; live claim-support verification is an extension.

| Action | Starting file / role |
| --- | --- |
| Reuse | Phase 4 `GroundedAnswerStep`, `MemoryRetriever`, and `ArtifactStore` |
| Add | `examples/implementation/showcase_research.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

### `examples/implementation/showcase_research.py`

```python
import asyncio
import json
from dataclasses import dataclass
from functools import partial

from llmgrid.context.history import ArtifactStore
from llmgrid.interfaces import Budget, ChatResponse, Message, RunContext
from llmgrid.interfaces.loop import Completed, Stopped
from llmgrid.interfaces.retrieval import Evidence
from llmgrid.loops.grounded import GroundedAnswerStep
from llmgrid.network.scripted import ScriptedModel
from llmgrid.rag.memory import MemoryRetriever

SOURCES = (
    Evidence(
        "launch", "Atlas launch requires a rollback owner and a staged rollout.", "packet/launch"
    ),
    Evidence(
        "support",
        "Atlas launch requires support coverage for the first 24 hours.",
        "packet/support",
    ),
    Evidence("unrelated", "The office kitchen closes at six.", "packet/office"),
)


@dataclass
class ChargedRetriever:
    inner: MemoryRetriever

    async def retrieve(self, query, *, limit, context):
        return await context.invoke(
            partial(self.inner.retrieve, query, limit=limit, context=context),
            kind="tool",
            label="retrieve-launch-packet",
        )


def answer_model(text, citations):
    return ScriptedModel(
        [
            ChatResponse(
                Message(
                    "assistant",
                    json.dumps(
                        {
                            "text": text,
                            "citations": citations,
                        }
                    ),
                ),
                "stop",
            )
        ]
    )


async def main():
    retriever = ChargedRetriever(MemoryRetriever(SOURCES))
    context = RunContext("brief", Budget(1, 1))
    result = await GroundedAnswerStep(
        retriever,
        answer_model(
            "Assign a rollback owner, stage the rollout, and cover support for 24 hours.",
            ["launch", "support"],
        ),
    ).run("Atlas launch requires", context=context)
    assert isinstance(result, Completed)
    assert {s.source_id for s in result.value.evidence} == {"launch", "support"}
    assert result.usage.model_calls == 1 and result.usage.tool_calls == 1
    lines = [result.value.text, "Citations: " + ", ".join(result.value.citations)]
    lines.extend(f"[{s.source_id}] {s.locator}: {s.content}" for s in result.value.evidence)
    store = ArtifactStore(context.run_id)
    ref = store.put("\n".join(lines))
    assert store.search(ref, "rollback")
    print(store.read(ref))
    print("Artifact:", ref.digest, "Usage: 1 model / 1 retrieval")

    bad = await GroundedAnswerStep(retriever, answer_model("Launch tomorrow", ["invented"])).run(
        "Atlas launch",
        context=RunContext("bad-citation", Budget(1, 1)),
    )
    assert isinstance(bad, Stopped) and bad.reason == "claimed_unverified"
    empty_context = RunContext("no-evidence", Budget(1, 1))
    empty = await GroundedAnswerStep(retriever, answer_model("Guess", ["launch"])).run(
        "quasar",
        context=empty_context,
    )
    assert isinstance(empty, Stopped) and empty.reason == "verification_inconclusive"
    assert empty_context.budget.model_calls == 0
    print("Invented citation rejected; empty retrieval skipped generation")


if __name__ == "__main__":
    asyncio.run(main())
```

## Run and inspect

After applying the required phases and this file:

```bash
.venv/bin/python examples/implementation/showcase_research.py
```

The complete documented suite can be checked without modifying production packages:

```bash
.venv/bin/python tools/check_implementation_guide.py --through 7
```

The brief lists both launch sources, prints their locators and contents, and exposes
an artifact digest. The failure cases print that an invented source was rejected and
that no generation occurred when retrieval returned nothing. The in-memory artifact
lasts for this process; use Phase 4 `FileArtifacts` for durable storage.

## Extend to live use

Inject a Phase 2 model and a production Retriever behind the charged wrapper. Keep
retrieval limits and source IDs stable. Add a verifier that checks claim-to-source
support before describing live answers as factually grounded. For private corpora,
authorize retrieval before fetching documents. Evaluate against questions with known
answers and intentionally irrelevant or conflicting evidence.

## Before moving on

- [ ] Only relevant documents are retrieved.
- [ ] Every displayed citation exists in the supplied evidence.
- [ ] Empty retrieval consumes one retrieval call and zero model calls.
- [ ] Invented citation yields `Stopped`, never a published brief.
- [ ] Artifact content includes both the answer and inspectable sources.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
