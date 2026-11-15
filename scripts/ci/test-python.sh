#!/usr/bin/env bash
# The Python test gate: pytest with coverage, the floor enforced by `coverage.toml`.
#
# Usage: test-python.sh [pytest args…]
#
# `--cov-config=coverage.toml` is what makes the floor opposable: coverage.py discovers
# .coveragerc, setup.cfg, tox.ini and pyproject.toml, and nothing named coverage.toml, so
# without the flag `fail_under` is read by nobody. `--cov` stays bare so the file's own
# `[run] source` decides what is measured, whatever the repo's layout.
#
# Writes coverage.xml and test-results.xml, the files the check uploads.
set -euo pipefail

PYTHONPATH=. exec uv run pytest --cov --cov-config=coverage.toml --cov-report=xml \
  --cov-report=term-missing --junit-xml=test-results.xml "$@"
