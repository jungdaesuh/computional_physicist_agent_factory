# migration.py — Typed JSON Artifact schema version migration utilities
#
# This file implements the version migration utility for typed JSON artifacts.
# It transitions v1 schemas to v2 schemas during loading or serialization.
#
# Use cases:
# 1. Migrating older JSON representation of EvidenceLedgerEntry to add surprise_bits.
# 2. Migrating GapCandidate fields to Phase B formats.

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger("factory.artifacts.migration")


def migrate_artifact_json(data: Mapping[str, object]) -> dict[str, object]:
    """Migrate raw JSON artifact data from old schemas to the current version.

    Args:
        data: A dictionary containing the raw JSON representation of an artifact.

    Returns:
        The migrated dictionary conforming to the latest Pydantic schemas.
    """
    logger.info("migrate_artifact_json called")

    migrated = dict(data)

    # 1. Deduce artifact type
    artifact_type = data.get("artifact_type")
    if not artifact_type:
        return migrated

    # 2. EvidenceLedgerEntry migrations
    if artifact_type == "EvidenceLedgerEntry":
        if "surprise_bits" not in migrated:
            migrated["surprise_bits"] = None
            logger.info("Added default surprise_bits to EvidenceLedgerEntry.")

    # 3. GapCandidate migrations
    elif artifact_type == "GapCandidate":
        # If gap_type is using old name formats, normalize it
        gap_type = data.get("gap_type")
        if gap_type == "methodology":
            migrated["gap_type"] = "methodology_transfer"
            logger.info("Normalized GapCandidate gap_type to methodology_transfer.")

    return migrated
