PYTHON ?= python3
VENV   ?= venv
BIN    := $(VENV)/bin

.PHONY: help venv test coverage lint build clean distclean

help:
	@echo "make venv       create $(VENV)/ and install hxtool with dev dependencies"
	@echo "make test       run the test suite (including pycodestyle checks)"
	@echo "make coverage   run the test suite with coverage, HTML report in htmlcov/"
	@echo "make lint       run the pycodestyle checks only"
	@echo "make build      build sdist and wheel into dist/"
	@echo "make clean      remove caches, coverage data and build output"
	@echo "make distclean  clean, and remove $(VENV)/ as well"

venv: $(VENV)/.installed

# Reinstall whenever the dependency declarations change
$(VENV)/.installed: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e '.[dev]'
	touch $@

test: venv
	$(BIN)/python -m pytest -v

coverage: venv
	$(BIN)/python -m coverage run --source=hxtool -m pytest
	$(BIN)/python -m coverage report
	$(BIN)/python -m coverage html

lint: venv
	$(BIN)/python -m pycodestyle hxtool tests

build: venv
	$(BIN)/python -m pip install build
	$(BIN)/python -m build

clean:
	rm -rf .pytest_cache .coverage htmlcov build dist *.egg-info
	find . -path ./$(VENV) -prune -o -type d -name __pycache__ -exec rm -rf {} +

distclean: clean
	rm -rf $(VENV)
