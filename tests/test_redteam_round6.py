"""Red-team round 6 — THE PDF CONTAINER.

Rounds 1-5 attacked the DOCX package and the PDF TEXT LAYER. This round attacks the PDF
*container*: the objects PyMuPDF writes into the output file and a reader renders from it —
the catalogue and its name trees, optional content, the CropBox, associated files, the
structure tree, and the residue a save leaves behind.

Fixtures are hand-built with ``fitz`` plus raw xref surgery (``update_object`` /
``xref_set_key`` / ``update_stream``), because none of these shapes can be produced by
``corpus/generate.py``: a reality check at the bottom of this file measures the corpus and
finds ZERO of 71 PDFs carrying an outline, a link, an optional-content group, a structure
tree, an associated file or a Form XObject shared between pages.

Every test asserts THE PROPERTY THAT SHOULD HOLD. A test asserting the bug would be green
today and turn red the day it was fixed, which is backwards. Unfixed findings carry
``xfail(strict=True)`` with the finding id, so a landed fix announces itself by XPASSing.

The tests that PASS are CONTROLS, of two kinds:

  * **reachability controls** — the needle is provably present on the expected surface of the
    UNREDACTED fixture (and, for R6-04, provably extractable from the OUTPUT by an ordinary
    reader), so "absent" can never be confused with a malformed fixture or a blind extractor;
  * **contrast controls** — the identical PII in the plane the writer DOES cover is redacted
    in the same run, so each finding is attributable to the missing traversal rather than to a
    detector that never fired.

A third block of controls records what did NOT reproduce, so nobody re-runs those attacks.

Findings are documented in ``redteam/FINDINGS_ROUND6.md``.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import fitz
import pytest

from detect.core import detect_with_failures
from eval.extract import extract
from eval.leak import Leak
from eval.leak_gate import split_found_in
from writer.labelmap import LabelMap
from writer.pdf_body import (RedactionIncompleteError, _collect_page_redactions,
                             _draw_label, _locate, redact_pdf)
from writer.report import build_report

# --------------------------------------------------------------------------------- needles
# Distinct per-surface needles so a failure names WHICH plane leaked. The SHORT ones are
# deliberate: a Slovak PSC is five digits and a bank code four, both auto-redact types, and
# round 5's headline was that the leak gate's attributability rule discounts exactly those on
# an opaque surface. A fixture carrying only long names would have recorded half this round
# as "the gate catches it".
NAME = "Maria Kovacova"       # 14 chars
RC = "855612/7788"            # 11 chars
PSC = "04001"                 # 5 chars  -> below the gate's attributability floor
KOD_BANKY = "1100"            # 4 chars  -> below the gate's attributability floor
BODY = "Predavajuci: Jan Novak, obcan SR, bytom Kosice."


# --------------------------------------------------------------------------------- kit
def _page_pdf(path: Path, *, pages: int = 1, extra: str = "") -> None:
    """A minimal, well-formed PDF with a readable text layer on every page.

    The body is deliberately a DIFFERENT party from the attack needles, so anything found in
    the output that matches an attack needle came from the plane under test and nowhere else.
    """
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    for i in range(pages):
        doc[i].insert_text((72, 100), BODY, fontname="helv", fontsize=11)
        if extra:
            doc[i].insert_text((72, 140), extra, fontname="helv", fontsize=11)
    doc.save(str(path))
    doc.close()


def _resave(doc: "fitz.Document", src: Path) -> Path:
    """PyMuPDF refuses a non-incremental save over the open file; write a sibling instead."""
    out = src.with_name(src.stem + "_b.pdf")
    doc.save(str(out), garbage=0)
    doc.close()
    return out


def _redact(src: Path, out: Path, known=None):
    """Run the shipping writer. RedactionIncompleteError is orthogonal to every finding here
    (the output and the report are written before it is raised), so it is swallowed; any other
    exception is allowed to propagate, because a crash IS a finding (R6-09)."""
    try:
        redact_pdf(str(src), str(out), known_entities=list(known or []))
    except RedactionIncompleteError:
        pass


def _surfaces(path: Path, needle: str) -> tuple[str, ...]:
    """Every ``eval/extract.py`` surface of ``path`` whose text contains ``needle``."""
    res = extract(path)
    return tuple(s for s, text in res.by_surface.items() if needle in text)


def _gate_verdict(path: Path, needle: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``eval/leak_gate.split_found_in`` applied to this needle: (counted, set_aside).

    ``counted`` non-empty is a gate FAIL; empty ``counted`` with non-empty ``set_aside`` is
    the class this round hunts — the gate looked, found it, and scored the document CLEAN.
    """
    res = extract(path)
    leak = Leak(
        surface=needle,
        type="MENO",
        found_in=tuple(s for s, t in res.by_surface.items() if needle in t),
        gt_parts=("body",),
    )
    return split_found_in(leak, res.by_surface)


def _new_stream(doc: "fitz.Document", dict_src: str, payload: bytes) -> int:
    x = doc.get_new_xref()
    doc.update_object(x, dict_src)
    doc.update_stream(x, payload, new=True)
    return x


