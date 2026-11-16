import unittest

from llmgrid.interfaces import Budget, BudgetExceededError, RunContext
from llmgrid.interfaces.execution import Counters, Limits


class NestedBudgetTests(unittest.TestCase):
    def test_child_cannot_spend_a_held_slice(self) -> None:
        root = Budget(3, 2)
        critic = root.allocate(Limits(1, 0))
        inner = root.child(Limits(2, 2))
        inner.consume("model", 2)
        with self.assertRaises(BudgetExceededError):
            inner.consume("model")
        self.assertEqual(root.used, Counters(2, 0))
        critic.consume("model")
        self.assertEqual(root.used, Counters(3, 0))

    def test_failed_consume_leaves_counters_unchanged(self) -> None:
        budget = Budget(max_model_calls=1, max_tool_calls=0)
        budget.consume("model")
        with self.assertRaises(BudgetExceededError):
            budget.consume("model")
        with self.assertRaises(BudgetExceededError):
            budget.consume("tool")
        self.assertEqual((budget.model_calls, budget.tool_calls), (1, 0))


class DeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_deadline_does_not_charge(self) -> None:
        import asyncio

        called = False

        async def operation() -> None:
            nonlocal called
            called = True

        context = RunContext("expired", Budget(), asyncio.get_running_loop().time() - 1)
        with self.assertRaises(TimeoutError):
            await context.invoke(operation, kind="model")
        self.assertFalse(called)
        self.assertEqual(context.budget.model_calls, 0)


if __name__ == "__main__":
    unittest.main()
