"""Checked by mypy only. Each ignore must stay necessary (strict = warn_unused_ignores)."""

from llmgrid.interfaces import Budget, RunContext
from llmgrid.loops import AgentResult, SequenceStep, ToolAgent
from llmgrid.network import ScriptedModel
from llmgrid.tools import ToolRegistry


class ExtractText:
    async def run(self, value: AgentResult, *, context: RunContext) -> str:
        return value.text


agent = ToolAgent(ScriptedModel([]), ToolRegistry([]))
context = RunContext("typing", Budget())

ok = SequenceStep[str, AgentResult, str](agent, ExtractText())

# ToolAgent produces AgentResult, not str.
wrong_middle = SequenceStep[str, str, str](agent, ExtractText())  # type: ignore[arg-type]

# AgentResult cannot feed a step that takes str.
mismatched = SequenceStep(agent, agent)  # type: ignore[misc]
