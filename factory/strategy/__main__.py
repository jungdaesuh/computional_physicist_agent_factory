"""Run `python -m factory.strategy`."""

from factory.module_entrypoint import run_module_entrypoint
from factory.strategy.cli import main

if __name__ == "__main__":
    run_module_entrypoint("strategy", main)
