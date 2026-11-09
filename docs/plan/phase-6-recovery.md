# Phase 6: approval, checkpoints, and uncertain actions

Depends on Phase 3 and the Phase 4 journal for experiment resume.
Implement the data types, SQLite store, then the approval executor.

The executor persists `sending` before external dispatch. A recovered `sending`
action becomes `unknown`; it is never blindly repeated. Use `operation_id` as the
provider idempotency key when the provider supports it. A confirmed rejection can
raise `ActionRejected`; a timeout after dispatch is uncertain.

An application must authenticate the person approving an action before calling
`approve`; matching the request digest/version binds the approval but does not
establish who approved it. `Action` is also the proposal format for outside effects
produced by the long-running loops.

This checkpoint stores one pending action. Store a recipe's stable step ID, messages,
inputs, context strategy, and settings version in its payload when suspending mid-run.
On process restart, restore `checkpoint.usage` into a fresh root budget before resuming.
On-disk data is versioned by checkpoint version and journal schema; add explicit schema
migrations when these dataclasses change.

## Starting point

| Action | Starting file / role |
| --- | --- |
| Keep | Phase 1 budget/context, Phase 3 outcome types, and Phase 4 round journal |
| Add | `interfaces/checkpoint.py`, `loops/{checkpoints,approval}.py`, and the recovery example |
| Extend | Application wiring to persist inputs, operation IDs, approval identity, and recipe position |
| Reuse | Standard-library SQLite; no existing database implementation needs to be migrated |

## Implement these files

[All phases](../composable-agent-platform-plan.md)

### `packages/interfaces/src/llmgrid/interfaces/checkpoint.py`

Add the action, checkpoint, and suspended result types.

```python
from dataclasses import dataclass
from typing import Literal

from llmgrid.interfaces.execution import Counters


@dataclass(frozen=True)
class Action:
    kind: str
    payload_json: str
    operation_id: str


@dataclass(frozen=True)
class Checkpoint:
    run_id: str
    version: int
    action: Action
    request_digest: str
    status: Literal["awaiting_approval", "approved", "sending", "succeeded", "failed", "unknown"]
    usage: Counters
    result_json: str | None = None


@dataclass(frozen=True)
class Suspended:
    checkpoint: Checkpoint
```

### `packages/loops/src/llmgrid/loops/checkpoints.py`

Add transactional compare-and-swap saves with SQLite WAL and full synchronization.

```python
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path

from llmgrid.interfaces.checkpoint import Action, Checkpoint
from llmgrid.interfaces.execution import Counters


class CheckpointConflict(ValueError):
    pass


def request_digest(action: Action) -> str:
    payload = json.loads(action.payload_json)
    raw = json.dumps(
        {"kind": action.kind, "payload": payload, "operation_id": action.operation_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


class SQLiteCheckpoints:
    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints "
            "(run_id TEXT PRIMARY KEY, version INTEGER NOT NULL, body TEXT NOT NULL)"
        )

    def close(self) -> None:
        self.db.close()

    def load(self, run_id: str) -> Checkpoint | None:
        row = self.db.execute("SELECT body FROM checkpoints WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        raw = json.loads(row[0])
        raw["action"] = Action(**raw["action"])
        raw["usage"] = Counters(**raw["usage"])
        return Checkpoint(**raw)

    def save(self, value: Checkpoint, *, expected_version: int | None) -> Checkpoint:
        version = 0 if expected_version is None else expected_version + 1
        saved = replace(value, version=version)
        body = json.dumps(asdict(saved), sort_keys=True)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if expected_version is None:
                try:
                    self.db.execute(
                        "INSERT INTO checkpoints VALUES (?, ?, ?)", (saved.run_id, version, body)
                    )
                except sqlite3.IntegrityError as exc:
                    raise CheckpointConflict("Checkpoint already exists") from exc
            else:
                cursor = self.db.execute(
                    "UPDATE checkpoints SET version=?, body=? WHERE run_id=? AND version=?",
                    (version, body, saved.run_id, expected_version),
                )
                if cursor.rowcount != 1:
                    raise CheckpointConflict("Stale checkpoint version")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return saved
```

