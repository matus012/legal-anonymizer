"""Phase 5 P3 (context.md): PDF metadata / XMP / attachment scrubbing.

P2 destroyed body glyphs. This file covers the three NON-BODY surfaces the leak harness
reads (eval/extract.py) and which body redaction cannot reach at all: the Info dictionary,
the XMP packet, and embedded file attachments. A PDF whose body is perfectly redacted still
leaks a name sitting in /Author -- that is the failure mode this file exists to catch.

Two assertion layers, deliberately:

  * STRUCTURAL -- doc.metadata values empty, get_xml_metadata() == "", embfile_names() == [].
    These pin the mechanism (the scrub actually ran) and localize a regression to a surface.
  * RAW BYTES -- the planted secrets absent from the output file's bytes. This is the real
    leak check: it does not care which API a secret hides behind, so it also catches a secret
    that survived in a surface no structural assertion here happens to read.

Fixtures are hand-built in-test with fitz (NO corpus import), matching the P1/P2 test files.
"""
from __future__ import annotations

import fitz

from writer.pdf_body import RedactionIncompleteError, redact_pdf

# Distinct per-surface sentinels: a failure names WHICH surface leaked, not just "something did".
LEAKNAME = "LEAKNAME"          # -> Info dictionary /Author
LEAKXMP = "LEAKXMP"            # -> XMP packet
LEAKATT = "LEAKATT"            # -> embedded file attachment
ALL_LEAKS = (LEAKNAME, LEAKXMP, LEAKATT)

# doc.metadata['format'] is derived by MuPDF from the PDF header version, NOT from the Info
# dictionary -- set_metadata cannot clear it (verified: it stays 'PDF 1.7' through
# set_metadata({}) and a save/reopen). It is a format constant, never PII, so it is the one
# key excluded from the all-values-empty assertion.
_UNSETTABLE_METADATA_KEYS = {"format"}


def _leaky_pdf(path) -> None:
    """A PDF carrying a distinct secret in each of the three non-body surfaces.

    Also carries plain body text so has_text_layer() is True and redact_pdf() proceeds to the
    scrub instead of refusing -- the body itself is deliberately PII-free, so any secret found
    in the output came from a metadata surface and nowhere else."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Filler text bez osobnych udajov.", fontname="helv", fontsize=11)
    doc.set_metadata({"author": LEAKNAME})
    doc.set_xml_metadata(f"<x>{LEAKXMP}</x>")
    doc.embfile_add("att1", LEAKATT.encode())
    doc.save(str(path))
    doc.close()


def _redact(src, out) -> None:
    """RedactionIncompleteError is orthogonal to scrubbing -- the scrub runs before doc.save,
    so the output exists and is scrubbed either way. Swallowed so these tests fail on scrub
    regressions only."""
    try:
        redact_pdf(str(src), str(out))
    except RedactionIncompleteError:
        pass


def test_fixture_actually_carries_all_three_leaks(tmp_path):
    """Guards the other tests: a fixture that silently stopped planting a secret would make
    every scrub assertion below pass vacuously."""
    src = tmp_path / "in.pdf"
    _leaky_pdf(src)

    doc = fitz.open(str(src))
    # The three harness read-expressions, verbatim (eval/extract.py) -- not imported by design.
    info = " ".join(str(v) for v in (doc.metadata or {}).values())
    xmp = doc.get_xml_metadata() or ""
    attachments = " ".join(
        doc.embfile_get(n).decode("utf-8", "replace") for n in doc.embfile_names()
    )
    doc.close()

    assert LEAKNAME in info
    assert LEAKXMP in xmp
    assert LEAKATT in attachments


def test_info_metadata_is_emptied(tmp_path):
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _leaky_pdf(src)

    _redact(src, out)

    doc = fitz.open(str(out))
    metadata = doc.metadata or {}
    doc.close()

    leftover = {
        k: v for k, v in metadata.items() if v and k not in _UNSETTABLE_METADATA_KEYS
    }
    assert leftover == {}


def test_xmp_metadata_is_deleted(tmp_path):
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _leaky_pdf(src)

    _redact(src, out)

    doc = fitz.open(str(out))
    xmp = doc.get_xml_metadata() or ""
    doc.close()

    assert xmp == ""


def test_embedded_attachments_are_deleted(tmp_path):
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _leaky_pdf(src)

    _redact(src, out)

    doc = fitz.open(str(out))
    names = doc.embfile_names()
    doc.close()

    assert names == []


def test_no_secret_survives_in_the_output_bytes(tmp_path):
    """THE leak assertion. Surface-agnostic: catches a secret that outlived the scrub in any
    corner of the file, including one no structural assertion above reads."""
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"
    _leaky_pdf(src)

    _redact(src, out)

    raw = out.read_bytes()
    survivors = [leak for leak in ALL_LEAKS if leak.encode() in raw]
    assert survivors == []


def test_body_redaction_still_works_alongside_the_scrub(tmp_path):
    """P2 regression guard: the scrub must not have disturbed the collect/apply/draw loop."""
    name = "Novák"
    src = tmp_path / "in.pdf"
    out = tmp_path / "out.pdf"

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"Predavajuci: {name}", fontname="helv", fontsize=11)
    doc.set_metadata({"author": LEAKNAME})
    doc.save(str(src))
    doc.close()

    redact_pdf(str(src), str(out), known_entities=[name])

    doc = fitz.open(str(out))
    text = "".join(p.get_text("text") for p in doc)
    doc.close()

    assert name not in text       # glyphs still destroyed
    assert "[MENO_1]" in text     # label still drawn (now numbered per entity)
    assert LEAKNAME.encode() not in out.read_bytes()