def _docx_bytes(text: str) -> bytes:
    """A real (deflated) OOXML package — the point being that its member is COMPRESSED, so no
    decoding of the bytes that contain it can read a word of it."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "word/document.xml",
            "<w:document><w:body><w:p><w:r><w:t>" + text + "</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    return buf.getvalue()


def _resources_xref(doc: "fitz.Document", page) -> tuple[int, str]:
    """(xref, key) to write an /XObject entry into — /Resources may be direct or indirect."""
    res = doc.xref_get_key(page.xref, "Resources")
    if res[0] == "xref":
        return int(res[1].split()[0]), "XObject"
    return page.xref, "Resources/XObject"


# =================================================================================== R6-01
def _outline_pdf(tmp_path: Path) -> Path:
    src = tmp_path / "outline.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    doc.set_toc([[1, f"Kupna zmluva - {NAME}", 1], [2, f"Rodne cislo {RC}", 1]])
    out = src.with_name("outline_b.pdf")
    doc.save(str(out))
    doc.close()
    return out


def test_control_r6_01_the_outline_needles_are_reachable(tmp_path):
    """CONTROL (reachability): the bookmark titles are on the ``outline`` surface of the input."""
    src = _outline_pdf(tmp_path)
    assert "outline" in _surfaces(src, NAME)
    assert "outline" in _surfaces(src, RC)


def test_r6_01_outline_bookmarks_are_redacted(tmp_path):
    """FIXED: ``_scrub_document_surfaces`` now calls ``doc.set_toc([])``."""
    src = _outline_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    survivors = [n for n in (NAME, RC) if _surfaces(out, n)]
    assert survivors == [], f"bookmark titles shipped unredacted: {survivors}"


# =================================================================================== R6-02
def _link_pdf(tmp_path: Path) -> Path:
    src = tmp_path / "link.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    doc[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 150, 300, 170),
                        "uri": "mailto:maria.kovacova@gmail.com"})
    out = src.with_name("link_b.pdf")
    doc.save(str(out))
    doc.close()
    return out


def test_control_r6_02_the_link_uri_is_reachable(tmp_path):
    """CONTROL (reachability): the URI is on the ``links`` surface of the input."""
    assert "links" in _surfaces(_link_pdf(tmp_path), "maria.kovacova@gmail.com")


def test_r6_02_link_annotation_targets_are_scrubbed(tmp_path):
    """FIXED: ``_scrub_link_targets`` deletes a link whose target ``_target_carries_pii`` --
    the DOCX writer's own predicate -- says carries personal data."""
    src = _link_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out)
    found = _surfaces(out, "maria.kovacova@gmail.com")
    assert found == (), f"link target shipped unredacted, on {found}"


# =================================================================================== R6-03
def _catalogue_pdf(tmp_path: Path) -> Path:
    """One PDF carrying FIVE separate catalogue-plane surfaces, each a different mechanism."""
    src = tmp_path / "catalogue.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    cat = doc.pdf_catalog()

    # 1. named destination — the NAME is the PII
    doc.xref_set_key(cat, "Dests", "<< /Kovacova_Maria_zmluva [ 0 0 R /XYZ 0 792 0 ] >>")
    # 2. page label prefix
    doc.xref_set_key(cat, "PageLabels",
                     "<< /Nums [ 0 << /S /D /P (Kovacova-Maria-) /St 1 >> ] >>")
    # 3. document-open JavaScript with the data in a string literal
    js = doc.get_new_xref()
    doc.update_object(js, f"<< /S /JavaScript /JS (var rc = '{RC}'; var psc = '{PSC}';) >>")
    doc.xref_set_key(cat, "OpenAction", f"{js} 0 R")
    # 4. optional-content group NAME
    doc.add_ocg("Vrstva klienta Peter Horvath", on=True)
    # 5. structure tree: /Alt (screen-reader text), /ActualText, /T (element title)
    se = doc.get_new_xref()
    doc.update_object(se, f"<< /Type /StructElem /S /Figure /Alt (Podpis {NAME}) "
                          f"/ActualText (ucet {KOD_BANKY}) /T (Spis {PSC}) >>")
    st = doc.get_new_xref()
    doc.update_object(st, f"<< /Type /StructTreeRoot /K [ {se} 0 R ] >>")
    doc.xref_set_key(cat, "StructTreeRoot", f"{st} 0 R")
    doc.xref_set_key(cat, "MarkInfo", "<< /Marked true >>")
    return _resave(doc, src)


_CATALOGUE_NEEDLES = {
    "named destination": "Kovacova_Maria_zmluva",
    "page label prefix": "Kovacova-Maria-",
    "OpenAction JavaScript": RC,
    "optional-content group name": "Peter Horvath",
    "structure element /Alt": NAME,
}


def test_control_r6_03_every_catalogue_needle_is_reachable(tmp_path):
    """CONTROL (reachability): all five are on ``pdf_objects`` of the input."""
    src = _catalogue_pdf(tmp_path)
    missing = {k: _surfaces(src, v) for k, v in _CATALOGUE_NEEDLES.items()
               if "pdf_objects" not in _surfaces(src, v)}
    assert missing == {}


@pytest.mark.xfail(strict=True, reason="R6-03: the document catalogue is never scrubbed")
def test_r6_03_the_document_catalogue_is_scrubbed(tmp_path):
    src = _catalogue_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    survivors = sorted(k for k, v in _CATALOGUE_NEEDLES.items() if _surfaces(out, v))
    assert survivors == [], f"catalogue plane shipped unredacted: {survivors}"


@pytest.mark.xfail(
    strict=True,
    reason="R6-03b: a short needle on the catalogue plane is graded CLEAN by the leak gate",
)
def test_r6_03b_a_short_needle_in_the_catalogue_is_graded_by_the_gate(tmp_path):
    """The gate's own verdict, not the extractor's. ``pdf_objects`` is an OPAQUE surface, so a
    Slovak PSC (5) and a bank code (4) fall under the attributability floor of 7 characters and
    are SET ASIDE as structural noise — on a plane that holds nothing but document metadata."""
    src = _catalogue_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    graded = {}
    for needle in (PSC, KOD_BANKY):
        counted, aside = _gate_verdict(out, needle)
        if aside and not counted:
            graded[needle] = ("set aside", aside)
    assert graded == {}, f"leak gate scored these CLEAN although they survived: {graded}"


def test_control_r6_03_contrast_the_same_name_in_the_body_is_redacted(tmp_path):
    """CONTRAST CONTROL: with the same document and the same known_entities, the name written
    into the PAGE is removed — so R6-03 is the plane nobody visits, not a detector miss."""
    src = tmp_path / "contrast.pdf"
    _page_pdf(src, extra=f"Kupujuci: {NAME}, rodne cislo {RC}")
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    doc = fitz.open(str(out))
    text = "".join(p.get_text("text") for p in doc)
    doc.close()
    assert NAME not in text
    assert RC not in text
    assert "[MENO_" in text


