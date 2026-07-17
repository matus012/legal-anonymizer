"""Known-entities layer (context.md §4.3, §6): the highest-value detection input.

The lawyer already knows the parties, so their canonical names are handed in as an explicit
list. This module is a THIN wrapper over the existing, correct Slovak declension matcher
(``detect.declension.match_entity``): it does NOT reimplement stemming or tokenizing. For
every constituent word of every supplied entity it collects the matching token spans,
deduplicates spans across ALL entities (two entities sharing a token -- e.g.
``["Jan Novak", "Novak"]`` -- must not emit the same span twice), and wraps each surviving
span as a ``MENO`` Candidate (auto=True) that then flows through detect()'s exact-span
precedence stages, where an identifier claim on the same span wins the tie.
"""
from __future__ import annotations

from .core import Candidate
from .declension import match_entity


def detect_known_entities(text: str, entities: list[str]) -> list[Candidate]:
    if not entities:
        return []
    seen: set[tuple[int, int]] = set()
    out: list[Candidate] = []
    for entity in entities:
        for start, end in match_entity(text, entity):
            if (start, end) in seen:
                continue
            seen.add((start, end))
            out.append(
                Candidate(
                    type="MENO",
                    surface=text[start:end],
                    start=start,
                    end=end,
                    auto=True,
                )
            )
    return out
