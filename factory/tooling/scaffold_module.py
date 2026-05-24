# scaffold_module.py — Module Bootstrapping CLI Tool
#
# This script automates the creation of a new module directory structure matching
# the template defined in ARCHITECTURE.md §3.1.
#
# Use cases:
# 1. Generating a new core factory component (e.g. factory/budget)
# 2. Scaffolding tests and mocks automatically to maintain architectural consistency.
#
# Usage:
# python -m factory.tooling.scaffold_module --name <module_name> --spec <spec_number>

import argparse
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("factory.tooling.scaffold_module")


def create_file(path: Path, content: str) -> None:
    """Helper function to write content to a file, creating parent directories if needed.

    Args:
        path: Path to the target file.
        content: Code or text contents of the file.
    """
    logger.info("create_file(path=%s, content_len=%d)", path, len(content))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def scaffold(name: str, spec_num: str) -> None:
    """Generates the standardized module structure for a given name and spec number.

    Args:
        name: Name of the module (e.g. 'budget').
        spec_num: The specification number (e.g. '013').
    """
    logger.info("scaffold(name=%s, spec_num=%s)", name, spec_num)
    root = Path(__file__).resolve().parents[2] / "factory" / name

    if root.exists():
        logger.error("Directory already exists: %s", root)
        sys.exit(1)

    # 1. __init__.py
    init_content = f"""# __init__.py — Public exports for the {name} module
#
# This file exports the public API of the {name} module. Other modules should
# only import from `factory.{name}`, not from internal files.

import logging

logger = logging.getLogger("factory.{name}")

# Public exports
__all__: list[str] = []
"""

    # 2. README.md
    readme_content = f"""# {name.capitalize()} Module (Spec {spec_num})

This module implements the functionality described in `docs/specs/{spec_num}-*.md`.

## Quick Start

Run this module in mock mode:
```bash
python -m factory.{name} --mock-mode
```

## Typical Usage

See `tests/test_{name}_typical_usage.py` for a complete integration example.
"""

    # 3. api.py
    api_content = f"""# api.py — Public interface of {name}
#
# This file defines the public-facing API for the {name} module.
# All functions/classes should have docstrings and log their calls.

import logging

logger = logging.getLogger("factory.{name}.api")
"""

    # 4. types.py
    types_content = f"""# types.py — Module-local types for {name}
#
# Defines internal or local types specific to the {name} module.
# Do not store shared artifacts here; those live in factory/artifacts/
"""

    # 5. errors.py
    errors_content = f"""# errors.py — Module-specific errors for {name}
#
# Defines the exception hierarchy for {name}. All exceptions must inherit
# from FactoryError.

class FactoryError(Exception):
    \"\"\"Base exception class for the factory.\"\"\"
    pass

class {name.capitalize()}Error(FactoryError):
    \"\"\"Base exception for the {name} module.\"\"\"
    pass
"""

    # 6. mock.py
    mock_content = f"""# mock.py — Mock implementation of the {name} API
#
# Implements mock functionality for local debugging and tests.
# Returns fixture data without performing real operations.

import logging

logger = logging.getLogger("factory.{name}.mock")
"""

    # 7. cli.py
    cli_content = f"""# cli.py — Command Line Interface for {name}
#
# Exposes subcommands for internal debugging and manual execution.

import argparse
import sys
import logging

logger = logging.getLogger("factory.{name}.cli")

def main() -> None:
    \"\"\"CLI entry point for the {name} module.\"\"\"
    logger.info("main() called with args=%s", sys.argv[1:])
    parser = argparse.ArgumentParser(description="{name.capitalize()} CLI")
    parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    args = parser.parse_args()

    if args.mock_mode:
        print("Running {name} in mock mode.")
    else:
        print("Running {name} in live mode.")

if __name__ == "__main__":
    main()
"""

    # 8. tests/__init__.py
    tests_init_content = ""

    # 9. tests/conftest.py
    conftest_content = f"""# conftest.py — pytest fixtures for {name}
import pytest
"""

    # 10. tests/test_typical_usage.py
    typical_usage_test_content = f"""# test_{name}_typical_usage.py
#
# This test acts as live documentation for the module's public API import path.

from factory.{name} import api

def test_{name}_typical_usage() -> None:
    \"\"\"Demonstrates typical usage of the {name} module.\"\"\"
    assert api.__name__ == "factory.{name}.api"
"""

    # 11. tests/test_api.py
    test_api_content = f"""# test_api.py — Unit tests for the public API of {name}
import pytest
"""

    # Write all files
    create_file(root / "__init__.py", init_content)
    create_file(root / "README.md", readme_content)
    create_file(root / "api.py", api_content)
    create_file(root / "types.py", types_content)
    create_file(root / "errors.py", errors_content)
    create_file(root / "mock.py", mock_content)
    create_file(root / "cli.py", cli_content)
    create_file(root / "tests" / "__init__.py", tests_init_content)
    create_file(root / "tests" / "conftest.py", conftest_content)
    create_file(root / "tests" / f"test_{name}_typical_usage.py", typical_usage_test_content)
    create_file(root / "tests" / "test_api.py", test_api_content)

    print(f"Successfully scaffolded module '{name}' under {root}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scaffold a standard factory module")
    parser.add_argument("--name", required=True, help="Name of the new module")
    parser.add_argument("--spec", required=True, help="Specification number (e.g. 013)")
    args = parser.parse_args()

    scaffold(args.name, args.spec)