# =================================================================================== R6-04
def _af_pdf(tmp_path: Path) -> Path:
    """A PDF whose client file is attached through /AF (an *associated file*, PDF 2.0 /
    PDF/A-3) rather than through the /Names /EmbeddedFiles tree the writer deletes from."""
    src = tmp_path / "af.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    ef = _new_stream(
        doc,
        "<< /Type /EmbeddedFile /Subtype /application#2Fvnd.openxmlformats-officedocument."
        "wordprocessingml.document >>",
        _docx_bytes(f"Kupujuci: {NAME}, rodne cislo {RC}, PSC {PSC}, kod banky {KOD_BANKY}"),
    )
    fs = doc.get_new_xref()
    doc.update_object(fs, f"<< /Type /Filespec /F (priloha_zmluva.docx) "
                          f"/UF (priloha_zmluva.docx) /EF << /F {ef} 0 R >> "
                          f"/AFRelationship /Source >>")
    doc.xref_set_key(doc.pdf_catalog(), "AF", f"[ {fs} 0 R ]")
    return _resave(doc, src)


def _pull_af(path: Path) -> list[bytes]:
    """Read every /AF-reachable embedded file back out, exactly as a reader's attachment pane
    does. This is what makes R6-04 a leak rather than a curiosity."""
    doc = fitz.open(str(path))
    got: list[bytes] = []
    af = doc.xref_get_key(doc.pdf_catalog(), "AF")
    if af[0] == "array":
        for tok in re.findall(r"(\d+) 0 R", af[1]):
            efk = doc.xref_get_key(int(tok), "EF/F")
            if efk[0] == "xref":
                got.append(doc.xref_stream(int(efk[1].split()[0])))
    doc.close()
    return got


def test_control_r6_04_the_attachment_is_readable_from_the_input(tmp_path):
    """CONTROL (reachability): an ordinary reader gets the client's data out of the INPUT."""
    blobs = _pull_af(_af_pdf(tmp_path))
    assert len(blobs) == 1
    with zipfile.ZipFile(io.BytesIO(blobs[0])) as z:
        text = z.read("word/document.xml").decode()
    assert NAME in text and RC in text and PSC in text and KOD_BANKY in text


def test_control_r6_04_the_gate_cannot_see_the_attachment_at_all(tmp_path):
    """CONTROL (extractor blindness), and the reason R6-04 is this round's headline: the
    needles are readable from the file but present on ZERO extractor surfaces, on the INPUT.
    This is not the gate discounting a short needle — it is the gate never seeing it."""
    src = _af_pdf(tmp_path)
    assert _surfaces(src, RC) == ()
    assert _surfaces(src, PSC) == ()
    assert _surfaces(src, KOD_BANKY) == ()


def test_control_r6_04_the_name_tree_is_empty_so_the_writer_never_looks(tmp_path):
    """CONTROL (mechanism): ``_scrub_document_surfaces`` iterates ``doc.embfile_names()``,
    which lists the /Names /EmbeddedFiles tree only — and this file's tree is empty."""
    doc = fitz.open(str(_af_pdf(tmp_path)))
    names = doc.embfile_names()
    doc.close()
    assert names == []


@pytest.mark.xfail(
    strict=True,
    reason="R6-04: an /AF associated file survives the redaction, unseen by every surface",
)
def test_r6_04_associated_files_are_removed(tmp_path):
    src = _af_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    blobs = _pull_af(out)
    leaked: list[str] = []
    for blob in blobs:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            text = z.read("word/document.xml").decode()
        leaked += [n for n in (NAME, RC, PSC, KOD_BANKY) if n in text]
    assert leaked == [], f"embedded client document shipped unredacted: {leaked}"


@pytest.mark.xfail(
    strict=True,
    reason="R6-04b: the leak gate scores the output CLEAN although the attachment survived",
)
def test_r6_04b_the_leak_gate_sees_the_surviving_attachment(tmp_path):
    src = _af_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    blind = [n for n in (NAME, RC, PSC, KOD_BANKY) if not _gate_verdict(out, n)[0]]
    assert blind == [], f"survived the redaction and the gate graded it CLEAN: {blind}"


# =================================================================================== R6-05
def _ocg_off_pdf(tmp_path: Path) -> Path:
    src = tmp_path / "ocg.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    ocg = doc.add_ocg("Poznamky advokata", on=False)
    doc[0].insert_text((72, 200), f"Kupujuci: {NAME}, rodne cislo {RC}",
                       fontname="helv", fontsize=11, oc=ocg)
    out = src.with_name("ocg_b.pdf")
    doc.save(str(out))
    doc.close()
    return out


def test_control_r6_05_the_writer_cannot_see_the_hidden_layer(tmp_path):
    """CONTROL (mechanism): ``page.get_text()`` — which is exactly what
    ``_collect_page_redactions`` calls — returns the body and nothing else, while
    ``eval/extract.py`` (which drops /OCProperties first) reads the hidden text fine."""
    src = _ocg_off_pdf(tmp_path)
    doc = fitz.open(str(src))
    writer_view = doc[0].get_text("text")
    doc.close()
    assert NAME not in writer_view
    assert "text_layer" in _surfaces(src, NAME)


def test_r6_05_text_on_a_hidden_layer_is_redacted(tmp_path):
    """FIXED: the writer calls the SAME ``writer.pdf_view.unhide`` the extractor calls, so the
    hidden layer is in the text it runs detect() over."""
    src = _ocg_off_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    survivors = [n for n in (NAME, RC) if _surfaces(out, n)]
    assert survivors == [], f"hidden-layer text shipped unredacted: {survivors}"


