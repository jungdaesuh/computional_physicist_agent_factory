"""Run `python -m factory.budget`."""

from factory.budget.cli import main
from factory.module_entrypoint import run_module_entrypoint

if __name__ == "__main__":
    run_module_entrypoint("budget", main)
