"""Provider selection and client configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .errors import ConfigurationError

__all__ = ["Provider", "LLMConfig", "RetryPolicy"]


class Provider(StrEnum):
    """Supported provider adapters.

    Members fall into four groups: providers with a native wire format and
    vendor SDK, hosted services that speak the OpenAI format, cloud platforms
    that require their own credential chain, and locally hosted servers.
    """

    # Native wire formats.
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    SARVAM = "sarvam"

    # OpenAI wire format, hosted.
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    DEEPSEEK = "deepseek"
    TOGETHER = "together"
    FIREWORKS = "fireworks"
    XAI = "xai"
    MISTRAL = "mistral"

    # Cloud platforms with their own credential chain.
    BEDROCK = "bedrock"
    VERTEX = "vertex"

    # Locally hosted servers, OpenAI wire format.
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    VLLM = "vllm"
    LLAMACPP = "llamacpp"
    TGI = "tgi"


#: Default endpoint per provider. ``LLMConfig.base_url`` overrides these.
#: Providers whose endpoint is account- or region-specific are absent here and
#: listed in :data:`ENDPOINT_REQUIRED` instead.
DEFAULT_BASE_URLS: dict[Provider, str] = {
    Provider.ANTHROPIC: "https://api.anthropic.com/v1",
    Provider.GEMINI: "https://generativelanguage.googleapis.com/v1beta",
    Provider.SARVAM: "https://api.sarvam.ai/v1",
    Provider.OPENAI: "https://api.openai.com/v1",
    Provider.GROQ: "https://api.groq.com/openai/v1",
    Provider.OPENROUTER: "https://openrouter.ai/api/v1",
    Provider.DEEPSEEK: "https://api.deepseek.com/v1",
    Provider.TOGETHER: "https://api.together.xyz/v1",
    Provider.FIREWORKS: "https://api.fireworks.ai/inference/v1",
    Provider.XAI: "https://api.x.ai/v1",
    Provider.MISTRAL: "https://api.mistral.ai/v1",
    Provider.OLLAMA: "http://localhost:11434/v1",
    Provider.LMSTUDIO: "http://localhost:1234/v1",
    Provider.VLLM: "http://localhost:8000/v1",
    Provider.LLAMACPP: "http://localhost:8080/v1",
    Provider.TGI: "http://localhost:8080/v1",
}

#: Providers with no fixed endpoint. ``base_url`` is mandatory, and the value
#: here describes the shape the caller must supply.
ENDPOINT_REQUIRED: dict[Provider, str] = {
    Provider.AZURE_OPENAI: "https://<resource>.openai.azure.com/openai",
    Provider.BEDROCK: "https://bedrock-runtime.<region>.amazonaws.com",
    Provider.VERTEX: "https://<location>-aiplatform.googleapis.com/v1",
}

#: Environment variable consulted for each provider's credential. Providers
#: that resolve credentials elsewhere are absent.
DEFAULT_API_KEY_ENV: dict[Provider, str] = {
    Provider.ANTHROPIC: "ANTHROPIC_API_KEY",
    Provider.GEMINI: "GEMINI_API_KEY",
    Provider.SARVAM: "SARVAM_API_KEY",
    Provider.OPENAI: "OPENAI_API_KEY",
    Provider.AZURE_OPENAI: "AZURE_OPENAI_API_KEY",
    Provider.GROQ: "GROQ_API_KEY",
    Provider.OPENROUTER: "OPENROUTER_API_KEY",
    Provider.DEEPSEEK: "DEEPSEEK_API_KEY",
    Provider.TOGETHER: "TOGETHER_API_KEY",
    Provider.FIREWORKS: "FIREWORKS_API_KEY",
    Provider.XAI: "XAI_API_KEY",
    Provider.MISTRAL: "MISTRAL_API_KEY",
    Provider.OLLAMA: "OLLAMA_API_KEY",
    Provider.LMSTUDIO: "LMSTUDIO_API_KEY",
    Provider.VLLM: "VLLM_API_KEY",
    Provider.LLAMACPP: "LLAMACPP_API_KEY",
    Provider.TGI: "TGI_API_KEY",
}

#: Providers that run locally and therefore need no credential.
LOCAL_PROVIDERS = frozenset(
    {
        Provider.OLLAMA,
        Provider.LMSTUDIO,
        Provider.VLLM,
        Provider.LLAMACPP,
        Provider.TGI,
    }
)

#: Providers whose credentials come from a platform chain (AWS SigV4, Google
#: ADC) rather than an API key this library reads.
CREDENTIAL_CHAIN_PROVIDERS = frozenset({Provider.BEDROCK, Provider.VERTEX})

#: Providers for which a missing API key is not an error.
KEYLESS_PROVIDERS = LOCAL_PROVIDERS | CREDENTIAL_CHAIN_PROVIDERS


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retry behavior for transport and 429/5xx failures.

    Attributes:
        max_attempts: Total attempts including the first. ``1`` disables retries.
        initial_backoff: Seconds to wait before the second attempt.
        backoff_multiplier: Growth factor applied to each subsequent wait.
        max_backoff: Ceiling on any single wait.
        jitter: Fraction of each wait randomized, to spread retry storms.
    """

    max_attempts: int = 3
    initial_backoff: float = 0.5
    backoff_multiplier: float = 2.0
    max_backoff: float = 30.0
    jitter: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ConfigurationError("max_attempts must be at least 1")
        if not 0.0 <= self.jitter <= 1.0:
            raise ConfigurationError("jitter must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """Everything the client needs to talk to one model.

    Attributes:
        provider: Which adapter to use.
        model_name: Provider-specific model identifier.
        api_key: Credential. Falls back to the provider's environment variable.
        base_url: Endpoint override. Required for the providers listed in
            :data:`ENDPOINT_REQUIRED` and for non-default local ports.
        timeout: Per-request timeout in seconds.
        max_tokens: Cap on generated tokens.
        temperature: Sampling temperature, or ``None`` for the provider default.
        top_p: Nucleus sampling cutoff, or ``None`` for the provider default.
        stop: Stop sequences.
        retry: Transport-level retry policy.
        tool_repair_attempts: How many corrective round trips the conformance
            layer may spend fixing an invalid tool call before raising.
        recover_text_tool_calls: Parse tool calls out of plain text when the
            provider emitted none structurally.
        strict_tools: Reject tool calls that violate their declared schema
            instead of passing them through unvalidated.
        constrained_decoding: Ask the provider to enforce the tool schema during
            decoding where supported. Ignored by providers that cannot.
        extra_headers: Additional headers merged into every request.
        extra_body: Additional top-level fields merged into every request body.
    """

    provider: Provider
    model_name: str
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 60.0
    max_tokens: int = 4096
    temperature: float | None = None
    top_p: float | None = None
    stop: tuple[str, ...] = ()
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    tool_repair_attempts: int = 1
    recover_text_tool_calls: bool = True
    strict_tools: bool = True
    constrained_decoding: bool = False
    extra_headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_name:
            raise ConfigurationError("model_name is required")
        if self.max_tokens < 1:
            raise ConfigurationError("max_tokens must be positive")
        if self.timeout <= 0:
            raise ConfigurationError("timeout must be positive")
        if self.tool_repair_attempts < 0:
            raise ConfigurationError("tool_repair_attempts cannot be negative")

    @property
    def resolved_base_url(self) -> str:
        """Return the endpoint, falling back to the provider's default.

        Raises:
            ConfigurationError: The provider has no fixed endpoint and no
                ``base_url`` was supplied.
        """
        base = self.base_url or DEFAULT_BASE_URLS.get(self.provider)
        if not base:
            raise ConfigurationError(
                f"{self.provider} has no fixed endpoint: pass base_url="
                f"{ENDPOINT_REQUIRED[self.provider]!r}"
            )
        return base.rstrip("/")

    def resolve_api_key(self) -> str | None:
        """Return the credential, reading the environment when none was given.

        Local providers may legitimately have no credential, and platform
        providers resolve theirs through AWS or Google credential chains the
        adapter drives. Every other provider raises
        :class:`ConfigurationError` when no credential can be found.
        """
        env_var = DEFAULT_API_KEY_ENV.get(self.provider)
        key = self.api_key or (os.environ.get(env_var) if env_var else None)
        if not key and self.provider not in KEYLESS_PROVIDERS:
            raise ConfigurationError(
                f"no API key for {self.provider}: pass api_key= or set {env_var}"
            )
        return key
