# Phase 8: verify, package, and release

[All phases](../composable-agent-platform-plan.md)

## Starting point

| Action | Starting file / role |
| --- | --- |
| Reuse | Root `Makefile`, `pyproject.toml`, and `requirements-dev.txt` |
| Reuse | `packages/*/pyproject.toml`, READMEs, LICENSE files, and `py.typed` markers |
| Reuse | `.github/workflows/ci.yml` and existing tests as the validation baseline |
| Reuse | `tools/check_implementation_guide.py`, already provided alongside this guide |
| Update | Exports, dependency extras, compatible version ranges, and capability documentation for the code you actually implemented |

## Check the guide before applying it

The repository includes [check_implementation_guide.py](../../tools/check_implementation_guide.py).
It copies the existing package source into a temporary directory, applies the file
blocks from each phase in order, and runs that phase's offline example. Phase 7 also loads the linked
`example-*.md` guides and runs every showcase. It does not
modify your production source or contact providers.

```bash
.venv/bin/python tools/check_implementation_guide.py
.venv/bin/python tools/check_implementation_guide.py --through 3
```

## Check the implementation after applying it

Migrate existing callers and tests as each public signature changes. Run:

```bash
make check
make build
make smoke
```

The guide examples verify representative behaviour; they do not replace contract,
cancellation, malformed-input, and crash tests for your final implementation.

## Package changes

- [ ] Export the new public types from each package's `__init__.py`.
- [ ] Keep optional dependencies in network/MCP/telemetry extras.
- [ ] Coordinate versions where interfaces and consumer signatures change.
- [ ] Verify clean installs with each extra and with no extras.
- [ ] Record tested provider models/platforms and supported Python versions.
- [ ] Run live adapter checks before claiming provider support.
- [ ] Mark streaming support separately from non-streaming model support.

Publish interfaces first, dependent packages next, and the meta-package last.
Use the existing `make publish-<pkg>` targets after the release checks pass.
