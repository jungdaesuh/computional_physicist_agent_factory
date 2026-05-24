"""Executable module entry point for `python -m factory.llm_client`."""

from factory.llm_client.cli import main
from factory.module_entrypoint import run_module_entrypoint

if __name__ == "__main__":
    run_module_entrypoint("llm_client", main)