# =================================================================================== R6-06
def _cropbox_pdf(tmp_path: Path) -> Path:
    """The Acrobat "Crop Pages" shape: the CropBox is narrowed and the cropped-away band —
    a letterhead, a stamp, a margin note — is still fully present in the file."""
    src = tmp_path / "crop.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    doc[0].insert_text((72, 700), f"Kupujuci: {NAME}, rodne cislo {RC}",
                       fontname="helv", fontsize=11)
    doc[0].set_cropbox(fitz.Rect(0, 0, 595, 400))
    out = src.with_name("crop_b.pdf")
    doc.save(str(out))
    doc.close()
    return out


def test_control_r6_06_the_writer_cannot_see_outside_the_cropbox(tmp_path):
    """CONTROL (mechanism): same asymmetry as R6-05 — the writer's ``get_text`` clips to the
    CropBox, the extractor widens it to the MediaBox first."""
    src = _cropbox_pdf(tmp_path)
    doc = fitz.open(str(src))
    writer_view = doc[0].get_text("text")
    doc.close()
    assert NAME not in writer_view
    assert "text_layer" in _surfaces(src, NAME)


def test_r6_06_text_outside_the_cropbox_is_redacted(tmp_path):
    """FIXED, by the same one helper as R6-05."""
    src = _cropbox_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    survivors = [n for n in (NAME, RC) if _surfaces(out, n)]
    assert survivors == [], f"text outside the CropBox shipped unredacted: {survivors}"


# =================================================================================== R6-07
def _page_xmp_pdf(tmp_path: Path) -> Path:
    src = tmp_path / "pagexmp.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    xmp = (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{NAME}</dc:creator><dc:title>PSC {PSC}</dc:title>"
        "</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end=\"w\"?>"
    )
    mx = _new_stream(doc, "<< /Type /Metadata /Subtype /XML >>", xmp.encode())
    doc.xref_set_key(doc[0].xref, "Metadata", f"{mx} 0 R")
    return _resave(doc, src)


def test_control_r6_07_the_document_level_xmp_is_deleted(tmp_path):
    """CONTRAST CONTROL: the CATALOGUE's XMP packet is removed by ``del_xml_metadata()`` in the
    same run — so R6-07 is about the level, not about XMP."""
    src = tmp_path / "docxmp.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    doc.set_xml_metadata(f"<x>{NAME}</x>")
    src2 = src.with_name("docxmp_b.pdf")
    doc.save(str(src2))
    doc.close()
    assert "xmp" in _surfaces(src2, NAME)
    out = tmp_path / "out.pdf"
    _redact(src2, out)
    assert _surfaces(out, NAME) == ()


@pytest.mark.xfail(
    strict=True, reason="R6-07: a page-level /Metadata XMP stream is never deleted")
def test_r6_07_page_level_xmp_is_deleted(tmp_path):
    src = _page_xmp_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    survivors = [n for n in (NAME, PSC) if _surfaces(out, n)]
    assert survivors == [], f"page-level XMP shipped unredacted: {survivors}"


@pytest.mark.xfail(
    strict=True,
    reason="R6-07b: the short needle in the page-level XMP is graded CLEAN by the leak gate",
)
def test_r6_07b_the_gate_grades_the_short_needle_in_a_page_xmp(tmp_path):
    src = _page_xmp_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    counted, aside = _gate_verdict(out, PSC)
    assert counted, (f"PSC {PSC} survived on {aside} and the gate counted nothing "
                     f"-- verdict CLEAN")


# =================================================================================== R6-08
def _shared_xobject_pdf(tmp_path: Path, pages: int) -> Path:
    """A letterhead drawn from ONE Form XObject referenced by every page — how a stamping or
    overlay tool (and PyMuPDF's own annotation baking) puts repeated content on a document."""
    src = tmp_path / f"xobj{pages}.pdf"
    _page_pdf(src, pages=pages)
    doc = fitz.open(str(src))
    xo = _new_stream(
        doc,
        "<< /Type /XObject /Subtype /Form /BBox [0 0 595 842] "
        "/Resources << /Font << /Helv 5 0 R >> >> >>",
        f"BT /Helv 11 Tf 72 700 Td (Hlavicka: {NAME}, rc {RC}) Tj ET\n".encode(),
    )
    for page in doc:
        rx, key = _resources_xref(doc, page)
        doc.xref_set_key(rx, key, f"<< /Hlav {xo} 0 R >>")
        cx = page.get_contents()[0]
        doc.update_stream(cx, doc.xref_stream(cx) + b"q /Hlav Do Q\n")
    return _resave(doc, src)


def _recoverable_streams(path: Path, needle: str) -> list[int]:
    """Xrefs whose stream body still holds ``needle`` — what ``qpdf --qdf``, ``mutool clean``
    or any object dump hands back, whether or not the page tree references them."""
    doc = fitz.open(str(path))
    hits = []
    for x in range(1, doc.xref_length()):
        if not doc.xref_is_stream(x):
            continue
        try:
            body = doc.xref_stream(x)
        except Exception:  # noqa: BLE001
            continue
        if needle.encode() in body:
            hits.append(x)
    doc.close()
    return hits


def test_control_r6_08_the_rendered_page_really_is_redacted(tmp_path):
    """CONTROL: the visible plane IS fixed — the letterhead is gone from what a reader sees.
    R6-08 is exclusively about what is left behind in the file."""
    src = _shared_xobject_pdf(tmp_path, pages=2)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    doc = fitz.open(str(out))
    text = "".join(p.get_text("text") for p in doc)
    doc.close()
    assert NAME not in text and RC not in text
    assert "[MENO_" in text


def test_control_r6_08_a_single_page_document_leaves_no_residue(tmp_path):
    """CONTROL (boundary): with ONE page the same construct leaves nothing behind, which is
    what makes the two-page result a finding about object reuse rather than about redaction."""
    src = _shared_xobject_pdf(tmp_path, pages=1)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    assert _recoverable_streams(out, NAME) == []


