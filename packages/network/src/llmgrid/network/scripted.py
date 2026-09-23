"""A `ChatModel` that replays prepared responses, for offline development."""

from __future__ import annotations

from collections.abc import Sequence

from llmgrid.interfaces import ChatRequest, ChatResponse, ModelCapabilities, RunContext

__all__ = ["ScriptedModel"]

_TOOL_CALLING = ModelCapabilities(tool_calling=True)


class ScriptedModel:
    """Returns `responses` in order and records every request it receives."""

    def __init__(
        self,
        responses: Sequence[ChatResponse],
        *,
        capabilities: ModelCapabilities = _TOOL_CALLING,
    ) -> None:
        self._responses = tuple(responses)
        self._capabilities = capabilities
        self.requests: list[ChatRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    async def generate(self, request: ChatRequest, *, context: RunContext) -> ChatResponse:
        context.check()
        if len(self.requests) >= len(self._responses):
            raise RuntimeError("ScriptedModel has no more responses")
        self.requests.append(request)
        return self._responses[len(self.requests) - 1]
