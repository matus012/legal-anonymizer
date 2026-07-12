"""Kúpna zmluva (nehnuteľnosť) — property purchase contract."""
from __future__ import annotations

from . import _common


def build(b, rng, bank, *, is_docx: bool) -> None:
    rec = b.rec
    p1 = _common.make_person(rng, bank, rec, "predavajuci")
    p2 = _common.make_person(rng, bank, rec, "kupujuci")
    people = [(p1, "predavajuci"), (p2, "kupujuci")]

    b.heading("Kúpna zmluva")
    b.paragraph([
        "uzavretá podľa § 588 a nasl. Občianskeho zákonníka medzi predávajúcim ",
        _common.name_spec(p1, "ins", "predavajuci", "full"),
        " a kupujúcim ",
        _common.name_spec(p2, "ins", "kupujuci", "full"), ".",
    ])
    ids = _common.identifier_specs(rng)
    _common.seed_all(b, rng, bank, rec, is_docx=is_docx, ids=ids, people=people)
    b.paragraph(["Zmluvné strany vyhlasujú, že zmluvu uzavreli slobodne a vážne."])
