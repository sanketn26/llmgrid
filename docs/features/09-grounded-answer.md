# 09 — Answer from stored evidence, or stop

> An answer completes only if every citation points at evidence that was actually retrieved.

← [08](08-route-and-errand.md) · [All features](README.md) · [10](10-context.md) →

## Why

Invented citations are a common hallucination. Checking them against the retriever's output turns that into a `Stopped` outcome.

## Expects

**Behavior (end to end)**

- A question about Python async is answered only when the citation is `s1` from the memory retriever.
- An invented citation stops.

**Rules**

- Accept a completion only when every citation was retrieved.
- The memory retriever is lexical — no embedding client, no network.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/interfaces/src/llmgrid/interfaces/retrieval.py` | `Evidence` and the `Retriever` protocol. |
| `packages/rag/src/llmgrid/rag/memory.py` | In-memory lexical retriever. |
| `packages/loops/src/llmgrid/loops/grounded.py` | Grounded step on top of `ModelStep`. |

**Also update / keep green**

- `llmgrid.network`: `ScriptedModel` supplies the JSON answer.

## Acceptance

- [ ] `packages/loops/tests/test_grounded.py` passes.
- [ ] Citation `s1` completes with text `Use await`.
- [ ] Citation `invented` stops with `claimed_unverified`.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_grounded.py`

Unit tests for a real citation and an invented one.

```python
import unittest

from llmgrid.interfaces import Budget, ChatResponse, Message, RunContext
from llmgrid.interfaces.loop import Completed, Stopped
from llmgrid.interfaces.retrieval import Evidence
from llmgrid.loops.grounded import GroundedAnswerStep
from llmgrid.network.scripted import ScriptedModel
from llmgrid.rag.memory import MemoryRetriever


class GroundedAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_known_citation_completes(self) -> None:
        retriever = MemoryRetriever((Evidence("s1", "Python uses await for async calls"),))
        model = ScriptedModel(
            [ChatResponse(Message("assistant", '{"text":"Use await","citations":["s1"]}'), "stop")]
        )
        answer = await GroundedAnswerStep(retriever, model).run(
            "Python async", context=RunContext("composition", Budget(4, 4))
        )
        self.assertIsInstance(answer, Completed)
        assert isinstance(answer, Completed)
        self.assertEqual(answer.value.text, "Use await")

    async def test_invented_citation_stops(self) -> None:
        retriever = MemoryRetriever((Evidence("s1", "Python uses await for async calls"),))
        model = ScriptedModel(
            [
                ChatResponse(
                    Message("assistant", '{"text":"Use await","citations":["invented"]}'),
                    "stop",
                )
            ]
        )
        rejected = await GroundedAnswerStep(retriever, model).run(
            "Python async", context=RunContext("composition", Budget(4, 4))
        )
        self.assertIsInstance(rejected, Stopped)
        assert isinstance(rejected, Stopped)
        self.assertEqual(rejected.reason, "claimed_unverified")


if __name__ == "__main__":
    unittest.main()
```
