"""W5a (context.md §10): per-entity consistent, document-global redaction labels.

Type-only labels ("[MENO]", "[RODNE_CISLO]") tell a reviewer WHAT was removed but lose WHO —
every party collapses to the same token, and one party's name reads identically to another's.
This unit mints numbered labels ("[MENO_1]", "[RODNE_CISLO_1]", ...) that stay CONSISTENT
across the whole document: the same entity -> the same number at every occurrence and in every
location (body, tables, headers/footers, textboxes, notes). Threading ONE LabelMap through the
entire redaction pass (writer.docx_body) is what makes the numbering document-global.

Grouping — deciding "is this candidate the same entity I already numbered?" — is the crux:

  * MENO carries no entity id (detect.known_entities emits one span-deduped MENO per matched
    TOKEN and drops which supplied entity produced it), so we recover the party by asking the
    Slovak declension matcher: iterate the known_entities IN ORDER and bind to the FIRST whose
    ``match_entity(surface, entity)`` is non-empty. Order-first binding means a first name shared
    by two parties deterministically attaches to the earlier party — acceptable, since surnames
    still separate them, and every occurrence of a given surface resolves the same way. A MENO
    matching no known entity (defensive; should not happen when the caller passes the GT names)
    falls back to grouping by normalized surface.
  * Every other type groups by normalized surface: strip ALL whitespace — a Unicode ``\\s`` sub,
    which removes U+00A0 NBSP as well as ASCII spaces — then casefold. So "0911 402 917",
    "0911\\u00a0402\\u00a0917" and "0911402917" are one group, and header/body/textbox variants
    of one identifier never split into different numbers.

Pure, docx-free unit: imports only detect.declension (the existing stemming engine — NOT
reimplemented). MUST NOT import corpus/ or eval/.
"""
from __future__ import annotations

import re

from detect.declension import match_entity

# A Unicode (str) ``\s`` class already covers U+00A0 NBSP, so this single sub strips ASCII
# spaces, tabs, newlines AND NBSP — the whole point being that spaced / NBSP-glued / fully
# glued variants of one surface collapse to one group key.
_WS_RE = re.compile(r"\s")


def normalize(s: str) -> str:
    """Strip all whitespace (incl. NBSP) then casefold — the group key for surface-grouped types."""
    return _WS_RE.sub("", s).casefold()


class LabelMap:
    """Mints and remembers ``[TYPE_N]`` labels, consistent per entity, document-global.

    One instance is threaded through an entire redaction pass; first-seen order of groups (which
    equals the pass's fixed traversal order) fixes the numbering, so it is deterministic."""

    def __init__(self, known_entities: list[str] | None) -> None:
        self._known: list[str] = list(known_entities) if known_entities else []
        self._counters: dict[str, int] = {}  # type -> highest N minted so far
        self._cache: dict[tuple[str, tuple], str] = {}  # (type, group_key) -> label
        # Report-capture side-channels, populated by the redaction pass via the explicit
        # record_* methods below (NOT by label_for, which stays pure/cached). These feed a
        # later round's <name>_report.txt and never influence numbering or redaction.
        self.occurrences: dict[str, list[tuple[str, str]]] = {}  # label -> [(location, surface)]
        self.low_confidence: list[tuple[str, str, str]] = []  # [(location, type, surface)]

    def group_key(self, cand) -> tuple:
        """Identity key for ``cand`` WITHIN its type. MENO resolves to its party via declension;
        everything else keys on the normalized surface."""
        if cand.type == "MENO":
            for i, entity in enumerate(self._known):
                if match_entity(cand.surface, entity):
                    return ("entity", i)
            return ("surface", normalize(cand.surface))  # defensive fallback
        return ("surface", normalize(cand.surface))

    def label_for(self, cand) -> str:
        """Return the ``[TYPE_N]`` label for ``cand``: the cached number for a group already seen,
        otherwise the next N for that type (minted on first sighting)."""
        key = (cand.type, self.group_key(cand))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        n = self._counters.get(cand.type, 0) + 1
        self._counters[cand.type] = n
        label = f"[{cand.type}_{n}]"
        self._cache[key] = label
        return label

    def record_occurrence(self, label: str, location: str, surface: str) -> None:
        """Append ONE redacted-span record. Called for EVERY kept (auto=True) occurrence,
        including repeats of an already-numbered label — never deduped."""
        self.occurrences.setdefault(label, []).append((location, surface))

    def record_low_confidence(self, location: str, type: str, surface: str) -> None:
        """Append ONE low-confidence (auto=False) record: a span detect() flagged for review
        that the pass leaves UNREDACTED and UNLABELLED."""
        self.low_confidence.append((location, type, surface))
