"""Run `python -m factory.surrogate`."""

from factory.module_entrypoint import run_module_entrypoint
from factory.surrogate.cli import main

if __name__ == "__main__":
    run_module_entrypoint("surrogate", main)
