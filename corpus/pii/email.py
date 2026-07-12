"""E-mail addresses and URLs derived from a person/entity (context.md §4.1).

Diacritics are stripped for the local part so the address is realistic (``jan.novak@…``).
"""
from __future__ import annotations

import random
import unicodedata

_DOMAINS = ("gmail.com", "azet.sk", "centrum.sk", "post.sk", "zoznam.sk", "outlook.com")


def _ascii(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def from_name(rng: random.Random, first: str, last: str) -> str:
    local = f"{_ascii(first)}.{_ascii(last)}".replace(" ", "")
    return f"{local}@{rng.choice(_DOMAINS)}"


def generate(rng: random.Random) -> str:
    user = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(5, 9)))
    return f"{user}@{rng.choice(_DOMAINS)}"
