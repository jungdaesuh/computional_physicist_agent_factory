# cli.py — Command Line Interface for budget
#
# Exposes subcommands for internal debugging and manual execution.

import argparse
import logging
import sys

logger = logging.getLogger("factory.budget.cli")


def main() -> None:
    """CLI entry point for the budget module."""
    logger.info("main() called with args=%s", sys.argv[1:])
    parser = argparse.ArgumentParser(description="Budget CLI")
    parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    args = parser.parse_args()

    if args.mock_mode:
        print("Running budget in mock mode.")
    else:
        print("Running budget in live mode.")


if __name__ == "__main__":
    main()
