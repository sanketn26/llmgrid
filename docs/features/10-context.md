# 10 — Keep the pinned instruction and the newest turn

> Compact history without losing the system message or the latest turn, and search stored artifacts.

← [09](09-grounded-answer.md) · [All features](README.md) · [11](11-experiment.md) →

## Why

Long runs overflow the context window. Compaction must never drop the instruction that defines the agent or the question it is answering.

## Expects

**Behavior (end to end)**

- Compacting three messages to a limit of two keeps the system message and the newest user message.
- A stored artifact can be searched by line.

**Rules**

- No model call and no network.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/context/src/llmgrid/context/history.py` | Artifact store and context builder. |
| `packages/context/src/llmgrid/context/artifacts.py` | File-backed artifacts. |
| `packages/loops/src/llmgrid/loops/compaction.py` | Compaction step used by the context package. |

## Acceptance

- [ ] `packages/context/tests/test_context_window.py` passes.
- [ ] Compacting three messages to two keeps the pinned system message and the newest turn.
- [ ] Artifact search returns the matching line.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/context/tests/test_context_window.py`

Unit tests for compaction and artifact search.

```python
import unittest

from llmgrid.context.history import ArtifactStore, ContextBuilder
from llmgrid.interfaces import Message


class ContextTests(unittest.TestCase):
    def test_compact_keeps_pinned_system_and_newest(self) -> None:
        builder = ContextBuilder(lambda messages: len(messages))
        history = (
            Message("system", "Pinned"),
            Message("user", "old"),
            Message("user", "new"),
        )
        compacted = builder.build(history, limit=2, strategy="compact")
        self.assertEqual(compacted, (history[0], history[-1]))

    def test_artifact_search_returns_the_matching_line(self) -> None:
        store = ArtifactStore("run")
        ref = store.put("large output\nfind this line")
        self.assertEqual(store.search(ref, "find"), ("find this line",))


if __name__ == "__main__":
    unittest.main()
```
