# Phase 7 example: iterative coding repair, review, artifacts, and replay

[Example phase](phase-7-examples.md) · [All phases](../composable-agent-platform-plan.md)

## Goal and starting point

Expand the basic coding agent into a visible investigate → edit → test → correct
workflow. Add literal source search and a targeted replacement tool that refuses
ambiguous edits. The first attempted fix handles the lower bound but breaks the upper
bound. The agent sees the failing tests, locates its edit, and replaces it with a
correct repair. The completion gate combines independent tests with a narrow
application-owned structural review.

Save a JSON report containing the diff, verification, usage, and final source through
`FileArtifacts`. Reopen the artifact store and inspect the saved result. Record the
model and tools and replay with the final candidate reconstructed; recorded edits are
not repeated. Every scripted response is a fixture. This recipe shows iterative repair
and debugging; a live model must actually choose its edits before claiming autonomous
coding behavior.

| Action | Starting file / role |
| --- | --- |
| Reuse | Phase 7 coding fixture; Phase 3 recording/replay; Phase 4 artifacts |
| Add | `examples/implementation/showcase_coding_advanced.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

### `examples/implementation/showcase_coding_advanced.py`

```python
import ast
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from coding_support import FIXED, Fixture, TestsPass, registry

from llmgrid.context.artifacts import FileArtifacts
from llmgrid.interfaces import (
    Budget,
    ChatResponse,
    InvalidArgumentsError,
    Message,
    RunContext,
    ToolCall,
    ToolSpec,
)
from llmgrid.interfaces.loop import Completed
from llmgrid.interfaces.verification import Verification
from llmgrid.loops.recording import RecordingModel, RecordingTools, ReplayModel, ReplayTools
from llmgrid.loops.tool_agent import ToolAgent
from llmgrid.network.scripted import ScriptedModel
from llmgrid.tools import ToolBinding, ToolRegistry


@dataclass(frozen=True)
class EditInput:
    old: str
    new: str


def decode_object(raw, keys):
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise InvalidArgumentsError("Expected JSON") from exc
    if not isinstance(value, dict) or set(value) != set(keys):
        raise InvalidArgumentsError("Unexpected arguments")
    if any(not isinstance(value[key], str) or len(value[key].encode()) > 8192 for key in keys):
        raise InvalidArgumentsError("Expected strings of at most 8192 bytes")
    return value


def decode_search(raw):
    value = decode_object(raw, ("query",))
    if not value["query"]:
        raise InvalidArgumentsError("Query must not be empty")
    return value["query"]


def decode_edit(raw):
    value = decode_object(raw, ("old", "new"))
    if not value["old"]:
        raise InvalidArgumentsError("Old source must not be empty")
    return EditInput(value["old"], value["new"])


@dataclass
class SearchSource:
    fixture: Fixture

    async def invoke(self, query, *, context):
        context.check()
        return json.dumps(
            [
                {"line": index, "text": line}
                for index, line in enumerate(self.fixture.candidate.read_text().splitlines(), 1)
                if query in line
            ][:20]
        )


@dataclass
class EditSource:
    fixture: Fixture
    writes: int = 0

    async def invoke(self, value, *, context):
        context.check()
        source = self.fixture.candidate.read_text()
        if source.count(value.old) != 1:
            raise InvalidArgumentsError("Edit must match exactly once")
        replacement = source.replace(value.old, value.new, 1)
        if len(replacement.encode()) > 8192:
            raise InvalidArgumentsError("Result exceeds source size limit")
        self.fixture.candidate.write_text(replacement)
        self.writes += 1
        return self.fixture.diff()


def schema(keys):
    return json.dumps(
        {
            "type": "object",
            "properties": {key: {"type": "string"} for key in keys},
            "required": list(keys),
            "additionalProperties": False,
        }
    )


