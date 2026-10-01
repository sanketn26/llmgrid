# Phase 7 example: approve, restart, and recover a publication

[Example phase](phase-7-examples.md) · [All phases](../composable-agent-platform-plan.md)

## Goal and starting point

Prepare a fictional release announcement and pause before publishing it to a local
mock destination. Close and reopen the checkpoint database before approval, then
restore persisted usage and dispatch the exact saved request. A second run returns
the saved result without publishing again.

Exercise a stale approval and a crash-like `sending` checkpoint. The latter becomes
`unknown` and must not be blindly resent. Approval here is simulated by application
code; production applications must authenticate approvers independently.

| Action | Starting file / role |
| --- | --- |
| Reuse | Phase 6 `ApprovedAction`, `SQLiteCheckpoints`, and Phase 1 budget restoration |
| Add | `examples/implementation/showcase_approval.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

### `examples/implementation/showcase_approval.py`

```python
import asyncio
import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from llmgrid.interfaces import Budget, RunContext
from llmgrid.interfaces.checkpoint import Action
from llmgrid.loops.approval import ApprovedAction
from llmgrid.loops.checkpoints import SQLiteCheckpoints


async def main():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "actions.sqlite"
        published = []

        async def publish(action):
            payload = json.loads(action.payload_json)
            if action.kind != "publish-announcement" or payload["destination"] != "mock/releases":
                raise ValueError("Unexpected action")
            published.append(action.operation_id)
            return json.dumps({"receipt": "mock-1", "operation_id": action.operation_id})

        store = SQLiteCheckpoints(path)
        context = RunContext("release", Budget(2, 2))
        # Represent an already-prepared upstream result in this application fixture.
        context.budget.consume("model")
        pending = (
            ApprovedAction(store, publish)
            .propose(
                Action(
                    "publish-announcement",
                    json.dumps({"destination": "mock/releases", "text": "Atlas rollout is ready."}),
                    "release-op-1",
                ),
                context=context,
            )
            .checkpoint
        )
        print("Prepared; awaiting approval:", pending.action.payload_json)
        assert published == []
        store.close()

        store = SQLiteCheckpoints(path)
        try:
            executor = ApprovedAction(store, publish)
            saved = store.load("release")
            assert saved is not None and saved.status == "awaiting_approval"
            budget = Budget(2, 2)
            budget.restore_used(saved.usage)
            resumed = RunContext("release", budget)
            try:
                executor.approve("release", version=saved.version, digest="wrong-request")
            except ValueError:
                pass
            else:
                raise AssertionError("Wrong request approval accepted")
            executor.approve("release", version=saved.version, digest=saved.request_digest)
            done = await executor.run(context=resumed)
            assert done.status == "succeeded" and published == ["release-op-1"]
            assert (await executor.run(context=resumed)) == done
            assert budget.model_calls == 1 and budget.tool_calls == 1
            print("Restarted, approved, published once:", done.result_json)

            uncertain = RunContext("crash", Budget(0, 1))
            proposal = executor.propose(
                Action(
                    "publish-announcement",
                    json.dumps(
                        {
                            "destination": "mock/releases",
                            "text": "Second announcement",
                        }
                    ),
                    "release-op-2",
                ),
                context=uncertain,
            ).checkpoint
            approved = executor.approve(
                "crash", version=proposal.version, digest=proposal.request_digest
            )
            # Match the durable pre-dispatch state; delivery may or may not have happened.
            uncertain.budget.consume("tool")
            store.save(
                replace(approved, status="sending", usage=uncertain.budget.used),
                expected_version=approved.version,
            )
        finally:
            store.close()

        store = SQLiteCheckpoints(path)
        try:
            saved = store.load("crash")
            assert saved is not None
            budget = Budget(0, 1)
            budget.restore_used(saved.usage)
            recovered = await ApprovedAction(store, publish).run(
                context=RunContext("crash", budget),
            )
            assert recovered.status == "unknown"
            assert published == ["release-op-1"] and budget.tool_calls == 1
            print("Uncertain dispatch: unknown; no second publication")
        finally:
            store.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## Run and inspect

After applying the required phases and this file:

```bash
.venv/bin/python examples/implementation/showcase_approval.py
```

The complete documented suite can be checked without modifying production packages:

```bash
.venv/bin/python tools/check_implementation_guide.py --through 7
```

The output shows the exact pending content, one successful receipt after reopening
the database, and an uncertain operation that remains unsent by recovery. The mock
publication list stays in this process while SQLite is reopened; this simulates
checkpoint restart and does not claim a separate durable external service.

## Extend to live use

Inject a real dispatcher with operation IDs and supported idempotency keys. Bind
approval to an authenticated user and display destination and payload before approval.
Reconcile unknown actions by querying the destination with the operation ID; persist
confirmed results with compare-and-swap. Do not infer delivery from a timeout. Store
upstream recipe state separately if the whole agent conversation must also resume.

## Before moving on

- [ ] Nothing is dispatched before approval.
- [ ] A mismatched request digest is rejected.
- [ ] Database reopening preserves action, status, and usage.
- [ ] Repeating a succeeded action returns its stored receipt.
- [ ] A recovered sending state becomes unknown without dispatch or a new charge.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
