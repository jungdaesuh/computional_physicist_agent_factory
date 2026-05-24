# Adapter Module (Spec 006)

Implements the domain-adapter contract from `docs/specs/006-domain-adapter.md`: six solver-component ABCs, registered simulator adapters, typed run artifacts, and output-schema validation.

## Quick Start

```bash
python -m factory.adapter --mock-mode
python -m factory.adapter list
python -m factory.adapter inspect sim_a --mock-mode
python -m factory.adapter run --simulator-id sim_a --experiment-fixture typical --mock-mode
```

## Typical Usage

See `tests/test_adapter_typical_usage.py` for the public contract and mock adapter flow.
