# __init__.py — Public exports for the genver module
#
# This file exports the public API of the genver module. Other modules should
# only import from `factory.genver`, not from internal files.

import logging

logger = logging.getLogger("factory.genver")

# Public exports
__all__: list[str] = []
