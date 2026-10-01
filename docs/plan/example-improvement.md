# Phase 7 example: measurable scheduling improvement

[Example phase](phase-7-examples.md) · [All phases](../composable-agent-platform-plan.md)

## Goal and starting point

Schedule jobs lasting 8, 7, and 5 minutes on two workers. Start with all jobs on one
worker (20 minutes), propose schedules, measure makespan, and preserve the best.
A worse proposal is rolled back. The loop maximizes scores, so score is negative
makespan. A fixed evaluator validates every assignment and reports worker loads.

Offline model responses are predetermined proposals; the example demonstrates the
optimization recipe, not autonomous discovery. A protected task file, durable round
journal, and explicit measurements make progress independently inspectable.

| Action | Starting file / role |
| --- | --- |
| Reuse | Phase 4 `ExperimentLoop`, `MemoryWorkspace`, journals, and Phase 3 `ModelStep` |
| Add | `examples/implementation/showcase_improvement.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

### `examples/implementation/showcase_improvement.py`

```python
import asyncio
import json
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from llmgrid.interfaces import Budget, ChatRequest, ChatResponse, Message, RunContext
from llmgrid.loops.experiments import ExperimentLoop, Journal, JournalSink, resume_round
from llmgrid.loops.model_step import ModelStep
from llmgrid.network.scripted import ScriptedModel
from llmgrid.tools.workspace import MemoryWorkspace

JOBS = (8, 7, 5)


def measure_assignment(assignment):
    if not isinstance(assignment, list) or len(assignment) != len(JOBS):
        raise ValueError("One worker per job required")
    if any(type(worker) is not int or worker not in (0, 1) for worker in assignment):
        raise ValueError("Worker must be 0 or 1")
    loads = [
        sum(t for t, w in zip(JOBS, assignment, strict=True) if w == worker) for worker in (0, 1)
    ]
    return -float(max(loads)), (f"loads={loads}; makespan={max(loads)}",)


@dataclass
class ProposeSchedule:
    workspace: MemoryWorkspace
    model: ScriptedModel

    async def run(self, index, *, context):
        current = self.workspace.files["schedule.json"].decode()
        reply = await ModelStep(self.model).run(
            ChatRequest(
                (
                    Message(
                        "user",
                        f"Jobs={JOBS}; workers=2; current={current}; round={index}. "
                        "Return JSON list.",
                    ),
                )
            ),
            context=context,
        )
        if reply.finish != "stop":
            raise ValueError("Incomplete proposal")
        assignment = json.loads(reply.message.text)
        measure_assignment(assignment)
        self.workspace.write("schedule.json", json.dumps(assignment).encode())


async def main():
    with TemporaryDirectory() as tmp:
        workspace = MemoryWorkspace(
            {
                "schedule.json": b"[0, 0, 0]",
                "task.json": json.dumps(JOBS).encode(),
            },
            frozenset({"task.json"}),
        )
        model = ScriptedModel(
            [
                ChatResponse(Message("assistant", value), "stop")
                for value in ("[0,1,0]", "[0,1,1]", "[0,0,1]")
            ]
        )
        context = RunContext("schedule", Budget(3, 4))
        journal = Journal(Path(tmp) / "rounds.jsonl")
        resume_round(journal, workspace, context, {"task": "schedule-v1"})
        context = replace(context, events=JournalSink(journal, context))

        async def measure(ctx):
            async def evaluate():
                return measure_assignment(json.loads(workspace.files["schedule.json"]))

            return await ctx.invoke(evaluate, kind="tool", label="measure-makespan")

        baseline, evidence = await measure(context)
        print("Baseline:", evidence[0])
        result = await ExperimentLoop(
            workspace,
            ProposeSchedule(workspace, model),
            measure,
            journal,
            3,
        ).run(baseline, context=context)
        assert result.best_score == -12
        assert [r.kept for r in result.rounds] == [True, True, False]
        assert json.loads(workspace.files["schedule.json"]) == [0, 1, 1]
        assert workspace.files["task.json"] == json.dumps(JOBS).encode()
        for row in result.rounds:
            print(f"Round {row.index}: {row.evidence[0]} {'kept' if row.kept else 'rolled back'}")
        print("Best: 12 minutes; assignment", workspace.files["schedule.json"].decode())
        assert context.budget.model_calls == 3 and context.budget.tool_calls == 4
        restored = RunContext("schedule", Budget(3, 4))
        resume_round(Journal(journal.path), workspace, restored, {"task": "schedule-v1"})
        assert restored.budget.used == context.budget.used
        try:
            measure_assignment([0, 2, 0])
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid worker accepted")
        print("Invalid assignment rejected; journal reload preserved usage")


if __name__ == "__main__":
    asyncio.run(main())
```

## Run and inspect

After applying the required phases and this file:

```bash
.venv/bin/python examples/implementation/showcase_improvement.py
```

The complete documented suite can be checked without modifying production packages:

```bash
.venv/bin/python tools/check_implementation_guide.py --through 7
```

Output progresses from 20 to 13 to 12 minutes and rejects a 15-minute proposal.
Print round evidence and the final assignment rather than an unsupported “improved”
claim. Reloading the journal restores usage; the in-memory workspace remains alive
in this fixture. Process restart additionally requires persisting its best snapshot.

## Extend to live use

Inject a live model into the proposer, include prior measurement evidence in its
prompt, and bound rounds and calls. Add more jobs and compare against a deterministic
scheduling baseline. Persist workspace snapshots for restart, and use Phase 4 critic
contexts if adding a reviewer. Do not claim optimality: this fixture proves improvement
and rollback, not a general optimizer or an exhaustive search.

## Before moving on

- [ ] Scores correspond to measured makespan, not model self-assessment.
- [ ] Worse proposals restore the previous best schedule.
- [ ] Invalid worker IDs fail validation.
- [ ] Protected task data stays unchanged.
- [ ] Reloaded journal usage matches all three proposals and four evaluations.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