@pytest.mark.xfail(
    strict=True,
    reason="R6-08: the pre-redaction Form XObject stays in the output as recoverable residue",
)
def test_r6_08_no_pre_redaction_content_stream_survives_in_the_output(tmp_path):
    src = _shared_xobject_pdf(tmp_path, pages=2)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    residue = _recoverable_streams(out, NAME)
    assert residue == [], (
        f"pre-redaction content stream(s) still in the output at xref(s) {residue}")


# =================================================================================== R6-09
def _actualtext_pdf(tmp_path: Path) -> Path:
    """A tagged-PDF span whose /ActualText is LONGER than the glyph run it covers — what
    PDF/UA tagging writes for a ligature, an abbreviation or a hyphen-split word. MuPDF
    distributes the replacement characters over the glyph advances, so the surplus characters
    get ZERO-WIDTH boxes."""
    src = tmp_path / "at.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    page = doc[0]
    cx = page.get_contents()[0]
    utf16 = ("﻿" + f"Kupujuci: {NAME}").encode("utf-16-be").hex().upper()
    doc.update_stream(cx, doc.xref_stream(cx) +
                      (f"/Span << /ActualText <{utf16}> >> BDC\n"
                       f"BT /Helv 11 Tf 72 300 Td (Zmluvna strana) Tj ET\nEMC\n").encode())
    return _resave(doc, src)


def test_control_r6_09_search_for_really_returns_an_empty_rect(tmp_path):
    """CONTROL (mechanism): the fixture is well-formed and the page really does yield a
    degenerate rectangle from ``page.search_for`` — the raw library call, so the control keeps
    measuring the SHAPE rather than the writer's handling of it.

    AMENDED with the R6-09 fix: the original asserted the degenerate rect through
    ``_collect_page_redactions``'s returned pairs, which is exactly where the fix removes it,
    so it could not survive its own finding being closed. The second half is the new property:
    the rect the library returns is dropped from the pairs and RECORDED AS SKIPPED, never
    silently discarded — that is what keeps RedactionIncompleteError firing."""
    src = _actualtext_pdf(tmp_path)
    doc = fitz.open(str(src))
    page = doc[0]
    raw = page.get_text("text")
    # _locate is the step BEFORE the fix's filter: every needle the page pass would search for,
    # located exactly as it locates them. Measured: the /ActualText span puts "Maria Kovacov"
    # on the page as Rect(121.808, 530.417, 135.855, 545.091) plus the degenerate
    # Rect(130.355, 530.417, 130.355, 545.091).
    located = [(raw[c.start:c.end], _locate(page, raw[c.start:c.end])[0])
               for c in detect_with_failures(raw, [NAME], None)[0] if c.auto]
    degenerate = [(needle, r) for needle, rects in located for r in rects if r.is_empty]
    assert degenerate, "fixture no longer produces a degenerate rect"

    lm = LabelMap([NAME])
    pairs, skipped = _collect_page_redactions(page, [NAME], lm, "page_1")
    doc.close()
    assert [r for r, _ in pairs if r.is_empty] == [], "a degenerate rect reached the draw stage"
    for needle, _rect in degenerate:
        assert needle in skipped, needle
        assert [row for row in lm.unlocated if row[2] == needle], needle


def test_control_r6_09_a_zero_width_rect_is_what_breaks_draw_label(tmp_path):
    """CONTROL (isolation): the crash was ``_draw_label``'s, not the fixture's — a zero-WIDTH
    rect raised while a zero-HEIGHT one did not.

    AMENDED with the R6-09 fix, which guards ``_draw_label`` itself so no future caller can
    reintroduce the crash: the zero-width rect now draws nothing and returns. Both halves still
    assert the isolation property (neither degenerate shape reaches the lawyer as a ValueError)
    and the guard is measured at the unit, not only through the writer."""
    doc = fitz.open()
    page = doc.new_page()
    _draw_label(page, fitz.Rect(100, 100, 120, 100), "[MENO_1]")   # zero height: fine
    _draw_label(page, fitz.Rect(100, 100, 100, 115), "[MENO_1]")   # zero width: guarded
    assert "[MENO_1]" not in page.get_text("text"), "a zero-width rect covers no glyph"
    doc.close()


def test_r6_09_a_tagged_pdf_is_not_refused_with_a_library_message(tmp_path):
    """``writer/errors.py`` promises: a file the tool cannot process is refused with a named
    error and a sentence the lawyer can act on. Here the lawyer gets PyMuPDF's
    "text box must be finite and not empty", no output and no report."""
    src = _actualtext_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    try:
        redact_pdf(str(src), str(out), known_entities=[NAME])
    except RedactionIncompleteError:
        pass
    except ValueError as exc:  # noqa: BLE001
        pytest.fail(f"writer raised a bare ValueError: {exc}")


# =================================================================================== R6-10
class _BlindPage:
    """A page whose glyphs cannot be located. ``_collect_page_redactions`` documents itself as
    taking ``page`` by duck type precisely so this bookkeeping is testable on its own."""

    def __init__(self, text: str) -> None:
        self._text = text

    def get_text(self, _kind: str = "text") -> str:
        return self._text

    def search_for(self, _needle: str):
        return []


def _blind_run() -> tuple[LabelMap, list[str]]:
    lm = LabelMap([NAME])
    _pairs, skipped = _collect_page_redactions(
        _BlindPage(f"Predavajuci: {NAME}, rodne cislo {RC}.\n"), [NAME], lm, "page_1")
    return lm, skipped


def test_control_r6_10_the_surfaces_really_were_detected_and_missed(tmp_path):
    """CONTROL (reachability): detect() found both surfaces and marked them auto=True; they
    are in the skip list, which is what raises RedactionIncompleteError."""
    _lm, skipped = _blind_run()
    assert NAME in skipped and RC in skipped


