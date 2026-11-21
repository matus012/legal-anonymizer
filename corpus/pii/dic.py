"""DIČ (tax id) — 10 digits (context.md §4.1). No public checksum is specified, so the
value is a plausible 10-digit number beginning with a non-zero digit."""
from __future__ import annotations

import random


def generate(rng: random.Random) -> str:
    return str(rng.randint(2_000_000_000, 2_999_999_999))
