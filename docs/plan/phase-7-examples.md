# Phase 7: runnable framework showcases

[All phases](../composable-agent-platform-plan.md)

The basic coding recipe depends on Phases 1–3; the full example suite depends on
Phases 1–6. Build application recipes that make composition, verification, budgets,
parallel execution, replay, and durable actions visible through concrete outcomes.
Keep all cross-package composition in `examples/`; package dependency rules still apply.

The demonstration is deterministic and offline. `ScriptedModel` supplies the planned
tool calls; it does not discover the bug. The same tools and verifier can be injected
into a live model later. Advertise the offline run as a workflow demonstration, and
claim autonomous repair only after running the live version on held-out tasks.

## Example suite

Each linked guide supplies complete file bodies, run commands, expected output,
live-use wiring, deliberate failures, and acceptance checks. The checker extracts
all these guides and executes every showcase after the basic coding example.

| Guide | Visible result | Framework capabilities |
| --- | --- | --- |
| Basic coding agent (below) | Seeded bug repaired with verified diff | Typed tools, budgets, independent tests |
| [Expanded coding agent](example-coding-advanced.md) | Failed first patch, corrected patch, saved report, exact replay | Search, targeted edits, review, durable artifacts, recording |
| [Research brief](example-research.md) | Answer with inspectable source text | Retrieval, citation validation, artifacts |
| [Improvement loop](example-improvement.md) | Schedule improves from 20 to 12 minutes | Measured experiments, rollback, protected data, journal |
| [Approval and recovery](example-approval.md) | Publish once after approval and database reopening | Durable action state, usage restore, uncertain outcomes |
| [Provider portability](example-providers.md) | Same verified workflow through five adapters | Provider-shaped fixtures, normalization, shared verification |
| [Parallel investigation](example-parallel.md) | Three cited findings, streamed final report | Bounded workers, child contexts, shared budgets, SSE assembly |
| [Failure replay](example-replay.md) | Inspect and reproduce a no-progress coding run | Model/tool capture, exact replay, independent verification |

Implement the basic coding support file first, then the showcase files from each
guide. Research exports small fixture helpers used by the provider and parallel
examples; place every application file together in `examples/implementation/`.
The suite remains standard-library-only and requires no provider credentials.

## Starting point

| Action | Starting file / role |
| --- | --- |
| Keep | Phase 1 budgets/context and Phase 3 verified `ToolAgent` and outcome types |
| Reuse | `ScriptedModel`, `ToolBinding`, `ToolRegistry`, and standard-library unittest |
| Add | `examples/implementation/coding_support.py`: fixture, typed tools, evaluator, verifier |
| Add | `examples/implementation/phase7.py`: successful repair, false claim, budget stop, report |
| Update | Guide checker to include Phase 7; release checks now live in Phase 8 |
| Extend later | Recording/replay, critics, experiments, provider wiring, and action approval |

## What the demonstration proves

The issue is: “`clamp(value, low, high)` returns the wrong result below the lower
bound. Fix it while preserving behavior inside and above the interval.” The fixture
contains a one-line bug. The agent reads the source, reproduces the failure, writes
a replacement, reruns tests, and claims completion. A separate verifier reruns the
same evaluator before returning `Completed`.

The evaluator is application-owned and outside the file tool's editable surface.
Only `candidate.py` can be read or written through the tools. No arbitrary shell
command tool is exposed. The fixed test command has a timeout; cancellation kills
and reaps its child. Every dispatched tool, including verifier tests, consumes budget.
The final report contains an actual unified diff, test evidence, and usage counts.

This is a trusted local fixture, not an execution sandbox. Python flags and a temporary
directory do not isolate generated code: candidate code inherits the subprocess user's
filesystem and network permissions. Before executing untrusted live-model edits, replace
the evaluator with an isolated worker/container with no secrets or network, resource
limits, and a read-only evaluator mounted separately from the writable candidate.

## Implement these files

### `examples/implementation/coding_support.py`

Use a single allowlisted file to make the write boundary explicit. Tests are supplied
by the application, never by the model. Invalid arguments become tool errors; unexpected
I/O failures propagate. The tool decoder enforces the same constraints as the schema.

