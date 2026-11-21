"""R0 — NAMED FIELD REGRESSION: pre-1954 rodné číslo with a 3-digit suffix.

This is the ONE defect reported from the office's first acceptance round: a rodné číslo
written in the pre-1954 form ``YYMMDD/XXX`` (nine digits, no check digit) was NOT caught, so
it survived into the redacted output. It survived because v1's ``_RC_RE`` was
``\\b(\\d{6})/(\\d{4})\\b`` — it required exactly four digits after the slash — and because the
mod-11 checksum was applied unconditionally, which is meaningless for a number that has no
check digit at all (rodné čísla issued before 1954 are not divisible by 11).

This file is the regression gate for that bug and must stay green before any DONE claim.
It deliberately tests END TO END through the real writers, not just through ``detect()``: the
office's bug was that the string came out in the FILE, and a detector-only test would not have
caught a writer that found the span and then failed to remove it.

Six placements, one per reported/plausible surface (ADDENDUM 1 R0):
    1. with a slash              ``850315/001``
    2. with a space              ``850315 001``
    3. no separator, near an RČ context anchor  ``rodné číslo 850315001``
    4. in a DOCX table cell
    5. split across several DOCX ``<w:r>`` runs (the classic silent-failure mode, context.md §10)
    6. in a PDF text layer

Fixtures are hand-built here with python-docx / fitz. ``corpus/`` is never imported
(CONTRACTS_v11.md §11).

Numbers used below are deliberately NOT divisible by 11, so a test that passes proves the
9-digit path does not run the checksum:
    850315001 % 11 == 3
"""
from __future__ import annotations

import fitz
import pytest
from docx import Document

from detect.core import detect
from eval.extract import extract
from writer.docx_body import redact_docx_body
from writer.pdf_body import redact_pdf

NBSP = " "

# The nine-digit pre-1954 forms under test, with the context that arms each one.
SLASH = "850315/001"
SPACED = "850315 001"
NBSP_FORM = f"850315{NBSP}001"
CONTIGUOUS = "850315001"


def test_nine_digit_rc_is_not_divisible_by_eleven():
    """Pins the premise of every test below: if this number happened to pass mod-11, a
    detector that still (wrongly) ran the checksum would look correct here."""
    assert int(CONTIGUOUS) % 11 != 0


# --------------------------------------------------------------------- detector level
@pytest.mark.parametrize(
    "text, expected",
    [
        (f"Rodné číslo {SLASH} je uvedené v zmluve.", SLASH),
        (f"Rodné číslo {SPACED} je uvedené v zmluve.", SPACED),
        (f"Rodné číslo {NBSP_FORM} je uvedené v zmluve.", NBSP_FORM),
        (f"rodné číslo {CONTIGUOUS} je uvedené v zmluve.", CONTIGUOUS),
        (f"r.č. {CONTIGUOUS} je uvedené v zmluve.", CONTIGUOUS),
        (f"rč {CONTIGUOUS} je uvedené v zmluve.", CONTIGUOUS),
        (f"nar. {CONTIGUOUS} v Košiciach.", CONTIGUOUS),
    ],
)
def test_detected_as_rodne_cislo(text, expected):
    hits = [c for c in detect(text) if c.type == "RODNE_CISLO"]
    assert len(hits) == 1, (text, detect(text))
    assert hits[0].surface == expected


@pytest.mark.parametrize("text", [
    f"Rodné číslo {SLASH}.",
    f"r.č. {CONTIGUOUS}.",
])
def test_nine_digit_form_is_auto_redacted_and_never_tagged_invalid(text):
    """The bug had two halves. The second half: even once matched, a 9-digit RČ must never be
    routed to the review bucket on a failed mod-11, because it HAS no check digit. It is
    always ``checksum="n/a"`` and always ``auto=True``."""
    hit = next(c for c in detect(text) if c.type == "RODNE_CISLO")
    assert hit.auto is True
    assert hit.checksum == "n/a"


