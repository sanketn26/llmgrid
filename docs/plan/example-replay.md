# Phase 7 example: record and replay a coding-agent failure

[Example phase](phase-7-examples.md) · [All phases](../composable-agent-platform-plan.md)

## Goal and starting point

Record a coding agent that runs the tests and then repeatedly claims it fixed the
bug without editing. Independent verification rejects the claims and the agent stops
for no progress. Print the failed tool output and recorded model claims, then replay
exactly those interactions without repeating recorded tool execution.

The verifier remains independent and reruns its tests during replay. The example
counts evaluator invocations to prove the distinction. Changed input must fail exact
replay matching instead of quietly borrowing a response from a different run.

| Action | Starting file / role |
| --- | --- |
| Reuse | Phase 3 model/tool recording and replay; Phase 7 coding fixture and independent tests |
| Add | `examples/implementation/showcase_replay.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

### `examples/implementation/showcase_replay.py`

```python
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from coding_support import Fixture, TestsPass, registry

from llmgrid.interfaces import Budget, ChatResponse, Message, RunContext, ToolCall
from llmgrid.interfaces.loop import Stopped
from llmgrid.loops.recording import RecordingModel, RecordingTools, ReplayModel, ReplayTools
from llmgrid.loops.tool_agent import ToolAgent
from llmgrid.network.scripted import ScriptedModel


class CountedFixture(Fixture):
    evaluations = 0

    async def test(self):
        self.evaluations += 1
        return await super().test()


async def main():
    with TemporaryDirectory() as tmp:
        fixture = CountedFixture.create(Path(tmp))
        tools = registry(fixture)
        model = RecordingModel(
            ScriptedModel(
                [
                    ChatResponse(
                        Message("assistant", calls=(ToolCall("test-1", "run_tests", "{}"),)),
                        "tool_calls",
                    ),
                    *[ChatResponse(Message("assistant", "Fixed; all tests pass."), "stop")] * 3,
                ]
            )
        )
        recorded_tools = RecordingTools(tools)
        prompt = "Fix clamp below its lower bound."
        original = await ToolAgent(model, recorded_tools, TestsPass(fixture)).run(
            prompt,
            context=RunContext("failure", Budget(4, 4)),
        )
        assert isinstance(original, Stopped) and original.reason == "no_progress"
        assert fixture.evaluations == 4  # one tool test and three verifier tests
        assert len(model.records) == 4 and len(recorded_tools.records) == 1
        print("Recorded failure:", original.reason)
        print("Tool output:", recorded_tools.records[0].result.content)
        print("Model claims:", [r.response.message.text for r in model.records[1:]])

        replay_model = ReplayModel(tuple(model.records), model.capabilities)
        replay_tools = ReplayTools(tools.specs, tuple(recorded_tools.records))
        repeated = await ToolAgent(replay_model, replay_tools, TestsPass(fixture)).run(
            prompt,
            context=RunContext("failure", Budget(4, 4)),
        )
        assert repeated == original
        assert replay_model.index == 4 and replay_tools.index == 1
        assert fixture.evaluations == 7  # only three independent verifier tests were rerun
        print("Exact replay matched; recorded run_tests was not executed again")
        try:
            await ToolAgent(
                ReplayModel(tuple(model.records), model.capabilities),
                ReplayTools(tools.specs, tuple(recorded_tools.records)),
                TestsPass(fixture),
            ).run("A different issue", context=RunContext("changed", Budget(4, 4)))
        except ValueError as exc:
            assert "differs" in str(exc)
            print("Changed prompt rejected:", exc)
        else:
            raise AssertionError("Replay accepted a changed request")


if __name__ == "__main__":
    asyncio.run(main())
```

## Run and inspect

After applying the required phases and this file:

```bash
.venv/bin/python examples/implementation/showcase_replay.py
```

The complete documented suite can be checked without modifying production packages:

```bash
.venv/bin/python tools/check_implementation_guide.py --through 7
```

The first run executes the evaluator four times. Replay consumes recorded model and
tool records and executes only the three independent verifier evaluations: the total
counter becomes seven. Both runs have the same no-progress outcome and logical budget
usage. This is replay-based debugging, not proof that rerunning a live model would
produce the same answers.

## Extend to live use

Keep capture opt-in and redact sensitive inputs before persistent storage. The Phase
3 records are in-memory dataclasses; durable recordings need a versioned serializer,
model capabilities, and tool specifications. Preserve the exact normalized requests.
For recorded writes, restore the candidate state explicitly before verification, since
ReplayTools returns saved results without writing files. For nondeterministic verifiers,
record their evidence separately and label evidence replay versus fresh verification.

## Before moving on

- [ ] Recorded test output shows the seeded bug.
- [ ] Three unsupported completion claims lead to no progress.
- [ ] Exact replay reproduces the full outcome and usage.
- [ ] Recorded tools have no repeated execution.
- [ ] Independent verification still runs during replay.
- [ ] Changed prompt rejects replay before consuming unrelated records.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
