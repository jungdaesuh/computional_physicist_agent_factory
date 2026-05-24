# Fidelity Module (Spec 017)

Implements the fidelity-ladder scheduling contract from `docs/specs/017-fidelity-scheduler.md`: tier decisions, dispatch helpers, promotion bookkeeping, and module-isolation commands.

## Quick Start

```bash
python -m factory.fidelity --mock-mode
python -m factory.fidelity inspect
python -m factory.fidelity kill-criteria
python -m factory.fidelity run-ladder --mock-mode
```

## Typical Usage

See `tests/test_fidelity_typical_usage.py` and `tests/test_scheduler.py` for the public contract and ladder traversal behavior.
