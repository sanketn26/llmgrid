# Example: approve, restart, and recover a publication

[Feature 15](../features/15-coding-release.md) · [Feature guide](../composable-agent-platform-plan.md)

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
| Reuse | Feature 14 `ApprovedAction` and `SQLiteCheckpoints`, and feature 01 `Budget.restore_used` |
| Add | `examples/implementation/showcase_approval.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

Write the file named in the starting-point table so the checklist below passes. This guide does not include a reference implementation.


## Run and inspect

After the features this showcase needs are in the packages:

```bash
.venv/bin/python examples/implementation/showcase_approval.py
```

The feature guide checker does not run this showcase. Run the command above and compare it with the checklist.

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
