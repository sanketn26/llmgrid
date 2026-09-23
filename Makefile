# llmgrid developer tasks.
# Every target runs inside one project-local virtualenv at $(VENV) where all
# packages are installed in editable mode.
#
# Per-package targets take the package's directory name under packages/:
#   make test-tools   lint-tools   typecheck-tools   check-tools
#   make build-tools  publish-tools
# Run `make packages` to list them.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin
PY     := $(BIN)/python
PIP    := $(BIN)/pip

# Code packages in dependency order (interfaces first). `llmgrid` is the
# meta-package that depends on all of them and ships no code.
CODE_PACKAGES := interfaces network tools context rag loops
PACKAGES      := $(CODE_PACKAGES) llmgrid

# twine repository: `pypi` or `testpypi`.
REPOSITORY ?= pypi
# Branch a release must be published from.
RELEASE_BRANCH ?= main

STAMP := $(VENV)/.install-stamp

.DEFAULT_GOAL := help
.PHONY: help packages setup test live-test lint format typecheck check build smoke demo cleanup

help: ## Show this help
	@grep -hE '^[a-zA-Z_%-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  <pkg> is one of: $(PACKAGES)"

packages: ## List the packages and their distribution names and versions
	@for p in $(PACKAGES); do \
		printf "  %-12s %s\n" "$$p" "$$(sed -nE 's/^(name|version) = "(.*)"/\2/p' packages/$$p/pyproject.toml | paste -sd' ' -)"; \
	done

$(STAMP): requirements-dev.txt $(foreach p,$(CODE_PACKAGES),packages/$(p)/pyproject.toml)
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt $(foreach p,$(CODE_PACKAGES),-e packages/$(p))
	@touch $(STAMP)

setup: $(STAMP) ## Create the virtualenv and install every package in editable mode
	@echo "Environment ready. Activate with: source $(BIN)/activate"

# ---------------------------------------------------------------- all packages

test: $(STAMP) ## Run every offline test (packages, integration, architecture)
	$(BIN)/pytest -m 'not live'

live-test: $(STAMP) ## Run live provider tests (requires credentials)
	@if [ -d tests/live ]; then $(BIN)/pytest -m live tests/live; \
	else echo "No live tests yet (tests/live does not exist)"; fi

lint: $(STAMP) ## Check formatting and lint rules everywhere
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: $(STAMP) ## Apply formatting and autofixable lint rules everywhere
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

typecheck: $(STAMP) ## Run mypy in strict mode, including negative typing tests
	$(BIN)/mypy

check: lint typecheck test ## Run everything CI runs

build: $(foreach p,$(PACKAGES),build-$(p)) ## Build every package into packages/<pkg>/dist

smoke: build ## Install all built wheels into a clean virtualenv and import each package
	rm -rf .smoke && $(PYTHON) -m venv .smoke
	.smoke/bin/pip install --quiet --no-index --find-links packages/interfaces/dist \
		$(foreach p,$(CODE_PACKAGES),--find-links packages/$(p)/dist) \
		$(foreach p,$(PACKAGES),packages/$(p)/dist/*.whl)
	.smoke/bin/python -c 'import importlib; [importlib.import_module("llmgrid." + p) for p in "$(CODE_PACKAGES)".split()]; print("smoke ok")'
	rm -rf .smoke

demo: $(STAMP) ## Run the offline tool-agent example
	$(PY) examples/tool_agent/demo.py

# ----------------------------------------------------------------- per package

# Fails fast on an unknown package name.
pkg-exists-%:
	@test -f packages/$*/pyproject.toml || { echo "Unknown package '$*'. Choose from: $(PACKAGES)"; exit 1; }

test-%: pkg-exists-% $(STAMP) ## Run one package's tests, e.g. make test-tools
	@if [ -d packages/$*/tests ]; then $(BIN)/pytest -m 'not live' packages/$*/tests; \
	else echo "packages/$* has no tests"; fi

lint-%: pkg-exists-% $(STAMP) ## Lint one package
	$(BIN)/ruff check packages/$*
	$(BIN)/ruff format --check packages/$*

typecheck-%: pkg-exists-% $(STAMP) ## Type-check one package
	@if [ -d packages/$*/src ]; then $(BIN)/mypy packages/$*; \
	else echo "packages/$* has no code"; fi

check-%: lint-% typecheck-% test-% ## Lint, type-check, and test one package
	@:

build-%: pkg-exists-% $(STAMP) ## Build one package's sdist and wheel into packages/<pkg>/dist
	rm -rf packages/$*/dist
	$(PY) -m build --outdir packages/$*/dist packages/$*
	$(BIN)/twine check --strict packages/$*/dist/*

# Publishing is deliberate: it requires the release branch and a clean tree,
# checks the package, then uploads. twine prompts for the API token unless
# TWINE_PASSWORD is set. Publish interfaces before packages that depend on it.
publish-%: pkg-exists-% $(STAMP) ## Check and publish one package (REPOSITORY=pypi|testpypi)
	@branch="$$(git rev-parse --abbrev-ref HEAD)"; \
	if [ "$$branch" != "$(RELEASE_BRANCH)" ]; then \
		echo "Refusing to publish from '$$branch'; switch to $(RELEASE_BRANCH)."; exit 1; fi
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "Refusing to publish with uncommitted changes."; exit 1; fi
	@if [ "$*" != "llmgrid" ]; then $(MAKE) --no-print-directory check-$*; fi
	$(MAKE) --no-print-directory build-$*
	$(BIN)/twine upload --repository $(REPOSITORY) packages/$*/dist/*

cleanup: ## Remove the virtualenv, build output, and caches
	rm -rf $(VENV) .smoke build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
	rm -rf $(foreach p,$(PACKAGES),packages/$(p)/dist)
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
