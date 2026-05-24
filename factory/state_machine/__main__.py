"""Run `python -m factory.state_machine`."""

from factory.module_entrypoint import run_module_entrypoint
from factory.state_machine.cli import main

if __name__ == "__main__":
    run_module_entrypoint("state_machine", main)
