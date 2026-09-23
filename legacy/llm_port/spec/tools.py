"""Tool and argument specifications for LLM port.

Defines ArgSpec and ToolSpec dataclasses for representing tool arguments and tools,
including type checks, enum validation, and JSON-Schema integration.
"""
from collections.abc import Sequence
from dataclasses import dataclass, field

# JSON-Schema primitive type -> (isinstance check, human label for errors).
_TYPE_CHECKS: dict[str, tuple[type | tuple[type, ...], str]] = {
    "string": (str, "a string"),
    "integer": (int, "an integer"),
    "number": ((int, float), "a number"),
    "boolean": (bool, "a boolean"),
    "object": (dict, "an object"),
}

# Item-type label matching the legacy "list of str" phrasing.
_ITEM_LABEL = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}

def _is_array_of(value: object, item_type: str) -> bool:
    if not isinstance(value, list):
        return False
    py_type = _TYPE_CHECKS.get(item_type, (object, ""))[0]
    return all(isinstance(item, py_type) for item in value)


@dataclass(frozen=True)
class ArgSpec:
    """One top-level argument of a tool: its declared type, enum, and whether
    it is required. Derived from the tool's JSON-Schema ``properties`` entry."""

    name: str
    type: str = ""
    description: str = ""
    required: bool = False
    enum: tuple = ()
    item_type: str | None = None  # element type when ``type == "array"``

    def type_error(self, value: object) -> str | None:
        """A human message if ``value`` violates this arg's type/enum, else None."""
        # array check
        if self.type == "array":
            item = self.item_type or "string"
            if not _is_array_of(value, item):
                return f"argument '{self.name}' must be a list of {_ITEM_LABEL.get(item, item)}"
        # primitive type check
        elif self.type in _TYPE_CHECKS:
            py_type, label = _TYPE_CHECKS[self.type]
            # bool is an int subclass — reject it where a number is asked.
            if not isinstance(value, py_type) or (
                self.type in ("integer", "number") and isinstance(value, bool)
            ):
                return f"argument '{self.name}' must be {label}"
        # enum check
        if self.enum and value not in self.enum:
            allowed = ", ".join(repr(v) for v in self.enum)
            return f"argument '{self.name}' must be one of: {allowed}"
        return None

@dataclass(frozen=True)
class ToolSpec:
    """A tool definition as a typed object — the single source of truth.

    ``parameters`` keeps the full (possibly deeply nested) JSON-Schema so
    ``to_wire`` reproduces the exact provider schema; ``args`` is the flattened
    top-level view used for validation and instruction rendering.
    """

    name: str
    description: str = ""
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    args: tuple[ArgSpec, ...] = ()
    guidance: str = ""

    @classmethod
    def from_function_dict(cls, definition: dict) -> "ToolSpec":
        """Parse an OpenAI-style ``{"type": "function", "function": {...}}`` dict.

        Accepts either the full envelope or a bare ``function`` body. The
        non-standard ``guidance`` field is captured here and deliberately *not*
        re-emitted by :meth:`to_wire`.
        """

        if "type" in definition and definition["type"] != "function":
            raise ValueError("Invalid function definition: 'type' must be 'function'")

        fn = definition.get("function", definition)

        name = fn.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"tool definition missing a valid 'name': {fn!r}")

        params = fn.get("parameters") or {"type": "object", "properties": {}}
        if params.get("type", "object") != "object":
            raise ValueError(
                f"tool '{name}' parameters must be a JSON-Schema object, got {params.get('type')!r}"
            )

        required = set(params.get("required", ()) or ())
        props = params.get("properties", {}) or {}

        unknown_required = required - props.keys()
        if unknown_required:
            raise ValueError(
                f"tool '{name}' required field(s) not in properties: {sorted(unknown_required)}"
            )

        args = tuple(
            ArgSpec(
                name=field_name,
                type=spec.get("type", "") or "",
                description=spec.get("description", "") or "",
                required=field_name in required,
                enum=tuple(spec.get("enum") or ()),
                item_type=(spec.get("items") or {}).get("type"),
            )
            for field_name, spec in props.items()
        )
        return cls(
            name=name,
            description=fn.get("description", "") or "",
            parameters=params,
            args=args,
            guidance=fn.get("guidance", "") or "",
        )

    def to_wire(self) -> dict:
        """Render the standard provider function schema (no ``guidance``)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def missing_required(self, args: dict) -> frozenset[str]:
        """Required arg names absent from ``args``."""
        return frozenset(a.name for a in self.args if a.required and a.name not in args)

    def argument_error(self, args: dict) -> str | None:
        """First type/enum violation among the declared args, or None."""
        by_name = {a.name: a for a in self.args}
        for field_name, value in args.items():
            spec = by_name.get(field_name)
            if spec is None:
                continue  # unknown fields are not type-checked (lenient by design)
            error = spec.type_error(value)
            if error:
                return error
        return None

    def format_instructions(self) -> str:
        """One-tool format block for prompt part 3 (weak/no-native-tool models)."""
        line = f"- {self.name}: {self.description}".rstrip()
        if not self.args:
            return line
        rendered = []
        for a in self.args:
            tag = "required" if a.required else "optional"
            kind = a.type or "any"
            choices = f", one of {list(a.enum)}" if a.enum else ""
            rendered.append(f"{a.name} ({kind}, {tag}{choices})")
        return line + "\n  arguments: " + "; ".join(rendered)


def render_tool_instructions(specs: Sequence[ToolSpec]) -> str:
    """Prompt part 3: how a no-native-tool model must emit a tool call.

    The adapter appends this only when ``ModelSpec.native_tools`` is false —
    a native model gets the declaration (``to_wire``) and an empty part 3.
    """
    catalogue = "\n".join(spec.format_instructions() for spec in specs)
    return (
        "To call a tool, reply with ONLY a single JSON object and nothing else, "
        "in exactly this shape:\n"
        '{"tool_call": {"name": "<tool_name>", "arguments": {<args>}}}\n'
        "Do not wrap it in prose, markdown, or code fences. Use only these tools:\n"
        f"{catalogue}"
    )
