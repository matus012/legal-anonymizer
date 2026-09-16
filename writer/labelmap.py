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


def make_snippet(text: str, start: int, end: int, radius: int = 40) -> str:
    """±radius chars of context around [start:end), whitespace collapsed to single spaces —
    feeds the GUI review table only; never the report."""
    lo, hi = max(0, start - radius), min(len(text), end + radius)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


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
        # Phase 6 GUI side-channels: review-table context snippets. Kept SEPARATE from
        # occurrences/low_confidence so build_report's tuple unpacking stays byte-stable.
        self.contexts: dict[str, str] = {}  # label -> first-seen snippet
        self.lc_contexts: list[str] = []    # index-aligned with low_confidence
        # v1.1 checksum side-channels (CONTRACTS_v11.md §1/§10). Built EXACTLY like
        # contexts/lc_contexts and for the same reason: occurrences/low_confidence tuple shapes
        # are unpacked positionally by build_report, so the checksum tag CANNOT widen them.
        self.checksums: dict[str, str] = {}  # label -> checksum ("valid"|"invalid"|"n/a")
        self.lc_checksums: list[str] = []    # index-aligned with low_confidence
        # v1.1 crash safety (CONTRACTS_v11.md Amendment 11): detectors that RAISED during
        # this pass. Deduplicated on (detector, error) because the same bug fires on every
        # unit of the document -- a report listing it 400 times would bury the one line
        # that matters. The LOCATION kept is the FIRST one, which is where a reviewer
        # should start looking, and the count is carried so the scale is not lost.
        self.detector_failures: list[tuple[str, str, str]] = []  # [(detector, location, error)]
        self._failure_seen: dict[tuple[str, str], int] = {}      # (detector, error) -> index
        self._failure_counts: dict[tuple[str, str], int] = {}

    def group_key(self, cand) -> tuple:
        """Identity key for ``cand`` WITHIN its type. MENO resolves to its party via declension;
        everything else keys on the normalized surface."""
        return self.group_key_for(cand.type, cand.surface)

    def group_key_for(self, type: str, surface: str) -> tuple:
        """Same identity, computable without a Candidate (GUI resolves decision keys from
        harvested (type, surface) pairs)."""
        if type == "MENO":
            for i, entity in enumerate(self._known):
                if match_entity(surface, entity):
                    return ("entity", i)
            return ("surface", normalize(surface))  # defensive fallback
        return ("surface", normalize(surface))

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

    def record_occurrence(self, label: str, location: str, surface: str, snippet: str = "",
                          checksum: str = "n/a") -> None:
        """Append ONE redacted-span record. Called for EVERY kept (auto=True) occurrence,
        including repeats of an already-numbered label — never deduped.

        The appended tuple shape is UNCHANGED (``(location, surface)``): build_report unpacks it
        positionally. ``checksum`` lands in the parallel ``checksums`` map, FIRST-SEEN wins —
        the same first-occurrence-wins rule ``contexts`` uses, so a label's reported checksum is
        the one from the occurrence that minted it and cannot flip between repeats."""
        self.occurrences.setdefault(label, []).append((location, surface))
        if snippet and label not in self.contexts:
            self.contexts[label] = snippet
        self.checksums.setdefault(label, checksum)

    def record_low_confidence(self, location: str, type: str, surface: str, snippet: str = "",
                              checksum: str = "n/a") -> None:
        """Append ONE low-confidence (auto=False) record: a span detect() flagged for review
        that the pass leaves UNREDACTED and UNLABELLED. Tuple shape UNCHANGED; the checksum is
        appended to ``lc_checksums``, index-aligned exactly like ``lc_contexts``."""
        self.low_confidence.append((location, type, surface))
        self.lc_contexts.append(snippet)
        self.lc_checksums.append(checksum)

    def record_detector_failure(self, detector: str, location: str, error: str) -> None:
        """Record that ``detector`` raised at ``location``. Idempotent per (detector, error).

        A detector that chokes on one character shape chokes on it in every paragraph that
        contains it, so the honest report is 'this detector failed, first at <location>,
        <n> times' -- not four hundred identical rows."""
        key = (detector, error)
        self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
        if key in self._failure_seen:
            i = self._failure_seen[key]
            first_location = self.detector_failures[i][1].split(" (")[0]
            self.detector_failures[i] = (
                detector,
                f"{first_location} (+{self._failure_counts[key] - 1} more)",
                error,
            )
            return
        self._failure_seen[key] = len(self.detector_failures)
        self.detector_failures.append((detector, location, error))

    def groups(self) -> dict[str, tuple[str, tuple]]:
        """label -> (type, group_key) for every label minted so far — the GUI's bridge from
        harvested labels back to decision keys."""
        return {label: key for key, label in self._cache.items()}
