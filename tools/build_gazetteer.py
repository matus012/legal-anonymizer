"""Build the bundled gazetteer JSON from the downloaded open-data sources.

Dev-only tool. It is NOT imported by the application, by ``detect/``, by ``eval/`` or by the
PyInstaller build — it exists so the bundled lists in ``detect/gazetteer_data/*.json`` are
REPRODUCIBLE rather than a pile of hand-edited data nobody can regenerate or audit.

    .\\.venv\\Scripts\\python.exe -m tools.build_gazetteer

Inputs are the raw downloads in ``detect/gazetteer_data/_raw/`` (gitignored — see
LICENSES.md for every source URL, its licence and its download date). Outputs are the small
normalised JSON lists that ARE committed and ARE bundled into the .exe.

Every source is CC0 or CC BY 4.0. Nothing derived from a data breach or a scraped social
network is used — see LICENSES.md "Rejected sources".
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import re
import unicodedata

RAW = pathlib.Path("detect/gazetteer_data/_raw")
OUT = pathlib.Path("detect/gazetteer_data")

# A "current" row in the Register adries CSVs carries validTo far in the future (the register
# uses 3000-12-31 as its open-ended sentinel) or leaves it empty. Historical rows carry a real
# past date and are dropped: a municipality renamed in 1997 is not an address a 2026 contract
# uses, and keeping it only widens the false-positive surface.
_OPEN_ENDED = ("3000-", "")


def _read_csv(name: str) -> list[dict]:
    text = RAW.joinpath(name).read_text(encoding="utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text)))


def _is_current(row: dict) -> bool:
    valid_to = (row.get("validTo") or "").strip()
    return valid_to == "" or valid_to.startswith("3000-")


def _clean(name: str) -> str:
    """Collapse internal whitespace and strip. Register rows carry stray double spaces."""
    return re.sub(r"\s+", " ", (name or "").strip())


def strip_diacritics(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)
    )


# --------------------------------------------------------------- head-city derivation
# The Register adries lists Slovakia's two biggest cities ONLY by borough: there are 22
# "Košice-*" rows and 17 "Bratislava-*" rows but no bare "Košice" and no bare "Bratislava".
# A contract that says "trvale bytom Hlavná 12, 040 01 Košice" would therefore miss the town
# entirely — a recall failure in the most common address in the country. So for every
# hyphenated entry we also add the head part before the first hyphen. Over-adding a place
# name is the safe direction (context.md §6, recall over precision): the head of a hyphenated
# Slovak municipality name is itself a real toponym, and the common-word stoplist below is
# what guards against a place name that is also an ordinary word.
def _with_head_city_names(names: set[str]) -> set[str]:
    out = set(names)
    for name in names:
        head = _clean(name.split("-", 1)[0]) if "-" in name else ""
        if len(head) >= 3 and head[0].isupper():
            out.add(head)
    return out


# ---------------------------------------------------------------------------- obce
def build_obce() -> list[str]:
    rows = _read_csv("obce_raw.csv")
    names = {
        _clean(r["municipalityName"])
        for r in rows
        if _is_current(r) and _clean(r.get("municipalityName", ""))
    }
    # "Neznáma" is the register's own placeholder row for an unknown municipality, not a place.
    names.discard("Neznáma")
    return sorted(_with_head_city_names(names))


# ---------------------------------------------------------------------------- ulice
def build_ulice() -> list[str]:
    rows = _read_csv("ulice_raw.csv")
    names = {
        _clean(r["streetName"])
        for r in rows
        if _is_current(r) and _clean(r.get("streetName", ""))
    }
    return sorted(names)


# ------------------------------------------------------------------ katastrálne územia
def build_katastralne_uzemia() -> list[str]:
    """CL000026 codelist export. The item name is column "Názov položky"; the header is
    Slovak with diacritics, so match the column by its diacritic-stripped, lowercased form
    rather than by a literal that depends on this file's own encoding surviving intact."""
    text = RAW.joinpath("katastralne_uzemia_raw.csv").read_text(
        encoding="utf-8-sig", errors="replace"
    )
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    wanted = "nazov polozky"
    idx = next(
        (i for i, h in enumerate(header) if strip_diacritics(h).strip().lower() == wanted),
        None,
    )
    if idx is None:  # header mangled by the export's encoding — fall back to the known index
        idx = 13
    # "Koniec účinnosti položky" (item end-of-validity) is the last-but-three column; a row
    # with a value there is a retired cadastral area.
    end_idx = next(
        (
            i
            for i, h in enumerate(header)
            if strip_diacritics(h).strip().lower() == "koniec ucinnosti polozky"
        ),
        None,
    )
    names = set()
    for row in reader:
        if idx >= len(row):
            continue
        if end_idx is not None and end_idx < len(row) and row[end_idx].strip():
            continue
        name = _clean(row[idx])
        if name:
            names.add(name)
    return sorted(_with_head_city_names(names))


