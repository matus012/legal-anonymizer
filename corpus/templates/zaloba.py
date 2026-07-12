"""Žaloba — statement of claim (civil action)."""
from __future__ import annotations

from . import _common


def build(b, rng, bank, *, is_docx: bool) -> None:
    rec = b.rec
    p1 = _common.make_person(rng, bank, rec, "zalobca")
    p2 = _common.make_person(rng, bank, rec, "zalovany")
    people = [(p1, "zalobca"), (p2, "zalovany")]

    b.heading("Žaloba o zaplatenie")
    b.paragraph([
        "Okresnému súdu. Žalobca ",
        _common.name_spec(p1, "nom", "zalobca", "full"),
        " proti žalovanému ",
        _common.name_spec(p2, "dat", "zalovany", "full"),
        " o zaplatenie dlžnej sumy.",
    ])
    ids = _common.identifier_specs(rng)
    _common.seed_all(b, rng, bank, rec, is_docx=is_docx, ids=ids, people=people)
    b.paragraph(["Žalobca navrhuje, aby súd žalobe v celom rozsahu vyhovel."])
