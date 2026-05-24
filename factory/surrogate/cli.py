# cli.py — Command Line Interface for surrogate
#
# Exposes subcommands for internal debugging and manual execution.

import argparse
import logging
import sys

logger = logging.getLogger("factory.surrogate.cli")


def main() -> None:
    """CLI entry point for the surrogate module."""
    logger.info("main() called with args=%s", sys.argv[1:])
    parser = argparse.ArgumentParser(description="Surrogate CLI")
    parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    args = parser.parse_args()

    if args.mock_mode:
        print("Running surrogate in mock mode.")
    else:
        print("Running surrogate in live mode.")


if __name__ == "__main__":
    main()
