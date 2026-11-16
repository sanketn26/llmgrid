# Example: iterative coding repair, review, artifacts, and replay

[Feature 15](../features/15-coding-release.md) · [Feature guide](../composable-agent-platform-plan.md)

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
| Reuse | Feature 15 coding fixture; feature 03 recording and replay; feature 10 artifacts |
| Add | `examples/implementation/showcase_coding_advanced.py`: application composition and offline fixtures |
| Keep | Package dependency rules; cross-package wiring stays in this application |

## Implement this file

Write the file named in the starting-point table so the checklist below passes. This guide does not include a reference implementation.


## Run and inspect

After the features this showcase needs are in the packages:

```bash
.venv/bin/python examples/implementation/showcase_coding_advanced.py
```

The feature guide checker does not run this showcase. Run the command above and compare it with the checklist.

The output identifies the first failed patch, prints the final diff, reports nine
model calls and ten tool calls, saves a durable report, and confirms exact replay.
Additional assertions reject an unmatched edit and a functionally passing but out-of-scope
source change. The AST review is a fixture-specific scope check, not a security sandbox.
No commit or PR is created.

## Extend to live use

Replace the scripted model with a feature 04 adapter, supply an AgentInput describing
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
