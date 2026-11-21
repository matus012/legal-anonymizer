"""Registers the ``acceptance`` marker and keeps acceptance-only tests out of the normal dev
loop (context.md rejection, defect D2/D7): the held-out corpus (``data/holdout``) must never
be iterated against, so tests marked ``acceptance`` are skipped unless explicitly requested
with ``pytest --run-acceptance`` (or ``pytest -m acceptance``, which still selects them
directly regardless of this default).

Deliberately a ``conftest.py`` under ``tests/`` rather than a root-level ``pytest.ini`` — see
context.md rejection round 2: the fix must live entirely under ``eval/`` and ``tests/``.
"""
from __future__ import annotations

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-acceptance",
        action="store_true",
        default=False,
        help="run acceptance-marked tests (the held-out corpus) instead of skipping them",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "acceptance: opt-in only, runs against the held-out corpus (data/holdout, seed "
        "1337). Never iterate against these results — run explicitly with "
        "`pytest --run-acceptance` or `pytest -m acceptance`.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-acceptance"):
        return
    skip_acceptance = pytest.mark.skip(reason="acceptance tests only run with --run-acceptance")
    for item in items:
        if "acceptance" in item.keywords:
            item.add_marker(skip_acceptance)
