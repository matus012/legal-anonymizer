"""The v1.1 REVIEW-BUCKET population — a bare, unanchored personal name (CONTRACTS_v11.md
§6/§7, policy A1).

Why this file exists
--------------------
Policy A1 demoted the checksum from a FILTER to a TAG: a shape-valid but checksum-invalid
identifier is now auto-redacted and merely tagged ``checksum="invalid"`` (contract §6), and
``corpus/groundtruth.py``'s three-state decision moved with it (contract §7). The consequence
is spelled out in §7 itself: ``should_flag`` becomes EMPTY for every identifier type. That
left ``EvalOutcome.flag_survival_ok`` passing vacuously and — worse — unfireable by any
baseline, i.e. a gate that had never been proven to work.

What the review bucket actually IS under v1.1 is not a policy choice made here; it is
whatever the shipped detector puts there with ``auto=False``. Measured against
``detect.core.detect`` (not assumed — see the verification note below), that is the
**bare-name heuristic** of ``detect/name_anchors.py``: 2-3 capitalised tokens, mid-sentence,
no stoplisted token, and **no title / role / field-label anchor** confirming them. Weak
evidence, so it arrives unticked and a human decides.

The three conditions this generator has to satisfy, and why each one is load-bearing
------------------------------------------------------------------------------------
1. **Mid-sentence.** ``detect/name_anchors.py::_at_sentence_start`` refuses the first token
   of a sentence outright (a capitalised sentence opener carries no name evidence at all), so
   every frame below puts at least two lowercase words in front of the name.
2. **No anchor.** A title (``JUDr.``), a role word (``predávajúci``) or a field label
   (``Meno a priezvisko:``) would make the same name ``auto=True`` — the anchored buckets,
   not this one. The frames are deliberately built out of ordinary narrative verbs, and every
   frame is checked against the role-stem list (``_ROLE_STEMS``): a lead-in such as
   "svedok"/"účastník"/"zástupca" would silently convert this fixture into an auto item.
3. **Unknown to the gazetteer.** This is the condition that is NOT obvious and that a
   hand-waved fixture gets wrong. ``detect/gazetteer.py`` emits ``MENO`` with ``auto=True``
   for *a given name from its register immediately followed by a capitalised token* — so
   "Radoslav Zúbek" comes back ``auto=True`` even though ``detect_name_anchors`` alone rates
   it ``auto=False``. A review-bucket fixture therefore needs a given name that is NOT in
   ``detect/gazetteer_data/first_names.json`` and a surname that is NOT in ``surnames.json``.
   The two pools below were selected by running the real ``detect()`` over every
   frame x first-name x surname combination and keeping only those that come back as exactly
   one candidate, ``MENO``, ``auto=False``. That is what makes this the HONEST population:
   it is what the shipped detector does, verified, not what the corpus wishes it did.

The pools are also disjoint from ``corpus/names/data/names.json`` (the document's own
entities) so the seeded surface can never collide with a real, auto-redact MENO in the same
document — ``eval/metrics.py::_unique_by_class`` subtracts any surface that is auto anywhere
in the document out of the flag class, which would quietly empty the bucket again.
"""
from __future__ import annotations

import random

from ..groundtruth import PiiSpec

# Given names absent from detect/gazetteer_data/first_names.json AND from the corpus's own
# name bank. Archaic/calendar Slovak given names: plausible in a real document, unknown to a
# frequency-built register — which is exactly the evidence situation the review bucket is for.
_FIRST = (
    "Aurélius", "Perpetua", "Nepomuk", "Kornélius", "Sixtus", "Serafína",
    "Eulália", "Silvestrína", "Kasián", "Teodozius", "Leopoldína", "Hermenegild",
    "Anastázius", "Gervázius", "Prokopína",
)
# Surnames absent from detect/gazetteer_data/surnames.json and from the corpus name bank.
_LAST = (
    "Zúbek", "Mrkvička", "Chrapek", "Štverák", "Kadlubiec", "Vrábeľ",
    "Hlucháň", "Šmatlák", "Petrušek", "Zemanovič", "Ondrušiak", "Brezovský",
)
# Narrative frames. Every lead-in is lowercase and at least two tokens long (condition 1) and
# carries no title, role word or field label (condition 2). ``{name}`` never starts or ends
# the sentence, so the bare-name pattern sees it mid-sentence with ordinary text on both
# sides — the situation a real document produces when a person is mentioned in passing.
_FRAMES = (
    "Do miestnosti vstúpil {name} a posadil sa.",
    "Na chodbe čakal {name} s dokladmi.",
    "V protokole je uvedený {name} bez ďalšieho upresnenia.",
)


def make_bare_name(rng: random.Random) -> tuple[str, PiiSpec]:
    """``(sentence to place, ground truth for the name inside it)``.

    The sentence is ordinary document text that must SURVIVE redaction; only ``spec.surface``
    (the name) is the recorded surface. Bucket: ``auto_redact=False, should_flag=True,
    checksum="n/a"`` — the review bucket, per contract §7. It must never be auto-redacted,
    which is precisely what ``EvalOutcome.flag_survival_ok`` gates.
    """
    name = f"{rng.choice(_FIRST)} {rng.choice(_LAST)}"
    placed = rng.choice(_FRAMES).format(name=name)
    return placed, PiiSpec(
        surface=name, type="MENO", auto_redact=False, should_flag=True, checksum="n/a"
    )
