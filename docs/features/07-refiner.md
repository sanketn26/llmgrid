# 07 — Return a revision only when the critic approves it

> Draft → critique → revise, and only an approved draft ever leaves the loop.

← [06](06-resample.md) · [All features](README.md) · [08](08-route-and-errand.md) →

## Why

A refine loop that returns its last draft when the critic gives up silently ships something nobody approved.

## Expects

**Behavior (end to end)**

- A critic that asks for a better answer gets that answer back.
- A critic that never approves does not return the last draft.

**Rules**

- Unapproved drafts are never returned.
- Malformed critic JSON raises `ContractError`; it never counts as approval.

**Files to write.** This guide does not include their bodies.

| File | Purpose |
| --- | --- |
| `packages/loops/src/llmgrid/loops/refine.py` | `RefineStep`, model critic, model reviser. |

**Also update / keep green**

- `llmgrid.network` is not needed; the tests use an in-file scripted model.

## Acceptance

- [ ] `packages/loops/tests/test_refine.py` passes.
- [ ] An approved revision is returned.
- [ ] An unapproved draft is not.

Test code is below for reference; you do not need to read it to understand the feature.

## Unit tests

### `packages/loops/tests/test_refine.py`

Unit tests for an approved revision and a critic that never approves.

```python
"""Feature behaviour tests. Fakes depend only on llmgrid.interfaces."""

import unittest

from llmgrid.interfaces import (
    Budget,
    ChatRequest,
    ChatResponse,
    Message,
    ModelCapabilities,
    RunContext,
)
from llmgrid.interfaces.capabilities import ResamplingExhaustedError, Verdict
from llmgrid.loops.refine import Draft, ModelCritic, ModelReviser, RefineStep, Revision


class TextModel:
    """Replies with prepared texts and counts model calls through the budget."""

    def __init__(self, *texts: str) -> None:
        self._texts = list(texts)
        self.requests: list[ChatRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities()

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(Message("assistant", self._texts.pop(0)), "stop")


def make_context(model_calls: int = 8) -> RunContext:
    return RunContext("t", Budget(model_calls, 8))


class Echo:
    async def run(self, value: str, *, context: RunContext) -> str:
        return value


class Critic:
    """Denies drafts until one contains `good`."""

    async def run(self, value: Draft[str, str], *, context: RunContext) -> Verdict:
        return Verdict.allow() if "good" in value.output else Verdict.deny("not good yet")


class Doubter:
    async def run(self, value: Draft[str, str], *, context: RunContext) -> Verdict:
        return Verdict.allow() if value.output.endswith("!") else Verdict.deny("needs emphasis")


class Improve:
    def __init__(self) -> None:
        self.feedback: list[tuple[str, ...]] = []

    async def run(self, value: Revision[str, str], *, context: RunContext) -> str:
        self.feedback.append(value.feedback)
        return value.draft.output + " good!"


class RefineTests(unittest.IsolatedAsyncioTestCase):
    async def test_revises_until_critic_approves(self) -> None:
        reviser = Improve()
        refine = RefineStep(Echo(), (Critic(),), reviser)
        self.assertEqual(await refine.run("draft", context=make_context()), "draft good!")
        self.assertEqual(reviser.feedback, [("not good yet",)])

    async def test_approved_draft_is_not_revised(self) -> None:
        reviser = Improve()
        refine = RefineStep(Echo(), (Critic(),), reviser)
        self.assertEqual(await refine.run("good", context=make_context()), "good")
        self.assertEqual(reviser.feedback, [])

    async def test_every_critic_must_agree(self) -> None:
        refine = RefineStep(Echo(), (Critic(), Doubter()), Improve())
        self.assertEqual(await refine.run("x", context=make_context()), "x good!")
        reviser = Improve()
        both = RefineStep(Echo(), (Critic(), Doubter()), reviser)
        await both.run("x", context=make_context())
        self.assertEqual(reviser.feedback, [("not good yet", "needs emphasis")])

    async def test_unapproved_draft_is_never_returned(self) -> None:
        refine = RefineStep(Echo(), (Critic(),), Echo2(), max_rounds=2)
        with self.assertRaises(ResamplingExhaustedError) as raised:
            await refine.run("x", context=make_context())
        self.assertEqual(len(raised.exception.reasons), 3)

    async def test_model_critic_approves_only_on_exact_ok(self) -> None:
        draft = Draft("task", "answer")
        ok = await ModelCritic(TextModel(" OK\n")).run(draft, context=make_context())
        self.assertTrue(ok.allowed)
        chatty = await ModelCritic(TextModel("OK, but see below")).run(
            draft, context=make_context()
        )
        self.assertFalse(chatty.allowed)

    async def test_model_critic_and_reviser_round_trip(self) -> None:
        critic_model = TextModel("Missing detail", "OK")
        refine = RefineStep(
            Echo(),
            (ModelCritic(critic_model, stance="doubt"),),
            ModelReviser(TextModel("better answer")),
        )
        self.assertEqual(await refine.run("answer", context=make_context()), "better answer")
        self.assertIn("wrong", critic_model.requests[0].messages[0].text)


class Echo2:
    async def run(self, value: Revision[str, str], *, context: RunContext) -> str:
        return value.draft.output


if __name__ == "__main__":
    unittest.main()
```
