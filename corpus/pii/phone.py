"""Slovak phone numbers in mixed surface formats (context.md §4.1 — added per §4).

Not on the office's original list; §4 says add it, so it is treated as first-class PII.
Group separators are a non-breaking space or a normal space (both seeded).
"""
from __future__ import annotations

import random

NBSP = chr(0xA0)  # non-breaking space (U+00A0)


def generate(rng: random.Random) -> str:
    s = NBSP if rng.random() < 0.5 else " "
    style = rng.choice(("mobile_intl", "mobile_local", "landline_intl", "landline_local"))
    a, b, c = rng.randint(100, 999), rng.randint(100, 999), rng.randint(100, 999)
    if style == "mobile_intl":
        pfx = rng.choice(("903", "905", "911", "915", "944", "948"))
        return f"+421{s}{pfx}{s}{a:03d}{s}{b:03d}"
    if style == "mobile_local":
        pfx = rng.choice(("0903", "0905", "0911", "0948"))
        return f"{pfx}{s}{a:03d}{s}{b:03d}"
    if style == "landline_intl":
        area = rng.choice(("2", "55", "41", "48", "51"))
        return f"+421{s}{area}{s}{a:04d}{s}{b:04d}"
    area = rng.choice(("02", "055", "041", "048", "051"))
    return f"{area}/{a:03d}{s}{b:02d}{s}{c:02d}"
