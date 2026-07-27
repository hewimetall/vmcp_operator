PYTHON ?= .venv/bin/python
UV ?= uv
CARGO ?= cargo
HELM ?= helm
CHART ?= charts/vmcp-operator

.PHONY: sync develop test-py test-rs lint-py lint-rs cov-py cov-rs helm-lint helm-template spike

sync:
	$(UV) sync --extra dev

develop:
	$(UV) run maturin develop

test-py:
	$(UV) run pytest

test-rs:
	$(CARGO) test -p vmcp-op-core

lint-py:
	$(UV) run ruff check python tests

lint-rs:
	$(CARGO) fmt --all -- --check
	$(CARGO) clippy -p vmcp-op-core -p vmcp-op-pyo3 -- -D warnings

cov-py:
	$(UV) run pytest --cov=vmcp_operator --cov-report=term-missing

cov-rs:
	$(CARGO) llvm-cov -p vmcp-op-core --fail-under-lines 93

helm-lint:
	$(HELM) lint $(CHART)

helm-template:
	$(HELM) template test $(CHART) --namespace vmcp-system >/dev/null

spike:
	PYTHON_LAZY_IMPORTS=normal $(PYTHON) scripts/phase_minus_one_kopf_spike.py
