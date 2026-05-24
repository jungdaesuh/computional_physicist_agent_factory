# __init__.py — Public exports for the validation module
#
# This file exports the public API of the validation module. Other modules should
# only import from `factory.validation`, not from internal files.

import logging

logger = logging.getLogger("factory.validation")

# Public exports
__all__: list[str] = []
