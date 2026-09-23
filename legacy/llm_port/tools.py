"""Tool declaration: one schema, reused for provider calls and validation."""

from __future__ import annotations

import inspect
import types as pytypes
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Self, Union, get_args, get_origin, get_type_hints

from .errors import ConfigurationError

__all__ = ["ToolSpec"]

_PY_TO_JSON: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type(annotation: Any) -> dict[str, Any]:
    """Map a Python annotation onto a minimal JSON Schema fragment."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    origin = get_origin(annotation)
    if origin in (Union, pytypes.UnionType):
        inner = [a for a in get_args(annotation) if a is not type(None)]
        if len(inner) == 1:
            return _json_type(inner[0])
        return {"anyOf": [_json_type(a) for a in inner]}
    if origin in (list, tuple, set):
        args = get_args(annotation)
        item = _json_type(args[0]) if args else {}
        return {"type": "array", "items": item} if item else {"type": "array"}
    if origin is dict:
        return {"type": "object"}
    if isinstance(annotation, type) and annotation in _PY_TO_JSON:
        return {"type": _PY_TO_JSON[annotation]}
    return {}


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool the model may call.

    The same instance produces every provider's wire format and drives
    conformance validation, so a tool is declared exactly once.

    Attributes:
        name: Tool name the model must emit.
        description: What the tool does; the model relies on this to choose it.
        parameters: JSON Schema object describing the arguments.
        strict: Request constrained decoding for this tool where supported.
    """

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    strict: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigurationError("tool name is required")
        if self.parameters.get("type", "object") != "object":
            raise ConfigurationError(
                f"tool {self.name!r}: top-level parameters must be an object schema"
            )

    # -- constructors -------------------------------------------------

    @classmethod
    def from_function_dict(cls, spec: dict[str, Any]) -> Self:
        """Build from the OpenAI ``{"type": "function", "function": {...}}`` shape.

        The bare inner ``{"name", "description", "parameters"}`` mapping is also
        accepted, since several providers document tools that way.
        """
        fn = spec.get("function", spec) if isinstance(spec, dict) else None
        if not isinstance(fn, dict) or "name" not in fn:
            raise ConfigurationError("function dict must contain a 'name'")
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        return cls(
            name=str(fn["name"]),
            description=str(fn.get("description") or ""),
            parameters=dict(params),
            strict=bool(fn.get("strict", False)),
        )

    @classmethod
    def from_callable(cls, fn: Callable[..., Any], *, strict: bool = False) -> Self:
        """Derive a spec from a function's signature, annotations, and docstring.

        Parameters without defaults become required. Annotations are mapped to
        JSON Schema types on a best-effort basis; anything unmappable is left
        untyped rather than guessed at.
        """
        sig = inspect.signature(fn)
        try:
            hints = get_type_hints(fn)
        except Exception:  # unresolvable forward refs should not break declaration
            hints = {}
        properties: dict[str, Any] = {}
        required: list[str] = []
        for pname, param in sig.parameters.items():
            if pname == "self" or param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            properties[pname] = _json_type(hints.get(pname, param.annotation))
            if param.default is inspect.Parameter.empty:
                required.append(pname)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        doc = inspect.getdoc(fn) or ""
        return cls(
            name=fn.__name__,
            description=doc.split("\n\n", 1)[0].strip(),
            parameters=schema,
            strict=strict,
        )

    # -- wire formats -------------------------------------------------

    def to_openai(self) -> dict[str, Any]:
        """Render the OpenAI / Ollama / LM Studio / Sarvam function shape."""
        fn: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }
        if self.strict:
            fn["strict"] = True
        return {"type": "function", "function": fn}

    def to_anthropic(self) -> dict[str, Any]:
        """Render the Anthropic tool shape."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_gemini(self) -> dict[str, Any]:
        """Render one Gemini ``functionDeclarations`` entry.

        Gemini rejects JSON Schema keywords it does not implement, so the
        schema is filtered rather than passed through.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": _gemini_schema(self.parameters),
        }


_GEMINI_KEYS = frozenset(
    {"type", "format", "description", "nullable", "enum", "items", "properties", "required"}
)


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Recursively drop schema keywords Gemini's OpenAPI subset rejects."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _GEMINI_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: _gemini_schema(v) if isinstance(v, dict) else v for k, v in value.items()}
        elif key == "items" and isinstance(value, dict):
            out[key] = _gemini_schema(value)
        elif key == "type" and isinstance(value, str):
            out[key] = value.upper()
        else:
            out[key] = value
    out.setdefault("type", "OBJECT")
    return out
