"""The bundled-data startup self-check (detect/selfcheck.py), including a FROZEN-LAYOUT test.

THE POINT OF THE FROZEN-LAYOUT TEST
--------------------------------------------------------------------------------------
``detect/gazetteer.py:_data_dir()`` has two branches: under ``sys._MEIPASS`` when frozen, and
next to the package otherwise. Every test in this repo, and every run on the developer's
machine, takes the SECOND branch — which is exactly why the first one can be broken for
months without anyone noticing. The data files are found on disk next to the source no matter
what ``anonymizer.spec`` says, so a spec that has stopped bundling them looks identical to one
that still does, right up until the .exe reaches a lawyer's laptop and quietly stops redacting
every municipality, street and surname in the country.

So these tests SIMULATE the frozen layout: set ``sys.frozen`` and ``sys._MEIPASS``, point them
at a directory we control, clear the loader's caches, and assert on what detection actually
does. That exercises the branch the suite otherwise never touches. It is not a substitute for
running the real .exe on a clean machine — nothing is — but it turns "we hope the spec is
right" into "the code path is tested and the data requirement is enforced at startup".
"""
import json
import os
import shutil
import sys

import pytest

from detect import gazetteer
from detect.core import detect
from detect.selfcheck import REQUIRED_DATA, describe_environment, verify_bundled_data


def _real_data_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(gazetteer.__file__)), "gazetteer_data")


def _clear_caches() -> None:
    """The loader memoises per filename, so a test that changes the data directory without
    clearing them measures the PREVIOUS directory and passes for the wrong reason."""
    gazetteer._load_names.cache_clear()
    gazetteer._index.cache_clear()


@pytest.fixture
def frozen(monkeypatch, tmp_path):
    """Pretend to be a PyInstaller build whose _MEIPASS is ``tmp_path``."""
    def _activate(copy_data: bool = True):
        meipass = tmp_path / "meipass"
        target = meipass / "detect" / "gazetteer_data"
        target.mkdir(parents=True)
        if copy_data:
            for name in os.listdir(_real_data_dir()):
                src = os.path.join(_real_data_dir(), name)
                if os.path.isfile(src):
                    shutil.copy(src, target / name)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        _clear_caches()
        return target

    yield _activate
    _clear_caches()


# --------------------------------------------------------------------------- source tree
def test_the_source_tree_passes_its_own_self_check():
    assert verify_bundled_data() == []


def test_describe_environment_names_the_branch_and_the_path():
    """The frozen/unfrozen distinction is the single most useful fact when this check fails,
    because those two branches are exactly what diverges between the build machine and the
    machine that runs the app."""
    out = describe_environment()
    assert "zdrojový strom" in out
    assert "gazetteer_data" in out


def test_every_required_file_actually_exists_in_the_repo():
    """Guards against the list and the repo drifting apart — a required file that no longer
    ships would make the check fail for everyone, and a shipped file missing from the list is
    a file nothing verifies."""
    present = set(os.listdir(_real_data_dir()))
    assert set(REQUIRED_DATA) <= present


# --------------------------------------------------------------------------- frozen layout
def test_detection_works_under_the_frozen_layout(frozen):
    """The branch the rest of the suite never takes. Asserts on HITS, not on file existence:
    the failure being guarded against is not "the file is absent", it is "the gazetteer
    matches nothing", and only a detection result can tell those apart."""
    frozen()
    assert verify_bundled_data() == []
    hits = [c for c in detect("Nehnuteľnosť sa nachádza v obci Košice, okres Košice I.")
            if c.type in ("OBEC", "KATASTER")]
    assert hits, "the frozen layout found no place names — the bundled data is not reachable"


def test_the_self_check_fails_when_the_data_directory_is_absent(frozen, monkeypatch):
    frozen()
    monkeypatch.setattr(sys, "_MEIPASS", os.path.join(os.sep, "nonexistent-meipass"))
    _clear_caches()
    problems = verify_bundled_data()
    assert problems and "chýba" in problems[0].lower()


def test_the_self_check_fails_when_one_file_is_missing(frozen):
    target = frozen()
    os.remove(target / "obce.json")
    _clear_caches()
    problems = verify_bundled_data()
    assert any("obce.json" in p for p in problems)


def test_the_self_check_fails_when_a_file_is_present_but_EMPTY(frozen):
    """The case a mere existence check would pass. An empty list fails in exactly the same
    invisible way as an absent file: no crash, no error, and every place name left in the
    document."""
    target = frozen()
    (target / "obce.json").write_text("[]", encoding="utf-8")
    _clear_caches()
    problems = verify_bundled_data()
    assert any("obce.json" in p and "prázdny" in p for p in problems)


def test_the_self_check_fails_when_a_file_is_truncated(frozen):
    target = frozen()
    (target / "surnames.json").write_text('["Novak", "Horak"]', encoding="utf-8")
    _clear_caches()
    problems = verify_bundled_data()
    assert any("surnames.json" in p for p in problems)


def test_the_self_check_fails_on_corrupt_json(frozen):
    target = frozen()
    (target / "ulice.json").write_text('["Hlavna", ', encoding="utf-8")
    _clear_caches()
    problems = verify_bundled_data()
    assert any("ulice.json" in p and "poškodený" in p for p in problems)


def test_the_self_check_fails_on_the_wrong_json_shape(frozen):
    target = frozen()
    (target / "first_names.json").write_text('{"a": 1}', encoding="utf-8")
    _clear_caches()
    problems = verify_bundled_data()
    assert any("first_names.json" in p and "formát" in p for p in problems)


def test_all_problems_are_reported_at_once(frozen):
    """A user told about one missing file, who fixes it and is then told about the next,
    learns to distrust the message."""
    target = frozen()
    os.remove(target / "obce.json")
    os.remove(target / "ulice.json")
    (target / "surnames.json").write_text("[]", encoding="utf-8")
    _clear_caches()
    problems = verify_bundled_data()
    assert len(problems) >= 3
