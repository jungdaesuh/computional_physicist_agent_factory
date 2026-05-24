"""Executable module entry point for `python -m factory.operator`."""

from factory.module_entrypoint import run_module_entrypoint
from factory.operator.cli import main

if __name__ == "__main__":
    run_module_entrypoint("operator", main)
