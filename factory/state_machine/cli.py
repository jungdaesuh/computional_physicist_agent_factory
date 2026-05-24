# cli.py — Command Line Interface for state_machine
#
# Exposes subcommands for internal debugging and manual execution.

import argparse
import logging
import sys

logger = logging.getLogger("factory.state_machine.cli")


def main() -> None:
    """CLI entry point for the state_machine module."""
    logger.info("main() called with args=%s", sys.argv[1:])
    parser = argparse.ArgumentParser(description="State_machine CLI")
    parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    args = parser.parse_args()

    if args.mock_mode:
        print("Running state_machine in mock mode.")
    else:
        print("Running state_machine in live mode.")


if __name__ == "__main__":
    main()
