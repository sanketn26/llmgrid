"""Public exceptions shared by every llmgrid package."""

from __future__ import annotations

__all__ = [
    "BudgetExceededError",
    "ContractError",
    "InvalidArgumentsError",
    "ModelStoppedError",
]


class ContractError(ValueError):
    """A value or response violates an llmgrid contract."""


class BudgetExceededError(RuntimeError):
    """A run tried to dispatch work beyond its budget."""


class InvalidArgumentsError(ValueError):
    """A tool decoder rejected the model's arguments."""


class ModelStoppedError(RuntimeError):
    """The model stopped without a final answer (truncation, refusal, round limit)."""
