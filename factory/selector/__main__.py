"""Run `python -m factory.selector`."""

from __future__ import annotations

from factory.module_entrypoint import run_module_entrypoint
from factory.selector.cli import main

if __name__ == "__main__":
    run_module_entrypoint("selector", main)