def advanced_registry(fixture):
    basic = registry(fixture)
    # Rebind only read_file and run_tests; this example deliberately omits whole-file writes.
    # Registry is private internally, so compose explicit bindings for these operations.
    from coding_support import ReadFile, RunTests, decode_empty, decode_file

    edit = EditSource(fixture)
    specs = {spec.name: spec for spec in basic.specs}
    tools = ToolRegistry(
        [
            ToolBinding(specs["read_file"], ReadFile(fixture), decode_file, str),
            ToolBinding(specs["run_tests"], RunTests(fixture), decode_empty, str),
            ToolBinding(
                ToolSpec("search_source", "Find literal source lines", schema(("query",))),
                SearchSource(fixture),
                decode_search,
                str,
            ),
            ToolBinding(
                ToolSpec(
                    "edit_source", "Replace exactly one source occurrence", schema(("old", "new"))
                ),
                edit,
                decode_edit,
                str,
            ),
        ]
    )
    return tools, edit


@dataclass
class ReviewedTests:
    fixture: Fixture

    async def verify(self, candidate, *, context):
        tested = await TestsPass(self.fixture).verify(candidate, context=context)
        if tested.verdict != "passed":
            return tested
        tree = ast.parse(self.fixture.candidate.read_text())
        # This intentionally narrow fixture review accepts a single pure clamp function.
        allowed = (
            ast.Module,
            ast.FunctionDef,
            ast.arguments,
            ast.arg,
            ast.Return,
            ast.Call,
            ast.Name,
            ast.Load,
        )
        pure = (
            len(tree.body) == 1
            and isinstance(tree.body[0], ast.FunctionDef)
            and tree.body[0].name == "clamp"
            and all(isinstance(node, allowed) for node in ast.walk(tree))
            and all(
                isinstance(node.func, ast.Name) and node.func.id in ("min", "max")
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
            )
        )
        return Verification(
            "passed" if pure else "failed",
            "deterministic",
            (*tested.evidence, "Task-specific AST review: " + str(pure)),
            "Keep only a pure clamp function using min/max" if not pure else "",
        )


def response(index, name, arguments):
    return ChatResponse(
        Message("assistant", calls=(ToolCall(f"coding-{index}", name, json.dumps(arguments)),)),
        "tool_calls",
    )


def iterative_model():
    return ScriptedModel(
        [
            response(1, "read_file", {"path": "candidate.py"}),
            response(2, "search_source", {"query": "return"}),
            response(3, "run_tests", {}),
            response(4, "edit_source", {"old": "min(value, high)", "new": "max(low, value)"}),
            response(5, "run_tests", {}),
            response(6, "search_source", {"query": "max(low, value)"}),
            response(
                7, "edit_source", {"old": "max(low, value)", "new": "max(low, min(value, high))"}
            ),
            response(8, "run_tests", {}),
            ChatResponse(
                Message("assistant", "Repaired both bounds; tests and review pass."), "stop"
            ),
        ]
    )


