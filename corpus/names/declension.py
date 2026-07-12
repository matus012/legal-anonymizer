"""Load the curated tables and expose Person / Place with declined surface forms (§5).

The ``Person.variants`` builder produces the *same* individual written inconsistently
(``Ján Novák`` / ``J. Novák`` / ``Novák`` / ``p. Novák``) — all one entity in ground truth —
while ``all_case_mentions`` yields the full name and the bare surname in every case.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

CASES = ("nom", "gen", "dat", "acc", "loc", "ins")
_DATA = Path(__file__).parent / "data"


@dataclass
class Person:
    gender: str  # "male" | "female"
    first: dict  # case -> form
    last: dict   # case -> form (gender-appropriate)
    family_nom: str
    family_gen: str

    @property
    def canonical(self) -> str:
        return f"{self.first['nom']} {self.last['nom']}"

    def full(self, case: str) -> str:
        return f"{self.first[case]} {self.last[case]}"

    def surname(self, case: str) -> str:
        return self.last[case]

    def honorific(self) -> str:
        return f"p. {self.last['nom']}"

    def initial(self) -> str:
        return f"{self.first['nom'][0]}. {self.last['nom']}"

    def variants(self) -> list[tuple[str, str]]:
        """Inconsistent renderings of the SAME person (surface, style)."""
        return [
            (self.canonical, "full"),
            (self.initial(), "initial"),
            (self.last["nom"], "surname_only"),
            (self.honorific(), "honorific"),
        ]

    def all_case_mentions(self) -> list[tuple[str, str, str]]:
        """(surface, grammatical_case, kind) for the full name and bare surname, all cases."""
        out: list[tuple[str, str, str]] = []
        for c in CASES:
            out.append((self.full(c), c, "full"))
            out.append((self.surname(c), c, "surname"))
        return out


@dataclass
class Place:
    kind: str
    rhythmic: bool
    forms: dict = field(default_factory=dict)

    @property
    def nom(self) -> str:
        return self.forms["nom"]

    def form(self, case: str) -> str:
        return self.forms[case]

    def all_case_mentions(self) -> list[tuple[str, str]]:
        return [(self.forms[c], c) for c in CASES]


class NameBank:
    def __init__(self, names: dict, places: dict):
        self._first = names["first_names"]
        self._surnames = names["surnames"]
        self._places = places["places"]

    @classmethod
    def load(cls) -> "NameBank":
        names = json.loads((_DATA / "names.json").read_text(encoding="utf-8"))
        places = json.loads((_DATA / "places.json").read_text(encoding="utf-8"))
        return cls(names, places)

    def person(self, rng: random.Random, gender: str | None = None) -> Person:
        gender = gender or rng.choice(("male", "female"))
        first = rng.choice(self._first[gender])
        surname = rng.choice(self._surnames)
        last = surname[gender]
        male = surname["male"]
        return Person(
            gender=gender,
            first={c: first[c] for c in CASES},
            last={c: last[c] for c in CASES},
            family_nom=male["family_nom"],
            family_gen=male["family_gen"],
        )

    def place(
        self,
        rng: random.Random,
        kind: str | None = None,
        rhythmic: bool | None = None,
    ) -> Place:
        pool = self._places
        if kind is not None:
            pool = [p for p in pool if p["kind"] == kind]
        if rhythmic is not None:
            pool = [p for p in pool if p["rhythmic"] == rhythmic]
        p = rng.choice(pool)
        return Place(kind=p["kind"], rhythmic=p["rhythmic"], forms={c: p[c] for c in CASES})
