from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

FILES = re.compile(r"^### `([^`]+\.py)`\n.*?^```python\n(.*?)^```", re.M | re.S)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--through", type=int, choices=range(1, 8), default=7)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix="llmgrid-guide-") as temporary:
        destination = Path(temporary)
        for package in ("interfaces", "network", "tools", "loops", "context", "rag"):
            shutil.copytree(
                root / f"packages/{package}/src/llmgrid/{package}",
                destination / f"llmgrid/{package}",
            )
        phases = sorted((root / "docs/plan").glob("phase-*.md"))
        for phase in phases:
            number = int(phase.name.split("-")[1])
            if not 1 <= number <= args.through:
                continue
            sources = [phase]
            if number == 7:
                sources.extend(sorted((root / "docs/plan").glob("example-*.md")))
            showcases: list[Path] = []
            for source in sources:
                for filename, code in FILES.findall(source.read_text()):
                    path = Path(filename)
                    if path.parts[:1] == ("packages",):
                        path = Path(*path.parts[3:])
                    if path.is_absolute() or ".." in path.parts:
                        raise ValueError("Invalid documented file path")
                    target = destination / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    compile(code, filename, "exec")
                    target.write_text(code)
                    if path.name.startswith("showcase_"):
                        showcases.append(target)
            environment = dict(os.environ, PYTHONPATH=str(destination))
            # -B avoids __pycache__ reuse between successive phase replacements.
            examples = [destination / f"examples/implementation/phase{number}.py", *showcases]
            for example in examples:
                subprocess.run(
                    [sys.executable, "-B", str(example)],
                    cwd=destination,
                    env=environment,
                    check=True,
                )
    print("All selected phase examples passed")


if __name__ == "__main__":
    main()
