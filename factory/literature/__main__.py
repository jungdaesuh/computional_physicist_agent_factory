"""Run `python -m factory.literature`."""

from factory.literature.cli import main
from factory.module_entrypoint import run_module_entrypoint

if __name__ == "__main__":
    run_module_entrypoint("literature", main)
