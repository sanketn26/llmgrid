# 11 — Review a draft, then measure three rounds

> Bounded review and measured improvement rounds that cannot touch the grader.

← [10](10-context.md) · [All features](README.md) · [12](12-mcp-tool.md) →

## Why

Self-improvement loops are only trustworthy if the thing measuring progress is protected and the critic's budget cannot be eaten by the proposer.

## Expects

**Behavior (end to end)**

- A one-round review that never accepts is `Stopped`, not a success.
- Three experiment rounds raise a candidate score to 3 and leave the protected `grader` file unchanged.
- A tree records four nodes.

**Rules**

- Critic budget: `context.budget.allocate(Limits(2, 0))`. Proposer budget: `context.budget.child(Limits(...))`.
- Do not add `RunContext.child` or an `allocate=True` argument.
- Protected workspace paths cannot be written.
- `AgentTool` takes its slice from `budget.child(limits)` on a new `RunContext`.
- `binding.py` and `agent_tool.py` are not imported by these tests.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/loops/src/llmgrid/loops/review.py` | Draft, evaluate, verify. The round limit returns `Stopped`. |
| `packages/interfaces/src/llmgrid/interfaces/workspace.py` | Workspace protocol. |
| `packages/tools/src/llmgrid/tools/workspace.py` | In-memory workspace with protected paths. |
| `packages/tools/src/llmgrid/tools/binding.py` | Typed invocation failures for nested agents. |
| `packages/loops/src/llmgrid/loops/agent_tool.py` | One agent exposed as one tool. |
| `packages/loops/src/llmgrid/loops/experiments.py` | Measured rounds and a journal. |
| `packages/loops/src/llmgrid/loops/critic.py` | Critic step, paid from a budget the caller already allocated. |
| `packages/loops/src/llmgrid/loops/tree.py` | Bounded tree search on the same workspace. |

## Acceptance

- [ ] `packages/loops/tests/test_review.py` and `packages/loops/tests/test_experiment.py` pass.
- [ ] A one-round review that never accepts is `Stopped` with `max_iterations`.
- [ ] Three experiment rounds reach score 3 and leave `grader` unchanged.
- [ ] The tree has four nodes.
- [ ] The critic slice is `Budget.allocate`; the proposer slice is `Budget.child`.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_review.py`

Unit test that a rejected draft is not a completed review.

```python
import unittest

from llmgrid.interfaces import Budget, RunContext
from llmgrid.interfaces.loop import Stopped
from llmgrid.interfaces.verification import Verification
from llmgrid.loops.review import DraftAndReview, DraftInput, Evaluation


class Drafter:
    async def run(self, value: DraftInput, *, context: RunContext) -> str:
        return "draft"


class Reject:
    async def evaluate(self, draft: str, *, context: RunContext) -> Evaluation:
        return Evaluation(False, "no")


class NeverPass:
    async def verify(self, candidate: str, *, context: RunContext) -> Verification:
        return Verification("failed", "deterministic", feedback="still wrong")


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_limit_is_not_success(self) -> None:
        step = DraftAndReview(Drafter(), Reject(), NeverPass(), max_rounds=1)
        outcome = await step.run("goal", context=RunContext("review", Budget(2, 0)))
        self.assertIsInstance(outcome, Stopped)
        assert isinstance(outcome, Stopped)
        self.assertEqual(outcome.reason, "max_iterations")


if __name__ == "__main__":
    unittest.main()
```

### `packages/loops/tests/test_experiment.py`

Expected unit test for the measured rounds and the four-node tree.

```python
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from llmgrid.interfaces import Budget, BudgetExceededError, RunContext
from llmgrid.interfaces.execution import Limits
from llmgrid.loops.experiments import ExperimentLoop, Journal, resume_round
from llmgrid.loops.tree import Node, TreeSearch
from llmgrid.tools.workspace import MemoryWorkspace


class ExperimentTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_rounds_leave_the_grader_untouched(self) -> None:
        workspace = MemoryWorkspace({"candidate": b"0", "grader": b"fixed"}, frozenset({"grader"}))

        class Proposer:
            async def run(self, index: int, *, context: RunContext) -> None:
                context.check()
                workspace.write("candidate", str(index + 1).encode())

        async def measure(context: RunContext) -> tuple[float, tuple[str, ...]]:
            context.check()
            return float(workspace.files["candidate"]), ("deterministic score",)

        with TemporaryDirectory() as tmp:
            journal = Journal(Path(tmp) / "rounds.jsonl")
            context = RunContext("composition", Budget(4, 4))
            resume_round(journal, workspace, RunContext("rounds", Budget()), {"version": 1})
            result = await ExperimentLoop(workspace, Proposer(), measure, journal, 3).run(
                0, context=context
            )
            self.assertEqual(result.best_score, 3)
            self.assertEqual(workspace.files["grader"], b"fixed")

            async def expand(parent: Node, *, context: RunContext) -> tuple[float, tuple[str, ...]]:
                context.check()
                workspace.write("candidate", str(parent.id + 10).encode())
                return parent.score + 1, ("branch measurement",)

            nodes = await TreeSearch(
                workspace, expand, Journal(Path(tmp) / "tree.jsonl"), max_nodes=4
            ).run(0, context=context)
            self.assertEqual(len(nodes), 4)

    def test_critic_slice_uses_allocate_and_child(self) -> None:
        root = Budget(4, 4)
        critic = root.allocate(Limits(2, 0))
        proposer = root.child(Limits(2, 4))
        proposer.consume("model", 2)
        with self.assertRaises(BudgetExceededError):
            proposer.consume("model")
        critic.consume("model", 2)
        self.assertEqual((root.model_calls, root.tool_calls), (4, 0))


if __name__ == "__main__":
    unittest.main()
```
