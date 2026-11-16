# 14 — Approve once, and do not send an uncertain action again

> Human-approved side effects that are sent at most once, even across crashes.

← [13](13-parallel-stream.md) · [All features](README.md) · [15](15-coding-release.md) →

## Why

If a process dies mid-send, you cannot know whether the action happened. The safe answer is `unknown`, not a resend.

## Expects

**Behavior (end to end)**

- An action is proposed, approved, and sent once.
- A second run stays `succeeded` and does not send again.
- A checkpoint left in `sending` resumes as `unknown` and is not sent.

**Rules**

- A stale version raises `CheckpointConflict`; a stale digest raises `ValueError`.
- `Budget.restore_used` writes saved counters only into a fresh root; a used budget or a child raises `ValueError`.
- Leave `unknown` unknown until something outside this feature can query the external system.
- No network; the dispatch function appends to a list.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/interfaces/src/llmgrid/interfaces/checkpoint.py` | Action and checkpoint values. |
| `packages/loops/src/llmgrid/loops/checkpoints.py` | SQLite store and compare-and-swap. |
| `packages/loops/src/llmgrid/loops/approval.py` | Propose, approve, run once. |

**Also update / keep green**

- `llmgrid.interfaces`: add `Budget.restore_used`.

## Acceptance

- [ ] `packages/loops/tests/test_approval.py` passes.
- [ ] The approved action is sent once; a second run does not resend.
- [ ] A checkpoint left in `sending` resumes as `unknown` and is not sent.
- [ ] A stale save raises `CheckpointConflict`.
- [ ] Approving with a stale digest raises `ValueError`.
- [ ] `restore_used` applies only to a fresh root.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_approval.py`

Expected unit test. Dispatch is an in-memory list.

```python
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from llmgrid.interfaces import Budget, RunContext
from llmgrid.interfaces.checkpoint import Action
from llmgrid.interfaces.execution import Counters, Limits
from llmgrid.loops.approval import ApprovedAction
from llmgrid.loops.checkpoints import CheckpointConflict, SQLiteCheckpoints


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_once_and_uncertain_recovery(self) -> None:
        with TemporaryDirectory() as tmp:
            store = SQLiteCheckpoints(Path(tmp) / "checkpoints.db")
            sent: list[str] = []

            async def dispatch(action: Action) -> str:
                sent.append(action.operation_id)
                return '{"ok":true}'

            executor = ApprovedAction(store, dispatch)
            context = RunContext("approved", Budget(0, 2))
            suspended = executor.propose(Action("fixture", '{"value":1}', "op-1"), context=context)
            checkpoint = suspended.checkpoint
            with self.assertRaises(ValueError):
                executor.approve(context.run_id, version=checkpoint.version, digest="stale-digest")
            executor.approve(
                context.run_id, version=checkpoint.version, digest=checkpoint.request_digest
            )
            finished = await executor.run(context=context)
            assert finished.status == "succeeded"
            assert (await executor.run(context=context)).status == "succeeded"
            assert sent == ["op-1"]
            try:
                store.save(finished, expected_version=0)
            except CheckpointConflict:
                pass
            else:
                raise AssertionError("Stale save accepted")

            uncertain_context = RunContext("uncertain", Budget(0, 2))
            pending = executor.propose(Action("fixture", "{}", "op-2"), context=uncertain_context)
            approved = executor.approve(
                "uncertain",
                version=pending.checkpoint.version,
                digest=pending.checkpoint.request_digest,
            )
            store.save(replace(approved, status="sending"), expected_version=approved.version)
            recovered = await executor.run(context=uncertain_context)
            assert recovered.status == "unknown" and sent == ["op-1"]
            store.close()


class RestoreUsedTests(unittest.TestCase):
    def test_restore_used_only_on_a_fresh_root(self) -> None:
        fresh = Budget(4, 4)
        fresh.restore_used(Counters(1, 2))
        self.assertEqual((fresh.model_calls, fresh.tool_calls), (1, 2))
        fresh.consume("tool")
        with self.assertRaises(ValueError):
            fresh.restore_used(Counters(1, 2))
        child = Budget(4, 4).child(Limits(2, 2))
        with self.assertRaises(ValueError):
            child.restore_used(Counters(0, 0))


if __name__ == "__main__":
    unittest.main()
```
