"""Run `python -m factory.fidelity`."""

from factory.fidelity.cli import main
from factory.module_entrypoint import run_module_entrypoint

if __name__ == "__main__":
    run_module_entrypoint("fidelity", main)
