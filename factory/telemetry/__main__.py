"""Run `python -m factory.telemetry`."""

from __future__ import annotations

from factory.module_entrypoint import run_module_entrypoint
from factory.telemetry.cli import main

if __name__ == "__main__":
    run_module_entrypoint("telemetry", main)
