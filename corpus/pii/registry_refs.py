"""Court / cadastral / registry references (context.md §4.1).

Covers: číslo LV, číslo parcely (incl. KN-C / KN-E registers), číslo vložky ORSR, and
spisová značka (court/admin file marks such as V-1234/2025, Z-567/2025, P-89/2025).
"""
from __future__ import annotations

import random

_ORSR_SECTIONS = ("Sro", "Sa", "Pš", "Dr")
_SPIS_PREFIXES = ("V", "Z", "P", "X", "R")
_COURT_AGENDA = ("C", "Cb", "Ro", "Er", "T", "D")


def lv(rng: random.Random) -> str:
    return f"LV č. {rng.randint(1, 9999)}"


def parcela(rng: random.Random) -> str:
    num = rng.randint(1, 4999)
    style = rng.choice(("plain", "sub", "kn_c", "kn_e"))
    if style == "plain":
        return f"parc. č. {num}"
    if style == "sub":
        return f"parc. č. {num}/{rng.randint(1, 99)}"
    reg = "C" if style == "kn_c" else "E"
    return f"parcela registra „{reg}“ KN č. {num}/{rng.randint(1, 99)}"


def orsr_vlozka(rng: random.Random) -> str:
    return (
        f"Oddiel: {rng.choice(_ORSR_SECTIONS)}, "
        f"Vložka č. {rng.randint(100, 99999)}/{rng.choice('VBTNZ')}"
    )


def spisova_znacka(rng: random.Random) -> str:
    style = rng.choice(("cadastral", "court"))
    year = rng.randint(2015, 2025)
    if style == "cadastral":
        return f"{rng.choice(_SPIS_PREFIXES)}-{rng.randint(1, 9999)}/{year}"
    return f"{rng.randint(1, 40)}{rng.choice(_COURT_AGENDA)}/{rng.randint(1, 999)}/{year}"
