"""STARTUP SELF-CHECK for the bundled gazetteer data (sprint brief, priority 8).

THE FAILURE THIS EXISTS TO PREVENT
--------------------------------------------------------------------------------------
``detect/gazetteer_data/*.json`` are plain data files. PyInstaller's import analysis cannot
see them, so they are bundled only because ``anonymizer.spec`` names them explicitly. If that
line is ever dropped, mistyped, or defeated by a path change, the frozen application still
starts, still scans, still writes a redacted document and still writes a report — and
silently stops redacting every municipality, street, cadastral area, first name and surname
in the country.

THAT IS THE WORST SHAPE A BUG CAN HAVE IN THIS TOOL. There is no crash, no error dialog and
no empty output. The report looks ordinary, just shorter. A missing row is indistinguishable
from a document that did not contain one, so the reviewer has nothing to notice. And it
cannot be caught on the developer's machine, where the files sit next to the source and are
found by the non-frozen branch of ``_data_dir()`` no matter what the spec says. The test
suite cannot catch it either, for the same reason: the suite never runs the frozen layout.

So the application checks, out loud, at startup, and REFUSES TO SCAN rather than scan
badly. A tool that under-redacts without saying so is worse than a tool that will not open.

WHY EMPTINESS IS CHECKED AND NOT JUST EXISTENCE
--------------------------------------------------------------------------------------
A file that exists, parses, and contains ``[]`` fails in exactly the same invisible way as a
file that is absent. So does a file truncated by a bad copy. The minimum counts below are
floors far under the real sizes — they are there to catch "present but useless", not to pin
the data's exact contents, which change when the gazetteer is rebuilt from source.
"""
from __future__ import annotations

import json
import os
import sys

from .gazetteer import _data_dir

# filename -> the fewest entries a usable file can have. Deliberately far below the real
# counts (obce 2842, ulice 12000, katastralne uzemia 3416, first names 481, surnames 1169)
# so a legitimate gazetteer rebuild never trips this, while [] and a truncated copy both do.
REQUIRED_DATA: dict[str, int] = {
    "obce.json": 1000,
    "ulice.json": 1000,
    "katastralne_uzemia.json": 1000,
    "first_names.json": 100,
    "surnames.json": 100,
    # The stoplist is the one file whose job is to REMOVE matches -- Slovak municipality names
    # that are also ordinary words. A missing stoplist does not silently under-redact, it
    # over-redacts loudly, so its floor is low. It is still required: shipping without it
    # means the reviewer drowns in false rows and stops reading them, which ends in the same
    # place by a longer road.
    "stoplist.json": 1,
}


def verify_bundled_data() -> list[str]:
    """Check every bundled data file. Returns a list of human-readable problems; empty = good.

    Returns problems rather than raising, so the caller can show ALL of them at once. A user
    told about one missing file, who fixes it and is then told about the next, learns to
    distrust the message.
    """
    problems: list[str] = []
    directory = _data_dir()

    if not os.path.isdir(directory):
        return [
            f"Datový adresár gazetteera chýba: {directory}. "
            "Aplikácia nemôže rozpoznávať obce, ulice, katastrálne územia ani mená."
        ]

    for filename, minimum in sorted(REQUIRED_DATA.items()):
        path = os.path.join(directory, filename)
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except OSError:
            problems.append(f"chýba alebo sa nedá čítať: {filename}")
            continue
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            problems.append(f"poškodený súbor: {filename} ({exc})")
            continue

        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            problems.append(f"nesprávny formát (očakáva sa JSON pole reťazcov): {filename}")
        elif len(raw) < minimum:
            problems.append(
                f"podozrivo prázdny: {filename} má {len(raw)} položiek, "
                f"očakáva sa aspoň {minimum}"
            )
    return problems


def describe_environment() -> str:
    """One line naming where the data was looked for, for the error dialog and bug reports.

    The frozen/unfrozen distinction is the single most useful fact when this check fails,
    because the two branches of ``_data_dir()`` are exactly what diverges between the machine
    that built the app and the machine that runs it."""
    kind = "frozen (PyInstaller)" if getattr(sys, "frozen", False) else "zdrojový strom"
    return f"{kind}: {_data_dir()}"