# ---------------------------------------------------------------------------- names
def _read_lines(name: str) -> list[str]:
    text = RAW.joinpath(name).read_text(encoding="utf-8", errors="replace")
    return [_clean(l) for l in text.splitlines() if _clean(l)]


def build_first_names() -> list[str]:
    """Union of the CC0 generator name lists and the MIT meniny (name-day) calendar."""
    names = set(_read_lines("names.male.txt")) | set(_read_lines("names.female.txt"))
    nd = json.loads(RAW.joinpath("names_namedays.json").read_text(encoding="utf-8"))
    # The name-day file is a list of records; harvest every string field that looks like a
    # single capitalised given name, so the exact record shape is not load-bearing.
    def harvest(node):
        if isinstance(node, str):
            for part in re.split(r"[,/]", node):
                part = _clean(part)
                if re.fullmatch(r"[A-ZÁÄČĎÉÍĽĹŇÓÔŔŠŤÚÝŽ][a-záäčďéíľĺňóôŕšťúýž]{2,}", part):
                    names.add(part)
        elif isinstance(node, dict):
            for v in node.values():
                harvest(v)
        elif isinstance(node, list):
            for v in node:
                harvest(v)

    harvest(nd)
    return sorted(names)


def build_surnames() -> list[str]:
    return sorted(set(_read_lines("surnames.male.txt")) | set(_read_lines("surnames.female.txt")))


# ---------------------------------------------------------------------------- stoplist
# Obce / street names that are ALSO ordinary Slovak words or legal-document vocabulary. A
# gazetteer hit on one of these inside running prose is a false positive that would redact a
# normal sentence, so they are excluded from the AUTO bucket. They are NOT deleted from the
# gazetteer: the same string preceded by an address anchor is still matched, because there
# the address context — not the word itself — is what makes it a place name.
COMMON_WORD_STOPLIST = sorted({
    # ordinary nouns/adjectives that are also municipality names
    "Bystré", "Bzince", "Časť", "Dedina", "Dolina", "Dolné", "Dolný", "Horné", "Horný",
    "Hora", "Hory", "Hrad", "Jarok", "Kopec", "Kostol", "Kríž", "Lehota", "Les", "Lipa",
    "Lom", "Lúka", "Lúky", "Most", "Nižné", "Nová", "Nové", "Nový", "Pole", "Potok",
    "Prameň", "Rieka", "Sad", "Sady", "Skala", "Sklené", "Stará", "Staré", "Starý",
    "Stráne", "Stred", "Studená", "Studené", "Vrch", "Vyšné", "Záhrada", "Zálesie",
    "Zemné", "Hviezda", "Dubina", "Brezina", "Breza", "Buk", "Dub", "Lipany",
    # legal-document vocabulary that collides with place or street names
    "Článok", "Príloha", "Strana", "Zmluva", "Predmet", "Cena", "Doba", "Právo", "Súd",
    "Návrh", "Vklad", "List", "Konanie", "Rozhodnutie", "Uznesenie", "Rozsudok",
    "Republika", "Obec", "Mesto", "Okres", "Kraj", "Ulica", "Námestie", "Trieda", "Cesta",
})


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "obce.json": build_obce(),
        "ulice.json": build_ulice(),
        "katastralne_uzemia.json": build_katastralne_uzemia(),
        "first_names.json": build_first_names(),
        "surnames.json": build_surnames(),
        "stoplist.json": COMMON_WORD_STOPLIST,
    }
    for name, values in artifacts.items():
        path = OUT / name
        path.write_text(
            json.dumps(values, ensure_ascii=False, indent=0, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"{name:26s} {len(values):>7,} entries  {path.stat().st_size:>9,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
