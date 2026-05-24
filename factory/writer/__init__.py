# __init__.py — Public exports for the writer module
#
# This file exports the public API of the writer module. Other modules should
# only import from `factory.writer`, not from internal files.

import logging

logger = logging.getLogger("factory.writer")

# Public exports
__all__: list[str] = []
