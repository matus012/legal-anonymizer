"""Monetary amounts in mixed Slovak formats (context.md §4.1).

Slovak convention: comma decimal separator, non-breaking/space thousands separator,
currency after the number (``€`` / ``EUR`` / legacy ``Sk``).
"""
from __future__ import annotations

import random


def _group(value: int) -> str:
    return f"{value:,}".replace(",", " ")  # 1 234 567 with NBSP thousands


def generate(rng: random.Random) -> str:
    euros = rng.randint(50, 950_000)
    cents = rng.choice([0, 0, 50, rng.randint(1, 99)])
    style = rng.choice(("eur_symbol", "eur_word", "dash_cents", "sk_legacy"))
    grouped = _group(euros)
    if style == "eur_symbol":
        return f"{grouped},{cents:02d} €"
    if style == "eur_word":
        return f"{grouped},{cents:02d} EUR"
    if style == "dash_cents":
        return f"{grouped},- €"
    return f"{_group(euros * 30)} Sk"  # legacy koruna, roughly ×30
