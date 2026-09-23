"""Model specifications for LLM port.

A ModelSpec describes what one model can do — context size, how it calls tools,
which inputs it accepts, which sampling knobs it honors — so adapters branch on
declared facts instead of on provider or model names. ModelRegistry maps a
``(provider, model_name)`` pair onto the spec that describes it.
"""
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from fnmatch import fnmatchcase

from ..config import LOCAL_PROVIDERS, LLMConfig, Provider


class ToolSupport(StrEnum):
    """How a model accepts tool declarations and emits tool calls."""

    NONE = "none"  # no tool calling; requests with tools are rejected
    PROMPTED = "prompted"  # tools rendered into the prompt, calls recovered from text
    NATIVE = "native"  # structured tool-call field on the wire
    STRICT = "strict"  # native, plus schema-constrained decoding


class Modality(StrEnum):
    """A kind of content a model can read or produce."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


# Sampling parameters an LLMConfig can set, mapped to the config attribute and
# the value that means "not set".
_SAMPLING_PARAMS: dict[str, tuple[str, object]] = {
    "temperature": ("temperature", None),
    "top_p": ("top_p", None),
    "stop": ("stop", ()),
}


def _modalities(value: object, field_name: str) -> frozenset[Modality]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise ValueError(f"'{field_name}' must be a list of modalities, got {value!r}")
    try:
        return frozenset(Modality(v) for v in value)
    except ValueError as exc:
        raise ValueError(f"'{field_name}': {exc}") from None


def _positive_or_none(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"'{field_name}' must be a positive integer, got {value!r}")
    return value


@dataclass(frozen=True)
class ModelSpec:
    """What one model supports — the single source of truth adapters consult.

    ``name`` is a concrete model id or an ``fnmatch`` glob (``"llama3*"``) when
    the spec lives in a registry; ``provider=None`` matches any provider.
    Limits left as ``None`` are unknown and never enforced.
    """

    name: str
    provider: Provider | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    tools: ToolSupport = ToolSupport.NATIVE
    parallel_tool_calls: bool = False
    streaming: bool = True
    streaming_tool_calls: bool = True
    system_prompt: bool = True  # False: adapter folds the system turn into the first user turn
    structured_output: bool = False  # JSON-schema response format
    reasoning: bool = False  # emits a separate reasoning/thinking stream
    input_modalities: frozenset[Modality] = frozenset({Modality.TEXT})
    output_modalities: frozenset[Modality] = frozenset({Modality.TEXT})
    sampling: frozenset[str] = frozenset(_SAMPLING_PARAMS)
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("model spec requires a 'name'")
        unknown = self.sampling - _SAMPLING_PARAMS.keys()
        if unknown:
            raise ValueError(f"model '{self.name}' unknown sampling param(s): {sorted(unknown)}")
        if (
            self.context_window is not None
            and self.max_output_tokens is not None
            and self.max_output_tokens > self.context_window
        ):
            raise ValueError(
                f"model '{self.name}' max_output_tokens ({self.max_output_tokens}) "
                f"exceeds context_window ({self.context_window})"
            )
        if self.tools is ToolSupport.NONE and self.parallel_tool_calls:
            raise ValueError(f"model '{self.name}' cannot have parallel_tool_calls without tools")

    @classmethod
    def from_dict(cls, data: dict) -> "ModelSpec":
        """Parse a plain dict (e.g. one entry of a JSON/TOML model catalogue).

        Unknown keys are rejected so a typo never silently falls back to a default.
        """
        unknown = data.keys() - cls.__dataclass_fields__.keys()
        if unknown:
            raise ValueError(f"model spec has unknown field(s): {sorted(unknown)}")

        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"model spec missing a valid 'name': {data!r}")

        kwargs = dict(data)
        if kwargs.get("provider") is not None:
            kwargs["provider"] = Provider(kwargs["provider"])
        if "tools" in kwargs:
            kwargs["tools"] = ToolSupport(kwargs["tools"])
        for key in ("input_modalities", "output_modalities"):
            if key in kwargs:
                kwargs[key] = _modalities(kwargs[key], key)
        if "sampling" in kwargs:
            kwargs["sampling"] = frozenset(kwargs["sampling"])
        for key in ("context_window", "max_output_tokens"):
            if key in kwargs:
                kwargs[key] = _positive_or_none(kwargs[key], key)
        return cls(**kwargs)

    def to_dict(self) -> dict:
        """Inverse of :meth:`from_dict`, with sets rendered as sorted lists."""
        data = asdict(self)
        for key in ("input_modalities", "output_modalities", "sampling"):
            data[key] = sorted(data[key])
        return data

    @classmethod
    def default_for(cls, provider: Provider, model_name: str) -> "ModelSpec":
        """Conservative spec for a model nobody has described.

        Locally hosted models are assumed weak at tool calling: tools go into the
        prompt and calls are recovered from text. Hosted models are assumed native.
        """
        if provider in LOCAL_PROVIDERS:
            return cls(
                name=model_name,
                provider=provider,
                tools=ToolSupport.PROMPTED,
                streaming_tool_calls=False,
            )
        return cls(name=model_name, provider=provider)

    @property
    def supports_tools(self) -> bool:
        return self.tools is not ToolSupport.NONE

    @property
    def native_tools(self) -> bool:
        """True when tools go on the wire rather than into the prompt."""
        return self.tools in (ToolSupport.NATIVE, ToolSupport.STRICT)

    @property
    def constrained_decoding(self) -> bool:
        return self.tools is ToolSupport.STRICT

    def accepts(self, modality: Modality) -> bool:
        return modality in self.input_modalities

    def matches(self, provider: Provider, model_name: str) -> bool:
        """Whether this spec (possibly a glob) describes ``model_name`` on ``provider``."""
        if self.provider is not None and self.provider is not provider:
            return False
        return fnmatchcase(model_name, self.name)

    def config_error(self, config: LLMConfig) -> str | None:
        """First way ``config`` asks for something this model can't do, or None."""
        if self.max_output_tokens is not None and config.max_tokens > self.max_output_tokens:
            return (
                f"max_tokens={config.max_tokens} exceeds {self.name}'s "
                f"limit of {self.max_output_tokens}"
            )
        for param, (attr, unset) in _SAMPLING_PARAMS.items():
            if param not in self.sampling and getattr(config, attr) != unset:
                return f"{self.name} does not accept '{param}'"
        return None

    def tools_error(self, has_tools: bool) -> str | None:
        """A human message if tools were passed to a model that can't use them."""
        if has_tools and not self.supports_tools:
            return f"{self.name} does not support tool calling"
        return None


@dataclass
class ModelRegistry:
    """Ordered collection of specs; the most recently registered match wins.

    Register broad globs first and exact overrides after them.
    """

    specs: list[ModelSpec] = field(default_factory=list)

    @classmethod
    def from_dicts(cls, entries: Iterable[dict]) -> "ModelRegistry":
        return cls([ModelSpec.from_dict(entry) for entry in entries])

    def register(self, spec: ModelSpec) -> None:
        self.specs.append(spec)

    def find(self, provider: Provider, model_name: str) -> ModelSpec | None:
        """The registered spec for this model, or None if nothing matches."""
        for spec in reversed(self.specs):
            if spec.matches(provider, model_name):
                return spec
        return None

    def resolve(self, provider: Provider, model_name: str) -> ModelSpec:
        """The spec for this model, concretized to its real name and provider.

        Falls back to :meth:`ModelSpec.default_for` when nothing is registered.
        """
        spec = self.find(provider, model_name)
        if spec is None:
            return ModelSpec.default_for(provider, model_name)
        return replace(spec, name=model_name, provider=provider)

    def resolve_config(self, config: LLMConfig) -> ModelSpec:
        return self.resolve(config.provider, config.model_name)
