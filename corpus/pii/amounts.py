"""Monetary amounts in mixed Slovak formats (context.md §4.1).

Slovak convention: comma decimal separator, non-breaking/normal space thousands separator,
currency after the number (``€`` / ``EUR`` / legacy ``Sk``). Both the NBSP and the normal-space
variants are seeded on purpose so the detector must handle both (context.md revision to §7).
"""
from __future__ import annotations

import random

NBSP = chr(0xA0)  # non-breaking space (U+00A0)


def _group(value: int, sep: str) -> str:
    return f"{value:,}".replace(",", sep)


def generate(rng: random.Random) -> str:
    thin = NBSP if rng.random() < 0.5 else " "
    cur = NBSP if rng.random() < 0.5 else " "
    euros = rng.randint(50, 950_000)
    cents = rng.choice([0, 0, 50, rng.randint(1, 99)])
    style = rng.choice(("eur_symbol", "eur_word", "dash_cents", "sk_legacy"))
    grouped = _group(euros, thin)
    if style == "eur_symbol":
        return f"{grouped},{cents:02d}{cur}€"
    if style == "eur_word":
        return f"{grouped},{cents:02d}{cur}EUR"
    if style == "dash_cents":
        return f"{grouped},-{cur}€"
    return f"{_group(euros * 30, thin)}{cur}Sk"
