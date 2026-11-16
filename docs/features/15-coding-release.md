# 15 — Fix the seeded clamp bug, then run the release checks

> The capstone: a coding agent repairs a real bug under an independent verifier, then the release checks pass.

← [14](14-approval.md) · [All features](README.md)

## Why

This combines everything before it — budget, verified outcomes, protected files, tools — into the end-to-end goal of the project.

## Expects

**Behavior (end to end)**

- A scripted coding agent repairs `clamp` below its lower bound.
- An independent verifier reruns the check before `Completed`.
- A false "fixed" claim and a run that cannot pay for the edit do not report success.

**Rules**

- Only `candidate.py` is writable through the tools. The evaluator is not.
- The fixture is local and trusted. Do not call it a sandbox. Do not publish to PyPI.
- `Budget(5, 1)` cannot pay for the edit, so `ToolAgent.run` returns `Stopped` / `budget_exhausted`; `Budget.consume` still raises `BudgetExceededError`.
- Package code stays in the packages; the fixture, tools and verifier live in `examples`.
- The showcases in `docs/plan/example-*.md` are goals and checklists, not reference programs.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `examples/implementation/coding_support.py` | Fixture, typed tools, evaluator, and verifier. The unit test imports it. |

**Also update / keep green**

- The test inserts `examples/implementation` on `sys.path`, like `tests/integration/test_tool_agent_flow.py` does for `examples/tool_agent`.
- `pyproject.toml`: add `examples/implementation` to `mypy_path` so strict mypy can import `coding_support`.

## Acceptance

- [ ] `tests/integration/test_coding_repair.py` passes.
- [ ] The baseline `clamp` fails below the lower bound.
- [ ] The repaired candidate is `return max(low, min(value, high))`; evaluator bytes unchanged; outcome `Completed` with usage `(5, 6)`.
- [ ] A false "fixed" claim is `Stopped` / `no_progress` and does not edit the candidate.
- [ ] `Budget(5, 1)` stops with `budget_exhausted` before an edit.
- [ ] Writes outside `candidate.py` are rejected.
- [ ] `make check`, `make build`, `make smoke` pass. Nothing is published.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `tests/integration/test_coding_repair.py`

Expected unit test. `coding_support` is part of the work. Its body is not in this guide.

```python
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).parents[2] / "examples" / "implementation"))
from coding_support import BROKEN, FIXED, Fixture, TestsPass, decode_file, registry

from llmgrid.interfaces import (
    Budget,
    ChatResponse,
    InvalidArgumentsError,
    Message,
    RunContext,
    ToolCall,
)
from llmgrid.interfaces.loop import Completed, Stopped
from llmgrid.loops.tool_agent import ToolAgent
from llmgrid.network.scripted import ScriptedModel

ISSUE = "Fix clamp below the lower bound; preserve inside and above-bound behavior."


def call(index: int, name: str, arguments: dict) -> ChatResponse:
    return ChatResponse(
        Message("assistant", calls=(ToolCall(f"call-{index}", name, json.dumps(arguments)),)),
        "tool_calls",
    )


def repair_model() -> ScriptedModel:
    return ScriptedModel(
        [
            call(1, "read_file", {"path": "candidate.py"}),
            call(2, "run_tests", {}),
            call(3, "write_file", {"path": "candidate.py", "content": FIXED}),
            call(4, "run_tests", {}),
            ChatResponse(Message("assistant", "Fixed clamp; all five tests pass."), "stop"),
        ]
    )


class CodingRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_repair_false_claim_and_budget(self) -> None:
        with TemporaryDirectory() as tmp:
            fixture = Fixture.create(Path(tmp))
            original_evaluator = fixture.evaluator.read_bytes()
            context = RunContext("coding-success", Budget(5, 6))
            baseline = json.loads(
                await context.invoke(
                    fixture.test,
                    kind="tool",
                    label="baseline-tests",
                )
            )
            assert not baseline["passed"] and "test_below" in baseline["output"]
            outcome = await ToolAgent(repair_model(), registry(fixture), TestsPass(fixture)).run(
                ISSUE,
                context=context,
            )
            assert isinstance(outcome, Completed)
            assert fixture.candidate.read_text() == FIXED
            assert fixture.evaluator.read_bytes() == original_evaluator
            assert outcome.usage.model_calls == 5 and outcome.usage.tool_calls == 6
            print("Baseline: FAIL; repaired candidate: PASS (5 tests)")
            print(fixture.diff(), end="")
            print(outcome.value.text)
            print(
                f"Usage: {outcome.usage.model_calls} model calls, "
                f"{outcome.usage.tool_calls} tool calls (includes baseline and verification)"
            )
            for path in ("../evaluate.py", "/tmp/candidate.py", "tests.py"):
                try:
                    decode_file(json.dumps({"path": path, "content": ""}), write=True)
                except InvalidArgumentsError:
                    pass
                else:
                    raise AssertionError("Out-of-scope write accepted")

        with TemporaryDirectory() as tmp:
            fixture = Fixture.create(Path(tmp))
            liar = ScriptedModel(
                [ChatResponse(Message("assistant", "Fixed; tests pass."), "stop")] * 3
            )
            outcome = await ToolAgent(liar, registry(fixture), TestsPass(fixture)).run(
                ISSUE,
                context=RunContext("coding-false-claim", Budget(3, 3)),
            )
            assert isinstance(outcome, Stopped) and outcome.reason == "no_progress"
            assert fixture.candidate.read_text() == BROKEN
            print("False completion claim: rejected by independent tests")

        with TemporaryDirectory() as tmp:
            fixture = Fixture.create(Path(tmp))
            outcome = await ToolAgent(repair_model(), registry(fixture), TestsPass(fixture)).run(
                ISSUE,
                context=RunContext("coding-budget", Budget(5, 1)),
            )
            assert isinstance(outcome, Stopped) and outcome.reason == "budget_exhausted"
            assert fixture.candidate.read_text() == BROKEN


if __name__ == "__main__":
    unittest.main()
```
