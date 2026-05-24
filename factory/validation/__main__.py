"""Run `python -m factory.validation`."""

from factory.module_entrypoint import run_module_entrypoint
from factory.validation.cli import main

if __name__ == "__main__":
    run_module_entrypoint("validation", main)
