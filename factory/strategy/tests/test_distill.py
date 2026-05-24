# test_distill.py — Unit tests for Behavior Descriptor extraction logic
#
# Verifies keyword-based score mapping and discretization onto MAP-Elites cells.

from __future__ import annotations

import logging

from factory.strategy.distill import extract_behavior_descriptor

logger = logging.getLogger("factory.strategy.tests.test_distill")


def test_extract_behavior_descriptor_typical() -> None:
    """Test behavior descriptor extraction with a rich description."""
    summary_md = (
        "# Stellarator Optimization Strategy\n"
        "We optimize the grid resolution and nodes for MHD stability and curvature.\n"
        "This relies on a gradient gd solver with an adaptive step."
    )
    descriptor = extract_behavior_descriptor(summary_md)
    assert descriptor is not None
    assert len(descriptor.vector) == 3
    # Verify that cell_id has the correct format cell_X_Y_Z
    assert descriptor.cell_id is not None
    assert descriptor.cell_id.startswith("cell_")
    parts = descriptor.cell_id.split("_")
    assert len(parts) == 4
    assert all(p in ("L", "M", "H") for p in parts[1:])


def test_extract_behavior_descriptor_empty() -> None:
    """Test extractor with empty string defaults to low values."""
    descriptor = extract_behavior_descriptor("")
    assert descriptor.vector == (0.0, 0.0, 0.0)
    assert descriptor.cell_id == "cell_L_L_L"
