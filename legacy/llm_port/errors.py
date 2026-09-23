"""Provider-neutral exception hierarchy.

Every adapter maps its transport and API failures onto these types so that
application code never has to branch on a provider-specific exception.
"""

from __future__ import annotations

__all__ = [
    "AuthenticationError",
    "ConfigurationError",
    "ContentFilterError",
    "ContextLengthError",
    "LLMPortError",
    "NotFoundError",
    "PermissionDeniedError",
    "ProviderError",
    "RateLimitError",
    "ResponseFormatError",
    "ServerError",
    "TimeoutError",
    "ToolCallError",
    "ToolCallRecoveryError",
    "ToolCallValidationError",
    "TransportError",
]


class LLMPortError(Exception):
    """Base class for every error raised by llm-port."""


class ConfigurationError(LLMPortError):
    """The client was constructed with an unusable configuration."""


class TransportError(LLMPortError):
    """The request never produced a usable HTTP response."""


class TimeoutError(TransportError):  # noqa: A001 - deliberate shadow, namespaced by module
    """The provider did not respond within the configured timeout."""


class ProviderError(LLMPortError):
    """The provider returned an error response.

    Attributes:
        status_code: HTTP status code, when one was received.
        provider: Provider identifier that produced the failure.
        body: Decoded response body, truncated by the adapter when large.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider: str | None = None,
        body: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.body = body


class AuthenticationError(ProviderError):
    """Credentials were missing, malformed, or rejected (401)."""


class PermissionDeniedError(ProviderError):
    """Credentials were valid but not entitled to the resource (403)."""


class NotFoundError(ProviderError):
    """The model or endpoint does not exist (404)."""


class RateLimitError(ProviderError):
    """The request was throttled (429).

    Attributes:
        retry_after: Seconds the provider asked the caller to wait, if given.
    """

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: object) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        self.retry_after = retry_after


class ServerError(ProviderError):
    """The provider failed internally (5xx)."""


class ContextLengthError(ProviderError):
    """The request exceeded the model's context window."""


class ContentFilterError(ProviderError):
    """The provider refused to complete the request on safety grounds."""


class ResponseFormatError(LLMPortError):
    """A response was received but could not be decoded into the port types."""


class ToolCallError(LLMPortError):
    """Base class for tool-call conformance failures."""


class ToolCallRecoveryError(ToolCallError):
    """A model emitted something tool-shaped that could not be recovered."""


class ToolCallValidationError(ToolCallError):
    """A recovered tool call did not satisfy its declared schema.

    Attributes:
        tool_name: Name of the tool the model attempted to call.
        violations: Human-readable schema violations, most specific first.
        arguments: The arguments as parsed, before validation failed.
    """

    def __init__(
        self,
        message: str,
        *,
        tool_name: str | None = None,
        violations: list[str] | None = None,
        arguments: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.violations = violations or []
        self.arguments = arguments or {}
