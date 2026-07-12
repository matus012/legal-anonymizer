"""Návrh na vklad do katastra nehnuteľností — cadastral registration petition."""
from __future__ import annotations

from . import _common


def build(b, rng, bank, *, is_docx: bool) -> None:
    rec = b.rec
    p1 = _common.make_person(rng, bank, rec, "navrhovatel")
    p2 = _common.make_person(rng, bank, rec, "ucastnik")
    people = [(p1, "navrhovatel"), (p2, "ucastnik")]

    b.heading("Návrh na vklad do katastra nehnuteľností")
    b.paragraph([
        "Okresný úrad, katastrálny odbor. Navrhovateľ ",
        _common.name_spec(p1, "nom", "navrhovatel", "full"),
        " navrhuje povolenie vkladu vlastníckeho práva.",
    ])
    ids = _common.identifier_specs(rng)
    _common.seed_all(b, rng, bank, rec, is_docx=is_docx, ids=ids, people=people)
    b.paragraph(["Prílohou návrhu je kúpna zmluva a správny poplatok."])
