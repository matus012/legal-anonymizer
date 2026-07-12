"""Web addresses (context.md §4.1)."""
from __future__ import annotations

import random

_TLDS = ("sk", "com", "eu")


def generate(rng: random.Random) -> str:
    name = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(4, 10)))
    scheme = rng.choice(("www.", "https://www.", "http://", ""))
    return f"{scheme}{name}.{rng.choice(_TLDS)}"
