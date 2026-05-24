"""Executable module entry point for `python -m factory.ledger`."""

from factory.ledger.cli import main
from factory.module_entrypoint import run_module_entrypoint

if __name__ == "__main__":
    run_module_entrypoint("ledger", main)
