"""Výpis z Obchodného registra SR (ORSR) — commercial-register extract."""
from __future__ import annotations

from . import _common


def build(b, rng, bank, *, is_docx: bool) -> None:
    rec = b.rec
    p1 = _common.make_person(rng, bank, rec, "konatel")
    p2 = _common.make_person(rng, bank, rec, "spolocnik")
    people = [(p1, "konatel"), (p2, "spolocnik")]

    b.heading("Výpis z Obchodného registra SR")
    b.paragraph([
        "Okresný súd, obchodný register. Konateľ ",
        _common.name_spec(p1, "nom", "konatel", "full"),
        ", spoločník ",
        _common.name_spec(p2, "nom", "spolocnik", "full"), ".",
    ])
    ids = _common.identifier_specs(rng)
    _common.seed_all(b, rng, bank, rec, is_docx=is_docx, ids=ids, people=people)
    b.paragraph(["Údaje platné k dátumu vyhotovenia výpisu."])