```python
from __future__ import annotations

import asyncio
import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from llmgrid.interfaces import InvalidArgumentsError, RunContext, ToolSpec
from llmgrid.interfaces.loop import AgentResult
from llmgrid.interfaces.verification import Verification
from llmgrid.tools import ToolBinding, ToolRegistry

BROKEN = "def clamp(value, low, high):\n    return min(value, high)\n"
FIXED = "def clamp(value, low, high):\n    return max(low, min(value, high))\n"
TEST_RUNNER = """import importlib.util
import sys
import unittest

spec = importlib.util.spec_from_file_location("candidate", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ClampTests(unittest.TestCase):
    def test_below(self):
        self.assertEqual(module.clamp(-2, 0, 10), 0)
    def test_inside(self):
        self.assertEqual(module.clamp(4, 0, 10), 4)
    def test_above(self):
        self.assertEqual(module.clamp(12, 0, 10), 10)
    def test_boundaries(self):
        self.assertEqual(module.clamp(0, 0, 10), 0)
        self.assertEqual(module.clamp(10, 0, 10), 10)
    def test_negative_interval(self):
        self.assertEqual(module.clamp(-9, -5, -1), -5)

unittest.main(argv=[sys.argv[0]], verbosity=2)
"""


@dataclass(frozen=True)
class FileInput:
    path: str
    content: str | None = None


def decode_file(raw: str, *, write: bool = False) -> FileInput:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise InvalidArgumentsError("Expected JSON") from exc
    keys = {"path", "content"} if write else {"path"}
    if not isinstance(value, dict) or set(value) != keys:
        raise InvalidArgumentsError("Unexpected file arguments")
    if value["path"] != "candidate.py":
        raise InvalidArgumentsError("Only candidate.py is available")
    content = value.get("content")
    if write and (not isinstance(content, str) or len(content.encode()) > 8192):
        raise InvalidArgumentsError("Expected source text of at most 8192 bytes")
    return FileInput(value["path"], content)


def decode_empty(raw: str) -> None:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise InvalidArgumentsError("Expected JSON") from exc
    if value != {}:
        raise InvalidArgumentsError("Expected an empty object")


@dataclass
class Fixture:
    candidate: Path
    evaluator: Path

    @classmethod
    def create(cls, root: Path) -> Fixture:
        workspace = root / "workspace"
        workspace.mkdir()
        candidate = workspace / "candidate.py"
        evaluator = root / "evaluate.py"
        candidate.write_text(BROKEN)
        evaluator.write_text(TEST_RUNNER)
        return cls(candidate, evaluator)

    def diff(self) -> str:
        return "".join(
            difflib.unified_diff(
                BROKEN.splitlines(keepends=True),
                self.candidate.read_text().splitlines(keepends=True),
                fromfile="a/candidate.py",
                tofile="b/candidate.py",
            )
        )

    async def test(self) -> str:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-B",
            str(self.evaluator),
            str(self.candidate),
            cwd=self.candidate.parent,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async with asyncio.timeout(5):
                output, _ = await process.communicate()
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        return json.dumps(
            {
                "passed": process.returncode == 0,
                "returncode": process.returncode,
                "output": re.sub(
                    r"Ran (\d+) tests in [0-9.]+s",
                    r"Ran \1 tests",
                    output.decode(errors="replace")[-8000:],
                ),
            }
        )


@dataclass
class ReadFile:
    fixture: Fixture

    async def invoke(self, value: FileInput, *, context: RunContext) -> str:
        context.check()
        return self.fixture.candidate.read_text()


@dataclass
class WriteFile:
    fixture: Fixture

    async def invoke(self, value: FileInput, *, context: RunContext) -> str:
        context.check()
        if value.content is None:
            raise ValueError("Missing source")
        self.fixture.candidate.write_text(value.content)
        return self.fixture.diff()


@dataclass
class RunTests:
    fixture: Fixture

    async def invoke(self, value: None, *, context: RunContext) -> str:
        context.check()
        return await self.fixture.test()


@dataclass
class TestsPass:
    fixture: Fixture

    async def verify(self, candidate: AgentResult, *, context: RunContext) -> Verification:
        raw = await context.invoke(self.fixture.test, kind="tool", label="verify-tests")
        report = json.loads(raw)
        return Verification(
            "passed" if report["passed"] else "failed",
            "deterministic",
            (report["output"],),
            "Independent tests failed. Read the failure and repair candidate.py."
            if not report["passed"]
            else "",
        )


def registry(fixture: Fixture) -> ToolRegistry:
    def file_schema(write: bool) -> str:
        properties = {"path": {"type": "string", "enum": ["candidate.py"]}}
        if write:
            properties["content"] = {"type": "string"}
        return json.dumps(
            {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            }
        )

    return ToolRegistry(
        [
            ToolBinding(
                ToolSpec("read_file", "Read candidate.py", file_schema(False)),
                ReadFile(fixture),
                decode_file,
                str,
            ),
            ToolBinding(
                ToolSpec("write_file", "Replace candidate.py source", file_schema(True)),
                WriteFile(fixture),
                lambda raw: decode_file(raw, write=True),
                str,
            ),
            ToolBinding(
                ToolSpec(
                    "run_tests",
                    "Run the fixed independent evaluator",
                    '{"type":"object","properties":{},"additionalProperties":false}',
                ),
                RunTests(fixture),
                decode_empty,
                str,
            ),
        ]
    )
```

