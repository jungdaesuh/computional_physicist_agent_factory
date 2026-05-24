# __init__.py — Public exports for the operator module
#
# This file exports the public API of the operator module. Other modules should
# only import from `factory.operator`, not from internal files.

import logging

logger = logging.getLogger("factory.operator")

# Public exports
__all__: list[str] = []
