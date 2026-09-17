"""Red-team round 3 reproductions — redteam/FINDINGS_ROUND3.md.

POLARITY. Every test here asserts the PROPERTY THAT SHOULD HOLD (the PII is gone / the whole
surface is covered). The ones that do not hold yet carry ``@pytest.mark.xfail`` with the
finding id, so the suite is green today and the day a fix lands the test XPASSes and says so.
A red-team test that asserted the bug would go green now and RED when somebody fixed it.

Every fixture is HAND-BUILT (CONTRACTS_v11.md §11): nothing here imports ``corpus/``. That is
not a formality in this round — the entire premise is that ``corpus/docx_builder.py`` and
``corpus/pdf_builder.py`` CANNOT EMIT these container shapes, so a fixture built through them
would prove nothing.

Each container test is paired with a CONTROL built in the same way out of the shape the corpus
DOES produce. Without the control, a "leak" here would be indistinguishable from a fixture that
is simply malformed — the control is what makes the difference attributable to the shape.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from detect.core import detect
from eval.extract import extract
from writer.docx_body import redact_docx_body

# --------------------------------------------------------------------------- raw OPC fixture
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

_CT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
    "</Relationships>"
)
_CORE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
    ' xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title></dc:title><dc:creator></dc:creator></cp:coreProperties>'
)
_APP = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    "<Company></Company></Properties>"
)
_DOC_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rIdH1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"'
    ' Target="mailto:x@example.sk" TargetMode="External"/></Relationships>'
)

NAME = "Ján Novák"
NAME2 = "Mária Kováčová"
KNOWN = [NAME, NAME2]


def _build_docx(path: Path, body_xml: str) -> Path:
    doc = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {_W} {_R}><w:body>{body_xml}<w:sectPr/></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("docProps/core.xml", _CORE)
        z.writestr("docProps/app.xml", _APP)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
    return path


def _p(*inner: str) -> str:
    return "<w:p>" + "".join(inner) + "</w:p>"


def _r(*inner: str) -> str:
    return "<w:r>" + "".join(inner) + "</w:r>"


def _t(s: str) -> str:
    return f'<w:t xml:space="preserve">{s}</w:t>'


def _redact_and_read(tmp_path: Path, name: str, body: str) -> tuple[dict[str, str], str]:
    """Redact a hand-built package and return (extracted surfaces, raw document.xml)."""
    src = _build_docx(tmp_path / f"{name}_in.docx", body)
    dst = tmp_path / f"{name}_out.docx"
    redact_docx_body(str(src), str(dst), known_entities=KNOWN)
    with zipfile.ZipFile(dst) as z:
        document_xml = z.read("word/document.xml").decode("utf-8")
    return extract(dst).by_surface, document_xml


def _assert_gone(surfaces: dict[str, str], needle: str) -> None:
    where = sorted(s for s, v in surfaces.items() if needle in v)
    assert not where, f"{needle!r} survived redaction on surfaces {where}"


# =========================================================================== CONTROLS
# These must ALWAYS pass. They are what makes every xfail below attributable to the container
# shape rather than to the fixture builder.
def test_control_corpus_shaped_paragraph_is_redacted(tmp_path: Path) -> None:
    """One <w:t> per <w:r>, plain body paragraph — exactly what corpus/docx_builder.py emits."""
    surfaces, _ = _redact_and_read(tmp_path, "ctl_body", _p(_r(_t("Predávajúci: " + NAME))))
    _assert_gone(surfaces, NAME)


def test_control_corpus_shaped_table_cell_is_redacted(tmp_path: Path) -> None:
    body = "<w:tbl><w:tr><w:tc>" + _p(_r(_t("Predávajúci: " + NAME))) + "</w:tc></w:tr></w:tbl>"
    surfaces, _ = _redact_and_read(tmp_path, "ctl_cell", body)
    _assert_gone(surfaces, NAME)


# =========================================================================== B1
# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
def test_r3_b1_second_w_t_in_a_run_must_not_survive_redaction(tmp_path: Path) -> None:
    """A Shift+Enter inside a formatting run: <w:r><w:t>..</w:t><w:br/><w:t>..</w:t></w:r>."""
    body = _p(_r(_t("Predávajúci: " + NAME), "<w:br/>", _t("Kupujúci: " + NAME2)))
    surfaces, _ = _redact_and_read(tmp_path, "b1_br", body)
    _assert_gone(surfaces, NAME2)


# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
def test_r3_b1_tab_split_run_value_must_not_survive(tmp_path: Path) -> None:
    body = _p(_r(_t("Meno a priezvisko:"), "<w:tab/>", _t(NAME)))
    surfaces, _ = _redact_and_read(tmp_path, "b1_tab", body)
    _assert_gone(surfaces, NAME)


# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
def test_r3_b1_last_rendered_page_break_split_run(tmp_path: Path) -> None:
    body = _p(_r(_t("Predávajúci: " + NAME), "<w:lastRenderedPageBreak/>",
                 _t(" a kupujúci " + NAME2)))
    surfaces, _ = _redact_and_read(tmp_path, "b1_lrpb", body)
    _assert_gone(surfaces, NAME2)


# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
def test_r3_b1_inner_content_children_are_not_multiplied(tmp_path: Path) -> None:
    body = _p(_r(_t("Meno a priezvisko:"), "<w:tab/>", _t(NAME)))
    _, document_xml = _redact_and_read(tmp_path, "b1_tabcount", body)
    assert document_xml.count("<w:tab/>") == 1, "the single <w:tab/> was multiplied"


# =========================================================================== B2..B5
# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
def test_r3_b2_hyperlink_display_text_must_be_redacted(tmp_path: Path) -> None:
    body = _p(_r(_t("E-mail: ")),
              '<w:hyperlink r:id="rIdH1">' + _r(_t("jan.novak@advokat.sk")) + "</w:hyperlink>")
    surfaces, _ = _redact_and_read(tmp_path, "b2_link", body)
    _assert_gone(surfaces, "jan.novak@advokat.sk")


# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
def test_r3_b3_nested_table_must_be_redacted(tmp_path: Path) -> None:
    inner = "<w:tbl><w:tr><w:tc>" + _p(_r(_t("Predávajúci: " + NAME))) + "</w:tc></w:tr></w:tbl>"
    body = ("<w:tbl><w:tr><w:tc>" + _p(_r(_t("Zmluvné strany"))) + inner
            + _p(_r(_t("x"))) + "</w:tc></w:tr></w:tbl>")
    surfaces, _ = _redact_and_read(tmp_path, "b3_nested", body)
    _assert_gone(surfaces, NAME)


# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
def test_r3_b4_content_control_paragraph_must_be_redacted(tmp_path: Path) -> None:
    body = "<w:sdt><w:sdtPr/><w:sdtContent>" + _p(_r(_t("Predávajúci: " + NAME))) + \
           "</w:sdtContent></w:sdt>"
    surfaces, _ = _redact_and_read(tmp_path, "b4_sdt", body)
    _assert_gone(surfaces, NAME)


# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
def test_r3_b5_table_inside_textbox_must_be_redacted(tmp_path: Path) -> None:
    inner = "<w:tbl><w:tr><w:tc>" + _p(_r(_t("Podpis: " + NAME))) + "</w:tc></w:tr></w:tbl>"
    body = _p(_r('<w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox>'
                 "<w:txbxContent>" + inner + "</w:txbxContent></v:textbox></v:shape></w:pict>"))
    surfaces, _ = _redact_and_read(tmp_path, "b5_txbx", body)
    _assert_gone(surfaces, NAME)


# =========================================================================== group A (text)
def _auto_covers(text: str, needle: str, known: list[str] | None = None) -> bool:
    cands = detect(text, known or [])
    i = text.find(needle)
    assert i >= 0
    j = i + len(needle)
    covered = [False] * (j - i)
    for c in cands:
        if not c.auto:
            continue
        for k in range(max(c.start, i) - i, min(c.end, j) - i):
            covered[k] = True
    return all(covered)


def test_control_role_anchored_slovak_name_is_fully_covered() -> None:
    assert _auto_covers("Zmluvné strany: predávajúci Ján Kováč, bytom Košice.", "Ján Kováč")


# FIXED 2026-09-17 (mutation gate surname_caps arm): detect/name_anchors.py now has a
# separate `_CAPS` token class (an all-caps Slovak surname next to a role/title anchor is
# the continental legal convention, not a relaxation of `_CAP`) included in the STRICT
# `_NAME_SEQ`, so this no longer depends on `document_is_single_case`. The marker is gone
# rather than flipped to xpass: a finding that has been fixed must become an ordinary
# regression test, or a later regression puts it back to "xfail" -- the state this file
# calls normal -- and nobody notices the fix was undone.
def test_r3_a5_uppercase_surname_in_a_mixed_case_document() -> None:
    assert _auto_covers(
        "Zmluvné strany: predávajúci Hartmut SCHNEIDER, bytom Viedeň.", "Hartmut SCHNEIDER"
    )


# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
@pytest.mark.parametrize(
    "text,needle",
    [
        ("Vec vedená pod V‑1234/2025 na katastri.", "V‑1234/2025"),
        ("Číslo klienta: KL‑99321", "KL‑99321"),
        ("Vozidlo EČV BA‑123AB je vo vlastníctve.", "BA‑123AB"),
    ],
)
def test_r3_a6_non_breaking_hyphen_in_an_identifier(text: str, needle: str) -> None:
    assert _auto_covers(text, needle)


def test_control_ascii_hyphen_identifiers_are_covered() -> None:
    assert _auto_covers("Vec vedená pod V-1234/2025 na katastri.", "V-1234/2025")
    assert _auto_covers("Číslo klienta: KL-99321", "KL-99321")


@pytest.mark.xfail(
    reason="R3-A7: _SPISOVA_ZNACKA_RE knows only the fused 1-2 letter agendas and the "
           "cadastral letter-dash form",
    strict=True,
)
@pytest.mark.parametrize(
    "text,needle",
    [
        ("Nález Ústavného súdu SR sp. zn. II. ÚS 45/2024.", "II. ÚS 45/2024"),
        ("Rozsudok Najvyššieho súdu sp. zn. 1Cdo/12/2023.", "1Cdo/12/2023"),
        ("Okresný súd Košice I, sp. zn. 2 C 45/2019, rozhodol.", "2 C 45/2019"),
        ("Uznesenie sp. zn. 5Obdo/7/2022 sa zrušuje.", "5Obdo/7/2022"),
    ],
)
def test_r3_a7_spisova_znacka_shapes_the_corpus_never_authors(text: str, needle: str) -> None:
    assert _auto_covers(text, needle)


def test_control_corpus_spisova_znacka_shapes_are_covered() -> None:
    assert _auto_covers("Okresný súd, sp. zn. 12Cb/345/2025, rozhodol.", "12Cb/345/2025")


@pytest.mark.xfail(
    reason="R3-A10: normalize() folds Cyrillic homoglyphs unconditionally, so a genuinely "
           "Cyrillic name becomes mixed-script and matches nothing — including the user's "
           "own known-entity string",
    strict=True,
)
def test_r3_a10_genuinely_cyrillic_name_with_the_users_own_entity_list() -> None:
    name = "Олександр " \
           "Ковальчук"
    assert _auto_covers(f"Kupujúci {name} prehlasuje, že prevzal vec.", name, [name])


# FIXED 2026-09-17, overnight run. The marker is gone rather than flipped to xpass: a finding that has been
# fixed must become an ordinary regression test, or a later regression puts it back to
# "xfail" -- the state this file calls normal -- and nobody notices the fix was undone.
# BOTH tokens must carry the deformation, and that is not pedantry: with only ONE token
# deformed the other still matches, the bare-name heuristic emits the whole span as
# auto=False, and detect()'s containment PROMOTION rule lifts it to auto=True — so a
# single-token fixture measures the promotion rule, not the entity matcher. Verified: a
# one-token variant XPASSes here.
@pytest.mark.parametrize("deformed", [
    "Al​essandro Be​rtolini",        # zero-width space, both tokens
    "Ale­ssandro Ber­tolini",        # soft hyphen, both tokens
    "Аlessandro Bertоlini",          # Cyrillic А and о, both tokens
])
def test_r3_a11_known_entity_list_is_not_normalized(deformed: str) -> None:
    text = "Dňa 3. marca 2024 prevzal Alessandro Bertolini vec do úschovy."
    assert _auto_covers(text, "Alessandro Bertolini", [deformed])


def test_control_clean_known_entity_list_matches() -> None:
    text = "Dňa 3. marca 2024 prevzal Alessandro Bertolini vec do úschovy."
    assert _auto_covers(text, "Alessandro Bertolini", ["Alessandro Bertolini"])


# =========================================================================== C1 (PDF)
@pytest.mark.xfail(
    reason="R3-C1: per-glyph text placement with tracking makes get_text() return the name "
           "with intra-word spaces — detect() finds nothing AND eval/extract reports the same "
           "mangled string, so the leak gate greps CLEAN on an unredacted document",
    strict=True,
)
def test_r3_c1_letterspaced_pdf_text_layer_is_still_detected(tmp_path: Path) -> None:
    fitz = pytest.importorskip("fitz")
    from writer.pdf_body import redact_pdf

    line = "Predavajuci: Jan Novak"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    font = fitz.Font("helv")
    x = 72.0
    for ch in line:
        page.insert_text((x, 720), ch, fontsize=11, fontname="helv")
        x += font.text_length(ch, fontsize=11) * 1.4
    src = tmp_path / "c1_in.pdf"
    dst = tmp_path / "c1_out.pdf"
    doc.save(str(src), garbage=4, deflate=True)
    doc.close()
    redact_pdf(str(src), str(dst), known_entities=["Jan Novak"])
    with fitz.open(str(dst)) as d:
        out = "\n".join(p.get_text("text") for p in d)
    # The glyphs are still on the page; the only question is whether anything removed them.
    assert "J" not in out.split("Predavajuci")[-1], (
        "the name's glyphs are still drawn on the page after redaction"
    )
