"""Composition primitives."""

from __future__ import annotations

from dataclasses import dataclass

from llmgrid.interfaces import RunContext, Step

__all__ = ["SequenceStep"]


@dataclass(frozen=True)
class SequenceStep[A, B, C]:
    """Runs `first`, then feeds its output to `second`."""

    first: Step[A, B]
    second: Step[B, C]

    async def run(self, value: A, *, context: RunContext) -> C:
        # Composition checks the deadline; leaf dispatches own timeout scopes.
        context.check()
        intermediate = await self.first.run(value, context=context)
        context.check()
        return await self.second.run(intermediate, context=context)
