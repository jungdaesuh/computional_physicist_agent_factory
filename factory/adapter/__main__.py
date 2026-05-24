"""Run `python -m factory.adapter`."""

from factory.adapter.cli import main
from factory.module_entrypoint import run_module_entrypoint

if __name__ == "__main__":
    run_module_entrypoint("adapter", main)