def test_r6_10_the_report_names_the_surfaces_that_were_missed(tmp_path):
    """``writer/pdf_body.py``: "the report is written BEFORE the incomplete-redaction raise,
    deliberately. A partial output is precisely the file whose record a reviewer needs." The
    record that gets written has no row for the surfaces still in the document — it reads as a
    document in which nothing was found."""
    lm, skipped = _blind_run()
    report = build_report(lm.occurrences, lm.low_confidence, lm.checksums,
                          lm.lc_checksums, lm.detector_failures, lm.unlocated)
    unmentioned = [s for s in skipped if s not in report]
    assert unmentioned == [], (
        f"report is silent about {len(unmentioned)} surface(s) left in the document: "
        f"{unmentioned}")


# =========================================================== CONTROLS: DID NOT REPRODUCE
# Each of these was attacked and HELD. They are ordinary passing tests so that nobody in a
# later round spends the time again, and so that a regression in any of them turns the suite
# red rather than becoming a new finding.
def test_dnr_custom_info_dictionary_keys_are_removed(tmp_path):
    """A private /Info key (/Klient) is NOT reachable through ``doc.metadata``, so nothing in
    the extractor names it -- but ``set_metadata({})`` rebuilds the dictionary from scratch
    rather than merging, and the key goes with it."""
    src = tmp_path / "info.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    ix = doc.get_new_xref()
    doc.update_object(ix, "<< >>")
    doc.xref_set_key(-1, "Info", f"{ix} 0 R")
    doc.xref_set_key(ix, "Klient", f"({NAME})")
    src2 = _resave(doc, src)
    assert "pdf_objects" in _surfaces(src2, NAME)
    out = tmp_path / "out.pdf"
    _redact(src2, out)
    assert _surfaces(out, NAME) == ()


def test_dnr_acroform_field_value_and_default_value_are_removed(tmp_path):
    """/V is baked into page content and destroyed there; /DV never reaches the output because
    ``doc.bake()`` drops /AcroForm and the widget, and garbage=4 collects what is left."""
    src = tmp_path / "form.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    w = fitz.Widget()
    w.field_name = "meno_kupujuceho"
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.rect = fitz.Rect(72, 200, 300, 220)
    w.field_value = NAME
    doc[0].add_widget(w)
    src2 = src.with_name("form_b.pdf")
    doc.save(str(src2))
    doc.close()
    doc = fitz.open(str(src2))
    for widget in doc[0].widgets():
        doc.xref_set_key(widget.xref, "DV", f"({RC})")
    src3 = _resave(doc, src2)
    assert "form_fields" in _surfaces(src3, NAME)
    assert "pdf_objects" in _surfaces(src3, RC)
    out = tmp_path / "out.pdf"
    _redact(src3, out, known=[NAME])
    assert _surfaces(out, NAME) == ()
    assert _surfaces(out, RC) == ()


def test_dnr_xfa_packet_is_removed(tmp_path):
    """An entire XFA form-data packet -- the PDF analogue of round 5's w:altChunk -- does not
    survive, because bake() removes /AcroForm and the packet becomes unreachable. It is an
    ACCIDENT of bake(), not a scrub: nothing in writer/ knows what XFA is."""
    src = tmp_path / "xfa.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    packet = ('<?xml version="1.0"?><xdp:xdp xmlns:xdp="http://ns.adobe.com/xdp/">'
              f"<form><meno>{NAME}</meno><rodne_cislo>{RC}</rodne_cislo>"
              f"<psc>{PSC}</psc></form></xdp:xdp>")
    sx = _new_stream(doc, "<< >>", packet.encode())
    af = doc.get_new_xref()
    doc.update_object(af, f"<< /XFA [ (datasets) {sx} 0 R ] /Fields [] >>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"{af} 0 R")
    src2 = _resave(doc, src)
    assert "raw_bytes" in _surfaces(src2, NAME)
    out = tmp_path / "out.pdf"
    _redact(src2, out)
    assert _surfaces(out, NAME) == ()
    assert _surfaces(out, RC) == ()
    assert _surfaces(out, PSC) == ()


def test_dnr_file_attachment_annotation_is_removed(tmp_path):
    """A .docx attached as a FileAttachment ANNOTATION is not in ``embfile_names()`` either --
    but bake() removes the annotation and the stream is collected. The /AF spelling of the
    same attack (R6-04) is NOT, which is the whole of the difference."""
    src = tmp_path / "fa.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    doc[0].add_file_annot(fitz.Point(300, 200),
                          _docx_bytes(f"Kupujuci: {NAME}, rc {RC}"),
                          "priloha.docx", desc=f"Spis {NAME}")
    src2 = src.with_name("fa_b.pdf")
    doc.save(str(src2))
    doc.close()
    assert "annotations" in _surfaces(src2, "priloha.docx")
    out = tmp_path / "out.pdf"
    _redact(src2, out)
    assert _surfaces(out, NAME) == ()
    assert _surfaces(out, "priloha.docx") == ()


