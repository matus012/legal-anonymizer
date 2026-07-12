"""Dates in the several Slovak surface formats (context.md §4.1, mixed-format failure mode).

Returns the surface string; the caller records it verbatim in ground truth. The same
logical date is rendered in a randomly chosen format so the corpus mixes formats.
"""
from __future__ import annotations

import datetime as _dt
import random

_MONTH_WORDS = (
    "januára", "februára", "marca", "apríla", "mája", "júna",
    "júla", "augusta", "septembra", "októbra", "novembra", "decembra",
)


def format_date(d: _dt.date, style: str) -> str:
    if style == "dotted":
        return f"{d.day}.{d.month}.{d.year}"
    if style == "spaced":
        return f"{d.day:02d}. {d.month:02d}. {d.year}"
    if style == "iso":
        return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"
    if style == "words":
        return f"{d.day}. {_MONTH_WORDS[d.month - 1]} {d.year}"
    raise ValueError(style)


STYLES = ("dotted", "spaced", "iso", "words")


def random_date(rng: random.Random, start_year: int = 1950, end_year: int = 2024) -> _dt.date:
    start = _dt.date(start_year, 1, 1)
    end = _dt.date(end_year, 12, 31)
    return start + _dt.timedelta(days=rng.randint(0, (end - start).days))


def generate(rng: random.Random, *, style: str | None = None, **kw) -> str:
    d = random_date(rng, **kw)
    return format_date(d, style or rng.choice(STYLES))
