"""Run `python -m factory.catalog`."""

from __future__ import annotations

from factory.catalog.cli import main
from factory.module_entrypoint import run_module_entrypoint

if __name__ == "__main__":
    run_module_entrypoint("catalog", main)