def test_dnr_prior_incremental_revision_does_not_survive(tmp_path):
    """The highest-severity vector on the brief's list, and it HOLDS: an input carrying an
    earlier revision's pre-redaction text loses it, because ``doc.save(garbage=4)`` rebuilds
    the xref from the page tree and writes only reachable objects."""
    src = tmp_path / "incr.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"Predavajuci: {NAME}, rodne cislo {RC}",
                     fontname="helv", fontsize=11)
    doc.set_metadata({"author": NAME})
    doc.save(str(src))
    doc.close()
    doc = fitz.open(str(src))
    doc.update_stream(doc[0].get_contents()[0],
                      b"BT /Helv 11 Tf 72 692 Td (Predavajuci: XXXXXX) Tj ET\n")
    doc.set_metadata({"author": ""})
    doc.save(str(src), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    assert NAME.encode() in src.read_bytes(), "fixture has no prior-revision residue"
    assert "raw_bytes" in _surfaces(src, NAME)
    out = tmp_path / "out.pdf"
    _redact(src, out)
    assert _surfaces(out, NAME) == ()
    assert _surfaces(out, RC) == ()


def test_dnr_annotation_author_subject_and_contents_are_removed(tmp_path):
    """/T (author), /Subj and /Contents of a sticky note: bake() flattens the annotation's
    appearance into page content and deletes the object, taking all three with it."""
    src = tmp_path / "note.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    annot = doc[0].add_text_annot((300, 100), f"Klientka: {NAME}, rc {RC}")
    annot.set_info(title="JUDr. Peter Horvath", subject="Spis Kovacova")
    annot.update()
    src2 = src.with_name("note_b.pdf")
    doc.save(str(src2))
    doc.close()
    for needle in (NAME, "JUDr. Peter Horvath", "Spis Kovacova"):
        assert "annotations" in _surfaces(src2, needle)
    out = tmp_path / "out.pdf"
    _redact(src2, out, known=[NAME])
    for needle in (NAME, RC, "JUDr. Peter Horvath", "Spis Kovacova"):
        assert _surfaces(out, needle) == (), needle


def test_dnr_hidden_annotation_is_removed(tmp_path):
    """An annotation carrying the /F Hidden flag -- no appearance for bake() to flatten -- is
    still dropped."""
    src = tmp_path / "hid.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    annot = doc[0].add_text_annot((300, 100), f"Klientka {NAME}, rc {RC}")
    annot.set_flags(fitz.PDF_ANNOT_IS_HIDDEN)
    annot.update()
    src2 = src.with_name("hid_b.pdf")
    doc.save(str(src2))
    doc.close()
    assert "annotations" in _surfaces(src2, NAME)
    out = tmp_path / "out.pdf"
    _redact(src2, out, known=[NAME])
    assert _surfaces(out, NAME) == ()


def test_dnr_signature_dictionary_is_removed(tmp_path):
    """A /Sig dictionary's /Name, /Reason, /Location and /ContactInfo -- the whole of what an
    eIDAS signature panel shows about the signer -- do not survive: the signature widget goes
    with /AcroForm in bake()."""
    src = tmp_path / "sig.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    sig = doc.get_new_xref()
    doc.update_object(sig, f"<< /Type /Sig /Filter /Adobe.PPKLite /Name (JUDr. {NAME}) "
                           f"/Reason (Podanie v spise {PSC}) /Location (Kosice) "
                           f"/ContactInfo (advokat@kovacova.sk) >>")
    wx = doc.get_new_xref()
    doc.update_object(wx, f"<< /Type /Annot /Subtype /Widget /FT /Sig /T (Podpis1) "
                          f"/V {sig} 0 R /Rect [400 520 560 570] /F 4 >>")
    afx = doc.get_new_xref()
    doc.update_object(afx, f"<< /Fields [ {wx} 0 R ] >>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"{afx} 0 R")
    doc.xref_set_key(doc[0].xref, "Annots", f"[ {wx} 0 R ]")
    src2 = _resave(doc, src)
    assert "pdf_objects" in _surfaces(src2, NAME)
    out = tmp_path / "out.pdf"
    _redact(src2, out, known=[NAME])
    for needle in (NAME, "advokat@kovacova.sk"):
        assert _surfaces(out, needle) == (), needle


def test_dnr_an_unapplied_redact_annotation_in_the_input_is_honoured(tmp_path):
    """A "redaction" a lawyer drew in Acrobat and never applied: the text under the black box
    is still real text in the input. It does NOT ship -- ``page.apply_redactions()`` applies
    every redaction annotation on the page, including the one that arrived with the file."""
    src = tmp_path / "red.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    doc[0].insert_text((72, 200), f"Kupujuci: {NAME}, PSC {PSC}",
                       fontname="helv", fontsize=11)
    rect = doc[0].search_for(f"{NAME}, PSC {PSC}")[0]
    doc[0].add_redact_annot(rect, fill=(0, 0, 0))
    src2 = src.with_name("red_b.pdf")
    doc.save(str(src2))
    doc.close()
    assert "text_layer" in _surfaces(src2, NAME)
    out = tmp_path / "out.pdf"
    _redact(src2, out, known=[NAME])
    assert _surfaces(out, NAME) == ()
    assert _surfaces(out, PSC) == ()


def test_dnr_a_widget_with_needappearances_and_no_ap_is_removed(tmp_path):
    """A government form that sets /NeedAppearances and ships field values with no appearance
    stream: MuPDF synthesizes the appearance, bake() flattens it, and the value is destroyed
    with the rest of the page content."""
    src = tmp_path / "na.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    wx = doc.get_new_xref()
    doc.update_object(wx, f"<< /Type /Annot /Subtype /Widget /FT /Tx /T (meno) /V ({NAME}) "
                          f"/Rect [72 520 400 545] /DA (/Helv 11 Tf 0 g) /F 4 >>")
    afx = doc.get_new_xref()
    doc.update_object(afx, f"<< /Fields [ {wx} 0 R ] /NeedAppearances true >>")
    doc.xref_set_key(doc.pdf_catalog(), "AcroForm", f"{afx} 0 R")
    doc.xref_set_key(doc[0].xref, "Annots", f"[ {wx} 0 R ]")
    src2 = _resave(doc, src)
    assert "form_fields" in _surfaces(src2, NAME)
    out = tmp_path / "out.pdf"
    _redact(src2, out, known=[NAME])
    assert _surfaces(out, NAME) == ()


# ===================================================== PROPERTIES THE ROUND-6 FIXES MUST KEEP
# Closing a finding is only half of it: each fix touches the SHIPPING path for every ordinary
# document, and a fix that costs the office an ordinary document is worse than the finding.
def test_the_writer_and_the_extractor_read_the_same_document(tmp_path):
    """The root cause of R6-05 AND R6-06 was two readings of one file. There is now exactly ONE
    definition of the unhidden view, and both sides call it -- asserted on the identity of the
    function object, because a second copy is what would bring the finding back."""
    import eval.extract as extract_mod
    import writer.pdf_body as pdf_body_mod
    from writer.pdf_view import unhide

    assert pdf_body_mod.unhide is unhide
    assert extract_mod.unhide is unhide


def test_the_output_keeps_the_cropbox_it_arrived_with(tmp_path):
    """R6-06's fix must not UN-CROP the lawyer's document. The band is read and redacted with
    the box widened; the box is put back before the save, so the output page is the page they
    handed in."""
    src = _cropbox_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    before = fitz.open(str(src))
    after = fitz.open(str(out))
    assert tuple(after[0].cropbox) == tuple(before[0].cropbox)
    assert tuple(after[0].cropbox) != tuple(after[0].mediabox), "fixture is not cropped"
    before.close()
    after.close()


def test_the_output_keeps_an_off_layer_switched_off(tmp_path):
    """The R6-05 counterpart: the PII on the hidden layer is destroyed, but the layer
    CONFIGURATION is restored, so an attorney's "Poznamky advokata" layer does not arrive at
    the other side switched on."""
    src = _ocg_off_pdf(tmp_path)
    out = tmp_path / "out.pdf"
    _redact(src, out, known=[NAME])
    doc = fitz.open(str(out))
    kind, _value = doc.xref_get_key(doc.pdf_catalog(), "OCProperties")
    off = doc.get_layer().get("off") or []
    doc.close()
    assert kind != "null", "/OCProperties was dropped from the saved output"
    assert off, "the OFF layer came back switched ON"


def test_a_link_that_carries_no_pii_survives(tmp_path):
    """FALSE-REFUSAL guard for R6-02: the scrub deletes links by the DOCX writer's measured
    predicate, not by being a link. A citation to the statute book is the commonest link in a
    Slovak legal document and must still work."""
    src = tmp_path / "cite.pdf"
    _page_pdf(src)
    doc = fitz.open(str(src))
    doc[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 150, 300, 170),
                        "uri": "https://www.slov-lex.sk/pravne-predpisy/SK/ZZ/1964/40/"})
    src2 = src.with_name("cite_b.pdf")
    doc.save(str(src2))
    doc.close()
    out = tmp_path / "out.pdf"
    _redact(src2, out)
    doc = fitz.open(str(out))
    uris = [link.get("uri") for p in doc for link in p.get_links()]
    doc.close()
    assert "https://www.slov-lex.sk/pravne-predpisy/SK/ZZ/1964/40/" in uris


