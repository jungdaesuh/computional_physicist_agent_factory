# test_ledger_typical_usage.py — Integration test showing typical usage of the Evidence Ledger
#
# Demonstrates:
# 1. Opening an in-memory DB in mock mode.
# 2. Inserting an EvidenceLedgerEntry fixture.
# 3. Running filtering queries and citation audits.
# 4. Triggering re-litigation condition updates.
# 5. Backup export and restore.

import logging
from pathlib import Path

from factory.artifacts.api import EvidenceLedgerEntry
from factory.ledger import Ledger, LedgerQuery

logger = logging.getLogger("factory.ledger.tests")


def test_ledger_typical_usage(tmp_path: Path) -> None:
    """Demonstrates typical usage of the Ledger class."""
    logger.info("Running typical usage test for ledger")

    # 1. Instantiate in mock/in-memory mode for testing
    with Ledger(db_path=tmp_path / "test_ledger.db", artifact_root=tmp_path) as ledger:
        # Load a valid fixture entry
        entry = EvidenceLedgerEntry.from_fixture("typical")
        assert entry is not None

        # 2. Insert the entry
        e_hash = ledger.insert_entry(entry)
        assert e_hash == entry.provenance_hash

        # 3. Retrieve by hash
        retrieved = ledger.get_by_hash(e_hash)
        assert retrieved.hypothesis_id == entry.hypothesis_id
        assert retrieved.result == entry.result

        # 4. Query with filter
        q = LedgerQuery(hypothesis_id=entry.hypothesis_id)
        results = ledger.query(q)
        assert len(results) == 1
        assert results[0].provenance_hash == e_hash

        # 5. Audit queries
        top_cited = ledger.top_cited_entries()
        # There are no downstream citing records in this fixture.
        assert isinstance(top_cited, list)

        # 6. Surprise bits update
        ledger.update_surprise(e_hash, 10.5)
        top_surprise = ledger.top_high_surprise_with_dependents(k=5)
        assert len(top_surprise) == 1
        assert top_surprise[0].surprise_bits == 10.5
        assert top_surprise[0].composite_score == 0.0  # 0 dependents

        # 7. Evaluate triggers
        reports = ledger.evaluate_triggers()
        assert len(reports) == 1
        assert reports[0].entry_hash == e_hash
        assert reports[0].new_state is False

        # 8. Export and restore
        export_file = tmp_path / "backup.jsonl"
        count = ledger.export(export_file)
        assert count == 1
        assert export_file.exists()

    # Restore in a fresh DB
    with Ledger(db_path=tmp_path / "restored.db", artifact_root=tmp_path) as fresh_ledger:
        restored_count = fresh_ledger.restore(export_file)
        assert restored_count == 1

        # Verify it exists in fresh ledger
        restored_entry = fresh_ledger.get_by_hash(e_hash)
        assert restored_entry.hypothesis_id == entry.hypothesis_id

        # Surprise bits should be preserved
        top_surprise = fresh_ledger.top_high_surprise_with_dependents(k=5)
        assert len(top_surprise) == 1
        assert top_surprise[0].surprise_bits == 10.5
