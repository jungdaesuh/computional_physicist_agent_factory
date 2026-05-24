"""Shared package entrypoint behavior for module-isolation smoke checks."""

from __future__ import annotations

import sys
from collections.abc import Callable


def run_module_entrypoint(module_name: str, main: Callable[[], None]) -> None:
    """Run a module CLI, reserving root --mock-mode for isolation checks."""
    if sys.argv[1:] == ["--mock-mode"]:
        print(f"{module_name} mock mode ready")
        return
    main()


__all__ = ["run_module_entrypoint"]
