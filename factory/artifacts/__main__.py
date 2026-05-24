"""Run `python -m factory.artifacts`."""

from factory.artifacts.cli import main
from factory.module_entrypoint import run_module_entrypoint

if __name__ == "__main__":
    run_module_entrypoint("artifacts", main)
