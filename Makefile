# Convenience targets.  Everything works without them; they exist so that
# "how do I reproduce the numbers in the README" has a one-line answer.

PY ?= python
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help venv install test test-fast coverage demo bench bounds sensitivity v2g app clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

venv: ## create the virtual environment
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

install: venv ## install runtime + dev dependencies
	$(BIN)/pip install -r requirements-dev.txt

test: ## run the whole test suite
	$(BIN)/python -m pytest

test-fast: ## skip the benchmark-scale checks
	$(BIN)/python -m pytest -m "not slow"

coverage: ## test suite with a coverage report for the evrp package
	$(BIN)/python -m pytest --cov=evrp --cov-report=term-missing

demo: ## solve C101 end to end and write figures to outputs/
	$(BIN)/python main.py --time-limit 20

bench: ## reproduce results/unconstrained/ and results/constrained/
	$(BIN)/python -m evrp.cli compare \
		--instances C101 C201 R101 R201 RC101 RC201 \
		--solvers ortools insertion-ls insertion savings \
		--battery 80 --stations 6 --time-limit 20 --seed 42 \
		--out results/unconstrained
	$(BIN)/python -m evrp.cli compare \
		--instances C101 C201 R101 R201 RC101 RC201 \
		--solvers ortools insertion-ls insertion savings \
		--battery 25 --stations 8 --time-limit 20 --seed 42 \
		--out results/constrained

bounds: ## reproduce results/consumption_bounds.csv
	$(BIN)/python -m evrp.cli bounds --instances C101 C201 R201 \
		--battery 25 --stations 8 --station-copies 3 --time-limit 20 --seed 42 \
		--out results

sensitivity: ## reproduce results/sensitivity.csv
	$(BIN)/python -m evrp.cli sensitivity \
		--instances C101 R101 RC101 --solvers ortools \
		--batteries 80 40 25 18 14 --stations 8 --time-limit 20 --seed 42 --out results

v2g: ## reproduce results/R201-v2g.json
	$(BIN)/python -m evrp.cli v2g --instance data/R201.csv --capacity 1000 \
		--battery 60 --stations 8 --time-limit 20 --solver insertion-ls \
		--out results

app: ## launch the Streamlit dashboard
	$(BIN)/python -m streamlit run app.py

clean: ## remove caches and generated artefacts
	rm -rf .pytest_cache **/__pycache__ .coverage outputs
