"""Run `python -m factory.writer`."""

from factory.module_entrypoint import run_module_entrypoint
from factory.writer.cli import main

if __name__ == "__main__":
    run_module_entrypoint("writer", main)
