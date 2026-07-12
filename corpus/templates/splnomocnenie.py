"""Splnomocnenie — power of attorney."""
from __future__ import annotations

from . import _common


def build(b, rng, bank, *, is_docx: bool) -> None:
    rec = b.rec
    p1 = _common.make_person(rng, bank, rec, "splnomocnitel")
    p2 = _common.make_person(rng, bank, rec, "splnomocnenec")
    people = [(p1, "splnomocnitel"), (p2, "splnomocnenec")]

    b.heading("Splnomocnenie")
    b.paragraph([
        "Ja, dolupodpísaný ",
        _common.name_spec(p1, "nom", "splnomocnitel", "full"),
        ", splnomocňujem ",
        _common.name_spec(p2, "acc", "splnomocnenec", "full"),
        " na zastupovanie vo veci.",
    ])
    ids = _common.identifier_specs(rng)
    _common.seed_all(b, rng, bank, rec, is_docx=is_docx, ids=ids, people=people)
    b.paragraph(["Toto splnomocnenie platí do odvolania."])
