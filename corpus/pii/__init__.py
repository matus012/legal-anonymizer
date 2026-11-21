"""Deterministic PII identifier generators (context.md §4.1).

Each module exposes pure ``is_valid`` validators and seeded ``generate`` producers.
The generators emit both checksum-valid and deliberately checksum-invalid variants so
the corpus can exercise the detector's precision (§7 seeded failure modes).
"""
