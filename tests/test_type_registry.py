"""TDD spec for CONTRACTS_v11.md §4 — the type registry.

Two guarantees:

1. COVERAGE. Every type string any module under detect/ can hand to a Candidate is
   registered in _TYPE_PRECEDENCE. The literals are harvested from the detector SOURCE
   (not from a run), so a type that no fixture happens to exercise is still caught. This
   is the unit test §4 requires in place of a KeyError-raising rank lookup.
2. NO CRASH. Rank lookup of an UNREGISTERED type must not raise inside a shipped desktop
   app; it ranks last (len(_TYPE_PRECEDENCE)) and resolution keeps working.

corpus/ is never imported (CONTRACTS_v11.md §11).
"""
import pathlib
import re

from detect import core
from detect.core import KNOWN_TYPES, Candidate, _TYPE_PRECEDENCE, _TYPE_RANK, _rank

_DETECT_DIR = pathlib.Path(core.__file__).parent

# Scoped to the detector modules detect.core ACTUALLY dispatches to. A module sitting in
# detect/ that core.py does not import cannot emit anything into detect()'s output, and
# scanning the whole directory would make this gate fail on another round's half-wired
# file rather than on a real registry gap. The module list is derived from core.py's own
# imports, so wiring a new detector in automatically brings it under this test.
_WIRED_MODULE_RE = re.compile(r"^from \.(\w+) import", re.MULTILINE)


def _wired_modules() -> list[pathlib.Path]:
    core_src = pathlib.Path(core.__file__).read_text(encoding="utf-8")
    names = set(_WIRED_MODULE_RE.findall(core_src)) - {"config"}
    paths = [_DETECT_DIR / f"{n}.py" for n in sorted(names)]
    assert paths, "no detector modules found wired into detect/core.py"
    return [core.__file__] + [p for p in paths if p.exists()]

# `type="X"` covers the direct constructions; the second alternative covers the
# registry_refs helper `_matches(pattern, "X", text)`, which passes the type positionally.
_TYPE_LITERAL_RE = re.compile(
    r"""type=["']([A-Z][A-Z0-9_]*)["']"""
    r"""|_matches\([^,]+,\s*["']([A-Z][A-Z0-9_]*)["']"""
)


def _emitted_type_literals() -> set[str]:
    found: set[str] = set()
    for path in _wired_modules():
        for a, b in _TYPE_LITERAL_RE.findall(pathlib.Path(path).read_text(encoding="utf-8")):
            found.add(a or b)
    return found


_V11_BASE_ORDER = (
        "RODNE_CISLO", "IBAN", "BANKOVY_UCET", "BIC", "IC_DPH", "ICO", "DIC",
        # AMENDMENT 3 (2026-09-16): VODICSKY_PREUKAZ moved AHEAD of CISLO_PASU/CISLO_OP. It is
    # anchor-required; the other two also match their bare letter+digit shape unanchored, so
    # on an exact-span tie the anchored claim is better evidenced. Deliberate reorder — this
    # constant was updated together with detect/core.py, which is the whole point of pinning
    # it: the test below failed first and forced this line to be written.
    "VIN", "ECV", "VODICSKY_PREUKAZ", "CISLO_PASU", "CISLO_OP",
        "SPISOVA_ZNACKA", "ORSR_VLOZKA", "LV", "PARCELA",
        "EMAIL", "TELEFON", "URL",
        "ADRESA", "PSC", "SUPISNE_CISLO", "CISLO_BYTU", "VCHOD", "POSCHODIE",
        # AMENDMENT 4 (2026-09-16): MENO moved AHEAD of ORG/OBEC/KATASTER. Deliberate reorder --
    # a gazetteer place-name hit must never outrank a user-supplied or anchor-confirmed
    # personal name on the same span. See detect/core.py for the full reason.
    "MENO", "ORG", "OBEC", "KATASTER",
        "DATUM", "SUMA",
)

# CONTRACTS_v11.md §12 (AMENDMENT 1): the types required by Vyhláška MS SR 482/2011, appended
# to the base order. FAX is the one exception — it is placed inside the contact block, before
# TELEFON, because the two share a digit shape and FAX's anchor makes it the stronger claim.
_V11_AMENDMENT_TYPES = frozenset({
    "KOD_BANKY", "NAZOV_BANKY", "NAZOV_UCTU", "CISLO_KLIENTA", "FAX", "ULICA",
    "STATNA_PRISLUSNOST",
})


def test_frozen_v11_base_order_is_preserved_in_sequence():
    """The base order must survive verbatim as a SUBSEQUENCE. Amendment types may be inserted
    or appended, but no v1.1 base type may be reordered relative to another — reordering
    silently changes which type wins an exact-span tie, and that is a behaviour change that
    must never ride along inside an unrelated diff."""
    positions = [_TYPE_PRECEDENCE.index(t) for t in _V11_BASE_ORDER]
    assert positions == sorted(positions), [
        t for t, _ in sorted(zip(_V11_BASE_ORDER, positions), key=lambda x: x[1])
    ]


def test_amendment_types_are_registered():
    assert _V11_AMENDMENT_TYPES <= set(_TYPE_PRECEDENCE)


def test_fax_outranks_telefon():
    assert _TYPE_PRECEDENCE.index("FAX") < _TYPE_PRECEDENCE.index("TELEFON")


def test_known_types_mirrors_the_precedence_tuple():
    assert KNOWN_TYPES == frozenset(_TYPE_PRECEDENCE)
    assert len(_TYPE_PRECEDENCE) == len(KNOWN_TYPES)  # no duplicate entries


def test_every_type_literal_in_detect_modules_is_registered():
    literals = _emitted_type_literals()
    assert literals, "harvester found no type literals — the regex has gone stale"
    assert literals <= KNOWN_TYPES, sorted(literals - KNOWN_TYPES)


def test_all_currently_shipped_detector_types_are_present():
    # belt-and-braces against a harvester regex that silently stops matching
    shipped = {
        "RODNE_CISLO", "ICO", "DIC", "IC_DPH", "IBAN", "BANKOVY_UCET",
        "EMAIL", "URL", "TELEFON", "DATUM", "SUMA", "MENO",
        "LV", "PARCELA", "ORSR_VLOZKA", "SPISOVA_ZNACKA",
    }
    assert shipped <= _emitted_type_literals()
    assert shipped <= KNOWN_TYPES


def test_rank_of_unregistered_type_does_not_raise_and_sorts_last():
    assert _rank("NIEKTORY_NOVY_TYP") == len(_TYPE_PRECEDENCE)
    assert _rank("RODNE_CISLO") == 0
    # Every REGISTERED type must rank strictly stronger than an unregistered one. (SUMA is no
    # longer the last entry: CONTRACTS_v11.md §12's amendment types are appended after it.)
    assert _rank("SUMA") < _rank("NIEKTORY_NOVY_TYP")
    assert all(_rank(t) < len(_TYPE_PRECEDENCE) for t in _TYPE_PRECEDENCE)


def test_rank_lookup_uses_get_not_subscript():
    assert _TYPE_RANK.get("NIEKTORY_NOVY_TYP", len(_TYPE_PRECEDENCE)) == len(_TYPE_PRECEDENCE)


def test_resolution_stages_survive_an_unregistered_type():
    odd = Candidate("NIEKTORY_NOVY_TYP", "1234567890", 0, 10, True)
    known = Candidate("DIC", "1234567890", 0, 10, True)
    out = core._resolve_type_precedence([odd, known])
    assert [c.type for c in out] == ["DIC"]  # registered type outranks the unknown one
