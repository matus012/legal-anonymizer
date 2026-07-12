"""Výpis z listu vlastníctva — extract from the land registry sheet."""
from __future__ import annotations

from . import _common


def build(b, rng, bank, *, is_docx: bool) -> None:
    rec = b.rec
    p1 = _common.make_person(rng, bank, rec, "vlastnik")
    p2 = _common.make_person(rng, bank, rec, "spoluvlastnik")
    people = [(p1, "vlastnik"), (p2, "spoluvlastnik")]

    b.heading("Výpis z listu vlastníctva")
    b.paragraph([
        "Úrad geodézie, kartografie a katastra. Vlastník ",
        _common.name_spec(p1, "nom", "vlastnik", "full"),
        " v podiele 1/1.",
    ])
    ids = _common.identifier_specs(rng)
    _common.seed_all(b, rng, bank, rec, is_docx=is_docx, ids=ids, people=people)
    b.paragraph(["Časť B: vlastníci a iné oprávnené osoby. Časť C: ťarchy."])
