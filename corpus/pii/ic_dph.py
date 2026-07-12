"""IČ DPH (VAT id) — ``SK`` + DIČ (context.md §4.1)."""
from __future__ import annotations

import random

from . import dic


def generate(rng: random.Random) -> str:
    return "SK" + dic.generate(rng)