The fixture removes unittest's variable elapsed-time footer so fresh verification
evidence is stable during replay; exit status and failure details stay intact.
The timeout bounds duration, and returned output is truncated. `communicate()` still
buffers output in memory; an untrusted runner needs streaming output caps as well as
process-tree cleanup. The fixture creates no descendants and emits bounded output.
Passing these five tests proves this task's specified behavior, not general correctness
or protection against malicious code that tries to deceive the evaluator.

### `examples/implementation/phase7.py`

Exercise the whole workflow plus two failures that distinguish verified completion
from a plausible final message. Keep every scenario in a fresh temporary workspace.

```python
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

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


async def main() -> None:
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
        liar = ScriptedModel([ChatResponse(Message("assistant", "Fixed; tests pass."), "stop")] * 3)
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
        print("Insufficient budget: stopped before editing")
    print("Phase 7: coding repair, independent verification, write boundary, and budgets passed")


if __name__ == "__main__":
    asyncio.run(main())
```

## Run this phase

After applying Phases 1–3 and the two files above:

```bash
.venv/bin/python examples/implementation/phase7.py
```

To validate the documented implementation without changing the library:

```bash
.venv/bin/python tools/check_implementation_guide.py --through 7
```

Expected output includes a failing baseline, the diff replacing `min(value, high)`
with `max(low, min(value, high))`, five passing tests, five model calls and six tool
calls, false-claim rejection, and a stop before editing when tool budget runs out.
The test command executed through the agent returns its actual output in tool messages;
the verifier independently reruns it rather than trusting that message or the final text.

## Extend to a live coding agent

1. Replace `repair_model()` with a Phase 2 adapter whose model supports tool calling.
   Inject its client at the application layer; retain the registry and verifier.
2. Supply `AgentInput` with explicit instructions about the issue, allowed files,
   available tools, and independent verification. Start with this fixture, then use
   a set of held-out bugs with a fixed evaluator. Record successes and failures.
3. Move candidate execution into an isolated evaluator before accepting untrusted
   edits. Expand file tools with normalized paths, symlink rejection, size limits,
   and application-controlled writable roots. Add read/search tools before a shell.
4. Report provider/model, issue, elapsed time, call counts, outcome, test evidence,
   and patch. Call-count limits are not hard token or currency limits.
5. Save the verified patch as an artifact. A stopped run may leave unverified edits;
   return that status clearly and never label those edits as a verified solution.

### Optional framework showcases

| Feature | Wiring and evidence required |
| --- | --- |
| Recording/replay | Wrap the model/tools with Phase 3 recorders. Replay in a workspace reconstructed to the recorded final state before independent verification: replayed writes return records and do not mutate files. Keep a separate assertion that the replayed outcome matches. |
| Critic | Reserve a Phase 4 critic budget before repair. Review the actual diff and evaluator evidence; retain independent tests as the completion gate. Show a vetoed patch as well as an accepted one. |
| Experiments | Use Phase 4 workspace snapshots and journals to compare bounded repair attempts. Preserve the highest-scoring verified candidate; do not select by the model's confidence. |
| Parallel checks | Use Phase 5 bounded parallel steps for independent checks on an immutable snapshot. Do not run concurrent writers against the same candidate. |
| Approval/recovery | Encode publishing the verified patch as a Phase 6 `Action`, including patch digest and destination. Pause for request-bound approval. Restoring that action does not restore a ToolAgent conversation; persist messages, workspace snapshot, and usage separately for mid-repair resume. |
| Multiple providers | Run the same issue, tools, and evaluator with separate fresh workspaces. Report comparable budgets and actual outcomes; avoid presenting the scripted run as a provider benchmark. |

These extensions are follow-up work, not capabilities exercised by the offline example.
Keep commit/PR publication out of the initial demo; add it only with an explicitly
configured destination, authenticated approval, and a dispatcher that handles uncertain
external outcomes as described in Phase 6.

## Package the showcase

Add an example README with the issue, one-command setup/run instructions, sample diff,
and a short terminal recording. Include a diagram of model → tools → tests → verifier
→ outcome. Make the successful run and false-claim rejection visible in the recording.
Document the fixture's trust assumptions and label offline/live modes clearly.

Run the complete linked suite before publishing recordings. The basic coding demo is
the quick introduction; use the expanded coding example for the flagship recording.
Show research and approval next, with the remaining examples available as focused
recipes. They compose existing phase APIs and require no new library abstractions.

## Before moving on

- [ ] The guide checker passes through Phase 7, including all seven linked showcases.
- [ ] Baseline fails and the repaired candidate passes independent tests.
- [ ] A completion claim without an edit never yields `Completed`.
- [ ] Tool and verifier dispatches are charged exactly once.
- [ ] Out-of-scope file paths fail and evaluator bytes stay unchanged.
- [ ] Insufficient budget stops before the write.
- [ ] Live-run tests additionally cover test timeout, cancellation, malformed source,
      output limits, worker isolation, and reconstruction of replay/resume state.
- [ ] README and recording distinguish implemented behavior from optional extensions.

Next: [Phase 8](phase-8-release.md).