### `packages/loops/src/llmgrid/loops/approval.py`

Add request-bound approval, durable dispatch intent, and explicit unknown-action recovery.

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace
from functools import partial

from llmgrid.interfaces import RunContext
from llmgrid.interfaces.checkpoint import Action, Checkpoint, Suspended
from llmgrid.loops.checkpoints import SQLiteCheckpoints, request_digest


class ActionRejected(Exception):
    # Use only when the external system confirms the operation did not take effect.
    pass


class ApprovedAction:
    def __init__(
        self, store: SQLiteCheckpoints, dispatch: Callable[[Action], Awaitable[str]]
    ) -> None:
        self.store, self.dispatch = store, dispatch

    def propose(self, action: Action, *, context: RunContext) -> Suspended:
        context.check()
        saved = self.store.save(
            Checkpoint(
                context.run_id,
                0,
                action,
                request_digest(action),
                "awaiting_approval",
                context.budget.used,
            ),
            expected_version=None,
        )
        return Suspended(saved)

    def approve(self, run_id: str, *, version: int, digest: str) -> Checkpoint:
        value = self.store.load(run_id)
        if value is None or value.status != "awaiting_approval":
            raise ValueError("No pending approval")
        if value.version != version or value.request_digest != digest:
            raise ValueError("Approval does not match this request/version")
        return self.store.save(replace(value, status="approved"), expected_version=version)

    async def run(self, *, context: RunContext) -> Checkpoint:
        value = self.store.load(context.run_id)
        if value is None:
            raise ValueError("No saved action")
        if value.status in ("succeeded", "failed", "unknown"):
            return value
        if value.status == "sending":
            # The previous process may have dispatched it. Do not send it again.
            return self.store.save(replace(value, status="unknown"), expected_version=value.version)
        if value.status != "approved":
            raise ValueError("Action needs approval")
        if request_digest(value.action) != value.request_digest:
            raise ValueError("Saved action digest mismatch")
        context.check()
        context.budget.consume("tool")
        sending = self.store.save(
            replace(value, status="sending", usage=context.budget.used),
            expected_version=value.version,
        )
        try:
            # The tool budget was charged and persisted before dispatch.
            result = await context.invoke(
                partial(self.dispatch, sending.action), label="approved-action"
            )
        except ActionRejected as exc:
            return self.store.save(
                replace(sending, status="failed", result_json=str(exc)),
                expected_version=sending.version,
            )
        except BaseException:
            self.store.save(replace(sending, status="unknown"), expected_version=sending.version)
            raise
        return self.store.save(
            replace(sending, status="succeeded", result_json=result),
            expected_version=sending.version,
        )
```

## Run this phase

### `examples/implementation/phase6.py`

```python
import asyncio
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from llmgrid.interfaces import Budget, RunContext
from llmgrid.interfaces.checkpoint import Action
from llmgrid.loops.approval import ApprovedAction
from llmgrid.loops.checkpoints import CheckpointConflict, SQLiteCheckpoints


async def main() -> None:
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
    print("Phase 6: request-bound approval, CAS, and uncertain-action recovery passed")


if __name__ == "__main__":
    asyncio.run(main())
```

```bash
.venv/bin/python examples/implementation/phase6.py
```

## Resume a saved run

```python
from llmgrid.interfaces import Budget, RunContext

saved = store.load("run-id")
if saved is None:
    raise ValueError("Run not found")
budget = Budget(20, 100)
budget.restore_used(saved.usage)
context = RunContext(saved.run_id, budget)
# Inside async code: outcome = await executor.run(context=context)
```

To reconcile `unknown`, query the external system using the recorded operation ID.
Persist a confirmed result with compare-and-swap. Leave it `unknown` when no reliable
status query exists. A new action requires a new operation ID and a new approval.

## Before moving on

- [ ] The approval/recovery example passes.
- [ ] Stale approvals and stale saves fail.
- [ ] Crash after external dispatch yields unknown and never sends the action again.

Next: [Phase 7](phase-7-examples.md).
