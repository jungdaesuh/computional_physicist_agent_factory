# cli.py — Command Line Interface for writer
#
# Exposes subcommands for internal debugging and manual execution.

import argparse
import logging
import sys

logger = logging.getLogger("factory.writer.cli")


def main() -> None:
    """CLI entry point for the writer module."""
    logger.info("main() called with args=%s", sys.argv[1:])
    parser = argparse.ArgumentParser(description="Writer CLI")
    parser.add_argument("--mock-mode", action="store_true", help="Run in mock mode")
    args = parser.parse_args()

    if args.mock_mode:
        print("Running writer in mock mode.")
    else:
        print("Running writer in live mode.")


if __name__ == "__main__":
    main()
