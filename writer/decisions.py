"""Phase 6: the reviewer's decisions, threaded into the writers.

A decision refers to a GROUP — ``(cand.type, LabelMap.group_key(cand))`` — never to a single
occurrence: the review screen is grouped by entity (context.md §9), so suppressing a group
suppresses every occurrence of that entity, and forcing one forces all of them.
``decisions=None`` in a writer call means byte-identical pre-Phase-6 behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RedactionDecisions:
    extra_terms: tuple[str, ...] = ()        # free-text "redact this too" -> joins known_entities
    suppress_groups: frozenset = frozenset()  # {(type, group_key)}: auto candidates NOT redacted
    force_groups: frozenset = frozenset()     # {(type, group_key)}: low-confidence candidates redacted