async def main():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        fixture = Fixture.create(root)
        tools, edit = advanced_registry(fixture)
        model = RecordingModel(iterative_model())
        recorded = RecordingTools(tools)
        context = RunContext("iterative-coding", Budget(9, 10))
        baseline = json.loads(await context.invoke(fixture.test, kind="tool", label="baseline"))
        assert not baseline["passed"]
        prompt = "Repair clamp; use search and targeted edits, then run tests."
        result = await ToolAgent(model, recorded, ReviewedTests(fixture), max_rounds=10).run(
            prompt,
            context=context,
        )
        assert isinstance(result, Completed) and fixture.candidate.read_text() == FIXED
        assert edit.writes == 2 and len(recorded.records) == 8
        trial_tests = json.loads(recorded.records[4].result.content)
        assert not trial_tests["passed"] and "test_above" in trial_tests["output"]
        assert result.usage.model_calls == 9 and result.usage.tool_calls == 10
        report = {
            "schema": 1,
            "issue": prompt,
            "outcome": "Completed",
            "diff": fixture.diff(),
            "source": fixture.candidate.read_text(),
            "usage": asdict(result.usage),
            "verification": asdict(result.verification),
        }
        report = json.loads(json.dumps(report))  # normalize tuple evidence to JSON arrays
        artifacts = FileArtifacts(context.run_id, root / "artifacts")
        ref = artifacts.put(json.dumps(report, indent=2))
        restored_store = FileArtifacts(context.run_id, root / "artifacts")
        assert json.loads(restored_store.read(ref, limit=8000)) == report
        print("First repair: rejected by upper-bound test; second repair: passed")
        print(fixture.diff(), end="")
        print("Reviewed result artifact:", ref.digest)
        print("Usage:", report["usage"])

        # Replay returns saved edit results, so reconstruct final source before verification.
        fixture.candidate.write_text(report["source"])
        replay_context = RunContext("iterative-coding", Budget(9, 10))
        replay_context.budget.consume("tool")  # same baseline accounting as the recorded run
        repeated = await ToolAgent(
            ReplayModel(tuple(model.records), model.capabilities),
            ReplayTools(tools.specs, tuple(recorded.records)),
            ReviewedTests(fixture),
            max_rounds=10,
        ).run(prompt, context=replay_context)
        assert repeated == result and edit.writes == 2
        print("Replay matched; no recorded edits executed again")

        try:
            await edit.invoke(
                EditInput("absent", "replacement"), context=RunContext("edit-check", Budget())
            )
        except InvalidArgumentsError:
            pass
        else:
            raise AssertionError("Unmatched edit accepted")
        assert fixture.candidate.read_text() == FIXED
        # Functional tests alone allow unrelated executable statements; review must reject them.
        fixture.candidate.write_text(FIXED + "unrelated = 1\n")
        rejected = await ReviewedTests(fixture).verify(
            result.value,
            context=RunContext("review-check", Budget(0, 1)),
        )
        assert rejected.verdict == "failed"
        print("Unmatched edit and unrelated source change rejected")


if __name__ == "__main__":
    asyncio.run(main())
```

## Run and inspect

After applying the required phases and this file:

```bash
.venv/bin/python examples/implementation/showcase_coding_advanced.py
```

The complete documented suite can be checked without modifying production packages:

```bash
.venv/bin/python tools/check_implementation_guide.py --through 7
```

The output identifies the first failed patch, prints the final diff, reports nine
model calls and ten tool calls, saves a durable report, and confirms exact replay.
Additional assertions reject an unmatched edit and a functionally passing but out-of-scope
source change. The AST review is a fixture-specific scope check, not a security sandbox.
No commit or PR is created.

## Extend to live use

Replace the scripted model with a Phase 2 adapter, supply an AgentInput describing
allowed files and tools, and retain deterministic completion verification. Generalize
search to a repository index and targeted edits to normalized allowlisted paths. Keep
independent evaluator files outside the writable root. Replace fixture AST review with
project checks and an injected reviewer whose budget is reserved before repair. Execute
untrusted candidate code only in an isolated worker. Persist messages, workspace state,
settings and consumed usage to support mid-run resume; a result artifact alone does not
resume an unfinished agent. Gate publication through the approval showcase.

## Before moving on

- [ ] Source search returns line numbers and matching text.
- [ ] Targeted edits require exactly one occurrence and enforce size limits.
- [ ] First repair fails a real upper-bound test; second repair passes.
- [ ] Independent tests and structural review gate Completed.
- [ ] Saved artifact reloads with identical patch, evidence, source, and usage.
- [ ] Replay reconstructs candidate state and repeats no recorded edits.
- [ ] Unmatched edits and unrelated changes are rejected.

For the public showcase, include the command, sample output, a short recording,
and the deliberate failure case. Label fixtures and live runs separately. Record
actual provider/model and usage whenever a live model is involved.
