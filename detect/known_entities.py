"""Known-entities layer (context.md §4.3, §6): the highest-value detection input.

The lawyer already knows the parties, so their canonical names are handed in as an explicit
list. This module is a THIN wrapper over the existing, correct Slovak declension matcher
(``detect.declension.match_entity``): it does NOT reimplement stemming or tokenizing. For
every constituent word of every supplied entity it collects the matching token spans,
deduplicates spans across ALL entities (two entities sharing a token -- e.g.
``["Jan Novak", "Novak"]`` -- must not emit the same span twice), and wraps each surviving
span as a ``MENO`` Candidate (auto=True) that then flows through detect()'s exact-span
precedence stages, where an identifier claim on the same span wins the tie.

SINGLE-CHARACTER GUARD (v1.1). ``match_entity`` matches PER TOKEN, so any single-letter token
in the supplied entity list becomes a one-letter needle that matches across the whole
document. This is not hypothetical: v1.1's ``detect.expansion.expand_person`` deliberately
generates initial forms ("A. Nováková", "Nováková A.") because documents really are written
that way — and the token "A." reduces to "a", which is the most common word in Slovak. Feeding
those variants in unguarded produced MENO candidates on every bare conjunction "a" in the
text, i.e. auto-redacting the document into rubble.

So a match whose surface carries fewer than two alphanumeric characters is DROPPED here, at
the point of consumption, rather than in the expander — this protects every caller, including
a lawyer who types a bare initial into the known-entities box by hand. Nothing is lost: an
initial only ever appears NEXT TO the surname it belongs to, and the surname token matches on
its own, so "J. Novák" is still fully redacted via "Novák".

This is the one place where recall is deliberately NOT maximised, and the reason is that the
alternative is not over-redaction of a name but destruction of the entire document.
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
            if sum(ch.isalnum() for ch in text[start:end]) < 2:
                continue  # single-character token — see SINGLE-CHARACTER GUARD above
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
