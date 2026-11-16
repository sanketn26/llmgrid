"""Check that the feature guides stay contracts, not reference implementations.

Each guide in docs/features must have Expects, Unit tests, and Acceptance.
Features 01-15 must contain a unit-test block. Every Python fence in a
feature guide must be one of those tests, and those tests must compile.
Showcase files in docs/plan must not carry a pasted program. This does not
implement a feature and it does not run the feature tests.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BLOCK = re.compile(r"^### `([^`]+)`\n\n.*?\n\n```python\n(.*?)```", re.M | re.S)
PYTHON = re.compile(r"^```python\n.*?^```", re.M | re.S)
REQUIRED = ("## Expects", "## Unit tests", "## Acceptance")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    features = sorted((root / "docs/features").glob("[0-9][0-9]-*.md"))
    if len(features) != 16:
        raise SystemExit(f"Expected 16 feature guides, found {len(features)}")
    for feature in features:
        text = feature.read_text()
        missing = [heading for heading in REQUIRED if heading not in text]
        if missing:
            raise SystemExit(f"{feature.name} is missing {', '.join(missing)}")
        if "does not include their bodies" not in text and not feature.name.startswith("00"):
            raise SystemExit(f"{feature.name} does not say the implementation bodies are absent")
        blocks = BLOCK.findall(text)
        if not feature.name.startswith("00") and not blocks:
            raise SystemExit(f"{feature.name} has no unit test")
        for filename, code in blocks:
            allowed = "/tests/test_" in filename or filename.startswith("tests/")
            if not allowed:
                raise SystemExit(f"{feature.name} still contains an implementation: {filename}")
            compile(code, filename, "exec")
        if PYTHON.search(BLOCK.sub("", text)):
            raise SystemExit(f"{feature.name} still contains an implementation")
        print(f"{feature.name} is a guide")
    for showcase in sorted((root / "docs/plan").glob("example-*.md")):
        if PYTHON.search(showcase.read_text()):
            raise SystemExit(f"{showcase.name} still contains a reference program")
    print("Feature guides have expectations, unit tests, and acceptance criteria")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(exc, file=sys.stderr)
        raise