def test_the_unlocated_section_says_the_document_may_be_under_redacted(tmp_path):
    """R6-10's framing, not merely its rows: the block carries the same
    THIS DOCUMENT MAY BE UNDER-REDACTED warning ``_FAILURE_HEADER`` uses, and sits ABOVE the
    two tables -- what is missing from them is what the reviewer has to act on."""
    lm, _skipped = _blind_run()
    report = build_report(lm.occurrences, lm.low_confidence, lm.checksums,
                          lm.lc_checksums, lm.detector_failures, lm.unlocated)
    assert "THIS DOCUMENT MAY BE UNDER-REDACTED" in report
    assert report.index("NOT REDACTED --") < report.index("[REDACTED]")
    assert "MENO" in report and NAME in report


def test_a_report_without_the_new_channel_is_byte_identical(tmp_path):
    """The same discipline every earlier side-channel was added under: a document with nothing
    to report loses not one byte, so no existing report, test or diff shifts because R6-10's
    block exists. This is what keeps the DOCX writer (which does not pass the channel)
    unchanged."""
    base = build_report({"[MENO_1]": [("page_1", "Novak")]}, [])
    assert build_report({"[MENO_1]": [("page_1", "Novak")]}, [], None, None, None, None) == base
    assert build_report({"[MENO_1]": [("page_1", "Novak")]}, [], None, None, None, []) == base


# ================================================================ CONTROL: corpus reality
CORPUS = Path(__file__).resolve().parents[1] / "data" / "synthetic"


@pytest.mark.skipif(not CORPUS.is_dir(), reason="data/synthetic not generated")
def test_control_the_corpus_cannot_express_a_single_shape_in_this_round(tmp_path):
    """The structural observation behind all six rounds, measured rather than asserted.

    It is also this round's FALSE-REFUSAL measurement: a guard that refuses, strips or rewrites
    any of these constructs cannot refuse a single document in the corpus, because no corpus
    document contains one. That is a zero false-refusal rate AND a statement that the corpus
    proves nothing about these shapes either way.
    """
    counts = {"outline": 0, "links": 0, "ocgs": 0, "struct_tree": 0, "associated_files": 0,
              "shared_xobject": 0}
    pdfs = sorted(CORPUS.glob("*.pdf"))
    assert pdfs, "corpus has no PDFs"
    for path in pdfs:
        doc = fitz.open(str(path))
        try:
            counts["outline"] += bool(doc.get_toc())
            counts["links"] += any(p.get_links() for p in doc)
            counts["ocgs"] += bool(doc.get_ocgs())
            counts["struct_tree"] += (
                doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] != "null")
            counts["associated_files"] += (
                doc.xref_get_key(doc.pdf_catalog(), "AF")[0] != "null")
            per_page = {}
            for page in doc:
                rx, _key = _resources_xref(doc, page)
                xo = doc.xref_get_key(rx, "XObject")
                if xo[0] != "null":
                    per_page[page.number] = xo[1]
            counts["shared_xobject"] += (
                len(per_page) > 1 and len(set(per_page.values())) < len(per_page))
        finally:
            doc.close()
    assert counts == {k: 0 for k in counts}, (
        f"corpus now expresses one of round 6's shapes: {counts} over {len(pdfs)} PDFs")
