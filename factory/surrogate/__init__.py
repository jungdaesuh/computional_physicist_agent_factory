# __init__.py — Public exports for the surrogate module
#
# This file exports the public API of the surrogate module. Other modules should
# only import from `factory.surrogate`, not from internal files.

import logging

logger = logging.getLogger("factory.surrogate")

# Public exports
__all__: list[str] = []