# ------------------------------------------------------------------------- DOCX, body
def _docx_with_paragraph(path, text: str) -> None:
    doc = Document()
    doc.add_paragraph(text)
    doc.save(str(path))


@pytest.mark.parametrize("surface", [SLASH, SPACED, CONTIGUOUS])
def test_docx_body_nine_digit_rc_is_removed(tmp_path, surface):
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    _docx_with_paragraph(src, f"Rodné číslo {surface} koniec vety.")
    redact_docx_body(str(src), str(out))
    text = extract(str(out)).full_text
    assert surface not in text, f"{surface!r} survived into the redacted DOCX"
    assert "[RODNE_CISLO_1]" in text


# -------------------------------------------------------------------- DOCX, table cell
def test_docx_table_cell_nine_digit_rc_is_removed(tmp_path):
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).paragraphs[0].add_run("Rodné číslo")
    table.cell(0, 1).paragraphs[0].add_run(SLASH)
    doc.save(str(src))

    redact_docx_body(str(src), str(out))
    text = extract(str(out)).full_text
    assert SLASH not in text, "9-digit RČ survived in a table cell"


# ------------------------------------------------------------- DOCX, split across runs
def test_docx_split_across_runs_nine_digit_rc_is_removed(tmp_path):
    """The classic silent failure (context.md §10): Word splits one logical surface across
    several ``<w:r>`` runs, so a regex over ``run.text`` finds nothing. The surface only exists
    on the RECONSTRUCTED paragraph text. Fragments below deliberately break the number
    mid-token, including across the slash."""
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    p = doc.add_paragraph()
    for fragment in ("Rodné čís", "lo 8503", "15", "/0", "01 koniec."):
        p.add_run(fragment)
    doc.save(str(src))

    # Precondition: the surface really is split — no single run contains it.
    assert all(SLASH not in r.text for r in doc.paragraphs[0].runs)
    assert SLASH in "".join(r.text for r in doc.paragraphs[0].runs)

    redact_docx_body(str(src), str(out))
    text = extract(str(out)).full_text
    assert SLASH not in text, "9-digit RČ survived when split across runs"
    assert "[RODNE_CISLO_1]" in text


# --------------------------------------------------------------------------------- PDF
@pytest.mark.parametrize("surface", [SLASH, CONTIGUOUS])
def test_pdf_nine_digit_rc_is_removed(tmp_path, surface):
    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), f"Rodne cislo {surface} koniec vety.")
    doc.save(str(src))
    doc.close()

    redact_pdf(str(src), str(out))
    text = extract(str(out)).full_text
    assert surface not in text, f"{surface!r} survived into the redacted PDF text layer"


# ------------------------------------------------------- the v1 behaviour must not return
def test_ten_digit_form_still_works(tmp_path):
    """Guard against a fix that widens the 9-digit case by breaking the 10-digit one."""
    ten = "850315/0018"  # 8503150018 % 11 == 0
    hit = next(c for c in detect(f"Rodné číslo {ten}.") if c.type == "RODNE_CISLO")
    assert hit.surface == ten
    assert hit.checksum == "valid"


def test_bare_nine_digit_run_without_context_is_not_claimed():
    """The widened pattern must not start eating every 9-digit number in every document. With
    no RČ anchor nearby, a bare contiguous run is NOT a rodné číslo."""
    assert [c for c in detect("Faktúra 850315001 zo dňa 1.1.2025.") if c.type == "RODNE_CISLO"] == []


def test_phone_number_is_not_stolen_by_the_widened_pattern():
    """``0905 123 456`` is six digits, a space, three, a space, three — the widened
    separator/internal-whitespace rules must not let RODNE_CISLO (which outranks TELEFON)
    claim it. This was the concrete mis-parse the two-regex design exists to prevent."""
    types = {c.type for c in detect("Kontakt r.č. nižšie, tel. 0905 123 456.")}
    assert "TELEFON" in types
    assert "RODNE_CISLO" not in types
