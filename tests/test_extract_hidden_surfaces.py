"""Red-team grader: every document surface that can carry text the extractor could not read.

``tests/test_extract.py`` proves the extractor finds every surface the CORPUS seeds. That is
a floor, not a ceiling: a surface the corpus builder never writes to is a surface the leak
gate has never once been asked about, and a leak hiding there greps clean. This module is the
adversarial complement — hand-built fixtures (no ``corpus/`` import, CONTRACTS_v11 §11) that
hide a unique marker in every surface a real Word/Acrobat file offers, including the ones no
fixture in this repo has ever produced.

Each surface is asserted twice:

* ``test_*_surface_is_extractable`` — the marker is found by the CURRENT extractor (GREEN).
* ``test_*_gap_is_real_under_the_legacy_extractor`` — the marker is NOT found by
  ``_legacy_*_surfaces``, a faithful copy of the pre-hardening extraction algorithm kept in
  this file (RED). This is the mutation-test discipline ``tests/test_harness_mutations.py``
  already uses: without it, a fixture that happens to place its marker somewhere the old code
  could already read would pass and prove nothing about the gap it claims to close.

The legacy copies are frozen on purpose. They are not a second implementation to maintain —
they are the evidence that each gap was real, pinned so it cannot quietly come back.
"""
from __future__ import annotations

import re
import zipfile
import zlib
from pathlib import Path

import fitz
import pytest
from lxml import etree

from eval.extract import (
    S_ANNOTATIONS,
    S_APP,
    S_ATTACHMENTS,
    S_BINARY_PARTS,
    S_COMMENTS,
    S_CORE,
    S_CUSTOM,
    S_DOCUMENT,
    S_ENDNOTES,
    S_FOOTER,
    S_FOOTNOTES,
    S_FORM_FIELDS,
    S_HEADER,
    S_INFO,
    S_LINKS,
    S_OTHER_XML,
    S_OUTLINE,
    S_PDF_OBJECTS,
    S_RAW_BYTES,
    S_RELS,
    S_TEXT_LAYER,
    S_XMP,
    S_XML_ATTRS,
    extract,
    surface_for_gt_part,
)

# --------------------------------------------------------------------------- DOCX fixture
_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"'
)

# One unique marker per surface: a leak report that names the wrong surface is as useless as
# no report, so no two surfaces may share a string.
DOCX_MARKERS = {
    "docpr_descr": "RTMARKER01NOVAK",
    "docpr_title": "RTMARKER02NOVAK",
    "ins_author": "RTMARKER03NOVAK",
    "del_author": "RTMARKER04NOVAK",
    "comment_author": "RTMARKER05NOVAK",
    "people_xml": "RTMARKER06NOVAK",
    "custom_xml": "RTMARKER07NOVAK",
    "header_default": "RTMARKER08NOVAK",
    "header_even": "RTMARKER09NOVAK",
    "header_first": "RTMARKER10NOVAK",
    "footer_default": "RTMARKER11NOVAK",
    "footer_even": "RTMARKER12NOVAK",
    "footer_first": "RTMARKER13NOVAK",
    "header_second_section": "RTMARKER14NOVAK",
    "footnote": "RTMARKER15NOVAK",
    "endnote": "RTMARKER16NOVAK",
    "comment_text": "RTMARKER17NOVAK",
    "vml_textbox": "RTMARKER18NOVAK",
    "drawingml_textbox": "RTMARKER19NOVAK",
    "smartart_diagram": "RTMARKER20NOVAK",
    "chart": "RTMARKER21NOVAK",
    "embedded_ole_object": "RTMARKER22NOVAK",
    "hyperlink_target_mailto": "RTMARKER23NOVAK",
    "hidden_vanish_text": "RTMARKER24NOVAK",
    "white_text": "RTMARKER25NOVAK",
    "custom_xml_item": "RTMARKER26NOVAK",
    "field_instrtext": "RTMARKER27NOVAK",
    "glossary_document": "RTMARKER28NOVAK",
    "attached_template_path": "RTMARKER29NOVAK",
    "core_xml": "RTMARKER30NOVAK",
    "app_xml": "RTMARKER31NOVAK",
    "footer_rels_mailto": "RTMARKER32NOVAK",
    "comment_initials": "RTMARKER33NOVAK",
    "settings_docvar": "RTMARKER34NOVAK",
}

# The surfaces the pre-hardening extractor could NOT see. Pinned: this list IS the finding.
DOCX_GAPS = (
    "docpr_descr",
    "docpr_title",
    "ins_author",
    "del_author",
    "comment_author",
    "comment_initials",
    "people_xml",
    "smartart_diagram",
    "chart",
    "embedded_ole_object",
    "hyperlink_target_mailto",
    "footer_rels_mailto",
    "custom_xml_item",
    "glossary_document",
    "attached_template_path",
    "settings_docvar",
)


def _p(text: str) -> str:
    return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _hdr(text: str, tag: str = "hdr") -> str:
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:{tag} {_NS}>{_p(text)}</w:{tag}>'


def _document_xml(m: dict[str, str]) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document {_NS}><w:body>
  <w:p><w:r><w:t>Zmluva o prevode nehnutelnosti.</w:t></w:r></w:p>
  <w:p><w:r><w:drawing><wp:inline><wp:extent cx="1000000" cy="500000"/>
    <wp:docPr id="1" name="Obrazok 1" descr="Podpis: {m['docpr_descr']}" title="{m['docpr_title']}"/>
    <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"/></a:graphic>
  </wp:inline></w:drawing></w:r></w:p>
  <w:p>
    <w:ins w:id="101" w:author="{m['ins_author']}" w:date="2024-01-01T00:00:00Z">
      <w:r><w:t>vlozeny text</w:t></w:r></w:ins>
    <w:del w:id="102" w:author="{m['del_author']}" w:date="2024-01-01T00:00:00Z">
      <w:r><w:delText>zmazany text</w:delText></w:r></w:del>
  </w:p>
  <w:p><w:r><w:pict><v:shape type="#_x0000_t202" style="width:240pt;height:48pt">
    <v:textbox><w:txbxContent>{_p(m['vml_textbox'])}</w:txbxContent></v:textbox>
  </v:shape></w:pict></w:r></w:p>
  <w:p><w:r><w:drawing><wp:inline><wp:extent cx="1000000" cy="500000"/>
    <wp:docPr id="2" name="TextBox 2"/>
    <a:graphic><a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
      <wps:wsp><wps:txbx><w:txbxContent>{_p(m['drawingml_textbox'])}</w:txbxContent></wps:txbx></wps:wsp>
    </a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>
  <w:p><w:r><w:rPr><w:vanish/></w:rPr><w:t>{m['hidden_vanish_text']}</w:t></w:r></w:p>
  <w:p><w:r><w:rPr><w:color w:val="FFFFFF"/></w:rPr><w:t>{m['white_text']}</w:t></w:r></w:p>
  <w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>
    <w:r><w:instrText xml:space="preserve"> HYPERLINK "mailto:{m['field_instrtext']}@firma.sk" </w:instrText></w:r>
    <w:r><w:fldChar w:fldCharType="separate"/></w:r>
    <w:r><w:t>[MENO_1]</w:t></w:r>
    <w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>
  <w:p><w:hyperlink r:id="rId100"><w:r><w:t>[MENO_1]</w:t></w:r></w:hyperlink></w:p>
  <w:p><w:r><w:footnoteReference w:id="1"/></w:r></w:p>
  <w:p><w:r><w:endnoteReference w:id="1"/></w:r></w:p>
  <w:p><w:commentRangeStart w:id="0"/><w:r><w:t>kotva</w:t></w:r>
    <w:commentRangeEnd w:id="0"/><w:r><w:commentReference w:id="0"/></w:r></w:p>
  <w:sectPr>
    <w:headerReference w:type="default" r:id="rId11"/>
    <w:headerReference w:type="even" r:id="rId12"/>
    <w:headerReference w:type="first" r:id="rId13"/>
    <w:footerReference w:type="default" r:id="rId14"/>
    <w:footerReference w:type="even" r:id="rId15"/>
    <w:footerReference w:type="first" r:id="rId16"/>
  </w:sectPr>
</w:body></w:document>"""


def _rel(rid: str, rtype: str, target: str, external: bool = False) -> str:
    mode = ' TargetMode="External"' if external else ""
    return (
        f'<Relationship Id="{rid}" '
        f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{rtype}" '
        f'Target="{target}"{mode}/>'
    )


def _rels(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{body}</Relationships>"
    )


def build_docx(path: Path, m: dict[str, str]) -> Path:
    """A .docx carrying one distinct marker in every surface a Word file can hide text in."""
    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="jpeg" ContentType="image/jpeg"/>'
            '<Default Extension="bin" ContentType="application/vnd.openxmlformats-officedocument.oleObject"/>'
            "</Types>"
        ),
        "_rels/.rels": _rels(_rel("rId1", "officeDocument", "word/document.xml")),
        "word/document.xml": _document_xml(m),
        "word/_rels/document.xml.rels": _rels(
            _rel("rId100", "hyperlink", f"mailto:{m['hyperlink_target_mailto']}@firma.sk", True)
            + "".join(
                _rel(f"rId1{i}", kind, f"{kind}{n}.xml")
                for i, (kind, n) in enumerate(
                    [("header", 1), ("header", 2), ("header", 3),
                     ("footer", 1), ("footer", 2), ("footer", 3)], start=1
                )
            )
        ),
        "word/header1.xml": _hdr(m["header_default"]),
        "word/header2.xml": _hdr(m["header_even"]),
        "word/header3.xml": _hdr(m["header_first"]),
        # second section's header — proves the glob reaches EVERY header part, not just the
        # ones the first sectPr references
        "word/header4.xml": _hdr(m["header_second_section"]),
        "word/footer1.xml": _hdr(m["footer_default"], "ftr"),
        "word/footer2.xml": _hdr(m["footer_even"], "ftr"),
        "word/footer3.xml": _hdr(m["footer_first"], "ftr"),
        "word/_rels/footer1.xml.rels": _rels(
            _rel("rId1", "hyperlink", f"mailto:{m['footer_rels_mailto']}@firma.sk", True)
        ),
        "word/footnotes.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:footnotes {_NS}>'
            f'<w:footnote w:id="1">{_p(m["footnote"])}</w:footnote></w:footnotes>'
        ),
        "word/endnotes.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:endnotes {_NS}>'
            f'<w:endnote w:id="1">{_p(m["endnote"])}</w:endnote></w:endnotes>'
        ),
        "word/comments.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:comments {_NS}>'
            f'<w:comment w:id="0" w:author="{m["comment_author"]}" '
            f'w:initials="{m["comment_initials"]}" w:date="2024-01-01T00:00:00Z">'
            f'{_p(m["comment_text"])}</w:comment></w:comments>'
        ),
        "word/people.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">'
            f'<w15:person w15:author="{m["people_xml"]}">'
            f'<w15:presenceInfo w15:providerId="AD" w15:userId="{m["people_xml"]}@firma.sk"/>'
            "</w15:person></w15:people>"
        ),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<dc:creator>{m["core_xml"]}</dc:creator></cp:coreProperties>'
        ),
        "docProps/app.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'extended-properties"><Company>{m["app_xml"]}</Company></Properties>'
        ),
        "docProps/custom.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            'custom-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/'
            '2006/docPropsVTypes"><property fmtid="{D5CDD505}" pid="2" name="Klient">'
            f'<vt:lpwstr>{m["custom_xml"]}</vt:lpwstr></property></Properties>'
        ),
        "word/diagrams/data1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<dgm:dataModel xmlns:dgm="http://schemas.openxmlformats.org/drawingml/2006/diagram" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><dgm:ptLst>'
            f'<dgm:pt modelId="1"><dgm:t><a:p><a:r><a:t>{m["smartart_diagram"]}</a:t></a:r>'
            "</a:p></dgm:t></dgm:pt></dgm:ptLst></dgm:dataModel>"
        ),
        "word/charts/chart1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><c:title><c:tx>'
            f'<c:rich><a:p><a:r><a:t>{m["chart"]}</a:t></a:r></a:p></c:rich>'
            "</c:tx></c:title></c:chartSpace>"
        ),
        # OLE storages keep their strings as UTF-16LE inside a CFB container
        "word/embeddings/oleObject1.bin": (
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 24
            + m["embedded_ole_object"].encode("utf-16-le") + b"\x00" * 16
        ),
        "customXml/item1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<klient xmlns="urn:firma"><meno>{m["custom_xml_item"]}</meno></klient>'
        ),
        "word/settings.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings {_NS}>'
            f'<w:docVars><w:docVar w:name="Klient" w:val="{m["settings_docvar"]}"/></w:docVars>'
            "</w:settings>"
        ),
        "word/_rels/settings.xml.rels": _rels(
            _rel(
                "rId1",
                "attachedTemplate",
                f"file:///C:\\Users\\{m['attached_template_path']}\\Sablony\\zmluva.dotx",
                True,
            )
        ),
        "word/glossary/document.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:glossaryDocument {_NS}><w:docParts><w:docPart><w:docPartBody>"
            f'{_p(m["glossary_document"])}</w:docPartBody></w:docPart></w:docParts>'
            "</w:glossaryDocument>"
        ),
        # a rendered picture of page 1 — see KNOWN BLIND SPOTS in redteam/FINDINGS.md
        "docProps/thumbnail.jpeg": b"\xff\xd8\xff\xe0JFIF-fake-thumbnail\xff\xd9",
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


@pytest.fixture(scope="module")
def docx_file(tmp_path_factory) -> Path:
    return build_docx(tmp_path_factory.mktemp("redteam") / "hidden_surfaces.docx", DOCX_MARKERS)


# ------------------------------------------------------------------ legacy DOCX extractor
def _legacy_docx_surfaces(path: Path) -> dict[str, str]:
    """The pre-hardening ``_extract_docx``, verbatim: text nodes of the named parts only.

    Kept so every claimed gap is PROVED, not asserted — a fixture whose marker this function
    can already read is not evidence of anything.
    """
    def itertext(root: etree._Element) -> str:
        return "".join(root.itertext())

    with zipfile.ZipFile(path) as z:
        names = z.namelist()

        def content(name: str) -> str:
            return itertext(etree.fromstring(z.read(name))) if name in names else ""

        def raw(name: str) -> str:
            return z.read(name).decode("utf-8") if name in names else ""

        def content_glob(pattern: str) -> str:
            return "".join(content(n) for n in names if re.search(pattern, n))

        return {
            S_DOCUMENT: content("word/document.xml"),
            S_HEADER: content_glob(r"header\d*\.xml"),
            S_FOOTER: content_glob(r"footer\d*\.xml"),
            S_FOOTNOTES: content("word/footnotes.xml"),
            S_ENDNOTES: content("word/endnotes.xml"),
            S_COMMENTS: content("word/comments.xml"),
            S_CORE: raw("docProps/core.xml"),
            S_APP: raw("docProps/app.xml"),
            S_CUSTOM: raw("docProps/custom.xml"),
        }


# ------------------------------------------------------------------------- DOCX assertions
@pytest.mark.parametrize("key", sorted(DOCX_MARKERS))
def test_docx_hidden_surface_is_extractable(docx_file, key):
    """GREEN: every hidable DOCX surface reaches ``extract()``."""
    marker = DOCX_MARKERS[key]
    res = extract(docx_file)
    found = [s for s, text in res.by_surface.items() if marker in text]
    assert found, (
        f"{key}: {marker!r} is in the document but no extracted surface contains it — "
        "the leak gate would grep this location and report clean"
    )
    assert marker in res.full_text


@pytest.mark.parametrize("key", DOCX_GAPS)
def test_docx_gap_is_real_under_the_legacy_extractor(docx_file, key):
    """RED: the same fixture, read by the pre-hardening algorithm, misses these surfaces."""
    marker = DOCX_MARKERS[key]
    legacy = _legacy_docx_surfaces(docx_file)
    assert not [s for s, text in legacy.items() if marker in text], (
        f"{key}: the legacy extractor CAN see {marker!r} — this fixture does not prove the "
        "gap it claims to, fix the fixture rather than the assertion"
    )


def test_docx_attribute_values_are_extracted_at_all(docx_file):
    """The headline gap: ``itertext()`` walks text nodes, so attributes were never read."""
    res = extract(docx_file)
    for key in ("docpr_descr", "docpr_title", "ins_author", "del_author", "comment_author"):
        assert DOCX_MARKERS[key] in res.by_surface[S_XML_ATTRS], key


def test_docx_hyperlink_target_is_extracted_even_when_display_text_is_redacted(docx_file):
    """A ``mailto:`` relationship target leaks a name and an address while the run text that
    the redactor rewrote reads ``[MENO_1]``."""
    res = extract(docx_file)
    assert "[MENO_1]" in res.by_surface[S_DOCUMENT]
    assert DOCX_MARKERS["hyperlink_target_mailto"] in res.by_surface[S_RELS]
    assert DOCX_MARKERS["footer_rels_mailto"] in res.by_surface[S_RELS]


def test_docx_separate_parts_are_extracted(docx_file):
    """SmartArt, charts, the content-control data store and the glossary are their own OPC
    parts; nothing in the named-surface list ever opened them."""
    res = extract(docx_file)
    other = res.by_surface[S_OTHER_XML]
    for key in ("smartart_diagram", "chart", "custom_xml_item", "glossary_document"):
        assert DOCX_MARKERS[key] in other, key
    # word/people.xml is a separate part AND keeps its author in an attribute, so it needs
    # both additions at once to be readable at all.
    assert DOCX_MARKERS["people_xml"] in res.by_surface[S_XML_ATTRS]


def test_docx_binary_part_names_and_strings_are_reported(docx_file):
    """A part whose pixels cannot be read must still be VISIBLE (by name) in a report, and
    an OLE storage's UTF-16LE strings must be read."""
    binaries = extract(docx_file).by_surface[S_BINARY_PARTS]
    assert "docProps/thumbnail.jpeg" in binaries, "a page-1 rendering must not vanish silently"
    assert DOCX_MARKERS["embedded_ole_object"] in binaries


def test_docx_hidden_and_white_text_are_not_skipped(docx_file):
    """``w:vanish`` and white-on-white text are still extractable text: a redactor that only
    hides them has redacted nothing."""
    doc_text = extract(docx_file).by_surface[S_DOCUMENT]
    assert DOCX_MARKERS["hidden_vanish_text"] in doc_text
    assert DOCX_MARKERS["white_text"] in doc_text


def test_docx_headers_and_footers_cover_every_variant_and_section(docx_file):
    """first-page / even-page / default, and a header belonging to a second section."""
    res = extract(docx_file)
    for key in ("header_default", "header_even", "header_first", "header_second_section"):
        assert DOCX_MARKERS[key] in res.by_surface[S_HEADER], key
    for key in ("footer_default", "footer_even", "footer_first"):
        assert DOCX_MARKERS[key] in res.by_surface[S_FOOTER], key


def test_docx_custom_properties_are_really_extracted(docx_file):
    """``docProps/custom.xml`` was claimed to be covered; the corpus never emits one, so it
    had never actually been exercised. It is."""
    assert DOCX_MARKERS["custom_xml"] in extract(docx_file).by_surface[S_CUSTOM]


def test_docx_unparseable_part_is_not_silently_dropped(tmp_path):
    """A part that is not well-formed XML must fall back to its raw bytes, never be skipped —
    a malformed part is exactly where someone would hide something."""
    path = build_docx(tmp_path / "broken.docx", DOCX_MARKERS)
    data = {n: zipfile.ZipFile(path).read(n) for n in zipfile.ZipFile(path).namelist()}
    data["word/charts/chart1.xml"] = b"<c:chartSpace><not-closed>RTMARKERBROKEN"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in data.items():
            z.writestr(name, blob)
    assert "RTMARKERBROKEN" in extract(path).full_text


# ---------------------------------------------------------------------------- PDF fixture
PDF_MARKERS = {
    "toc_bookmark": "RTPDF01NOVAK",
    "link_uri_mailto": "RTPDF02NOVAK",
    "annot_author": "RTPDF03NOVAK",
    "annot_subject": "RTPDF04NOVAK",
    "formfield_name": "RTPDF05NOVAK",
    "formfield_value": "RTPDF06NOVAK",
    "ocg_layer_name": "RTPDF07NOVAK",
    "outside_cropbox": "RTPDF08NOVAK",
    "rotated_text": "RTPDF09NOVAK",
    "tiny_font": "RTPDF10NOVAK",
    "embfile_name": "RTPDF11NOVAK",
    "embfile_description": "RTPDF12NOVAK",
    "custom_info_key": "RTPDF13NOVAK",
    "catalog_extra_key": "RTPDF14NOVAK",
    "ocg_hidden_text": "RTPDF15NOVAK",
    "attachment_body": "RTPDF16NOVAK",
    "annot_content": "RTPDF17NOVAK",
    "info_author": "RTPDF18NOVAK",
    "xmp_creator": "RTPDF19NOVAK",
    "text_layer": "RTPDF20NOVAK",
    "formfield_label": "RTPDF21NOVAK",
    "white_text": "RTPDF22NOVAK",
    "invisible_render_mode": "RTPDF23NOVAK",
}

PDF_GAPS = (
    "toc_bookmark",
    "link_uri_mailto",
    "annot_author",
    "annot_subject",
    "formfield_name",
    "formfield_label",
    "ocg_layer_name",
    "ocg_hidden_text",
    "outside_cropbox",
    "embfile_name",
    "embfile_description",
    "custom_info_key",
    "catalog_extra_key",
)


def build_pdf(path: Path, m: dict[str, str]) -> Path:
    """A .pdf carrying one distinct marker in every surface an Acrobat file can hide text in."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 100), f"Zmluva {m['text_layer']}", fontsize=11)
    page.insert_text((60, 130), m["rotated_text"], fontsize=11, rotate=90)
    page.insert_text((60, 160), m["tiny_font"], fontsize=0.6)
    page.insert_text((60, 190), m["white_text"], fontsize=11, color=(1, 1, 1))
    page.insert_text((60, 220), m["invisible_render_mode"], fontsize=11, render_mode=3)
    page.insert_text((60, 760), m["outside_cropbox"], fontsize=11)

    annot = page.add_freetext_annot(fitz.Rect(60, 250, 400, 290), m["annot_content"], fontsize=10)
    annot.set_info(title=m["annot_author"], subject=m["annot_subject"])
    annot.update()

    page.insert_text((60, 320), "[MENO_1]", fontsize=11)
    page.insert_link({
        "kind": fitz.LINK_URI,
        "from": fitz.Rect(60, 308, 200, 324),
        "uri": f"mailto:{m['link_uri_mailto']}@firma.sk",
    })

    widget = fitz.Widget()
    widget.field_name = m["formfield_name"]
    widget.field_label = m["formfield_label"]
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_value = m["formfield_value"]
    widget.rect = fitz.Rect(60, 360, 300, 380)
    page.add_widget(widget)

    ocg = doc.add_ocg(m["ocg_layer_name"], on=False)
    page.insert_text((60, 420), m["ocg_hidden_text"], fontsize=11, oc=ocg)

    doc.embfile_add(
        f"{m['embfile_name']}.txt",
        f"Priloha {m['attachment_body']}".encode("utf-8"),
        desc=m["embfile_description"],
    )
    doc.set_toc([[1, f"Klient {m['toc_bookmark']}", 1]])
    doc.set_metadata({"author": m["info_author"], "title": "Zmluva"})
    doc.set_xml_metadata(
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator><rdf:Seq><rdf:li>{m['xmp_creator']}</rdf:li></rdf:Seq></dc:creator>"
        '</rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    )
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()

    # A custom /Info key and a catalogue entry that no typed PyMuPDF API models, plus the
    # CropBox that hides the text drawn at y=760.
    doc = fitz.open(str(path))
    info = doc.xref_get_key(-1, "Info")[1]
    if info:
        doc.xref_set_key(int(info.split()[0]), "Klient", f"({m['custom_info_key']})")
    doc.xref_set_key(doc.pdf_catalog(), "RTNamedDest", f"({m['catalog_extra_key']})")
    doc[0].set_cropbox(fitz.Rect(0, 0, 595, 700))
    doc.save(str(path), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    return path


@pytest.fixture(scope="module")
def pdf_file(tmp_path_factory) -> Path:
    return build_pdf(tmp_path_factory.mktemp("redteam") / "hidden_surfaces.pdf", PDF_MARKERS)


def _legacy_pdf_surfaces(path: Path) -> dict[str, str]:
    """The pre-hardening ``_extract_pdf``, verbatim."""
    doc = fitz.open(path)
    try:
        text_layer = "\n".join(p.get_text() for p in doc).replace("\xad", "-")
        annotations = " ".join((a.info.get("content") or "") for p in doc for a in p.annots())
        form_fields = " ".join((w.field_value or "") for p in doc for w in p.widgets())
        attachments = " ".join(
            doc.embfile_get(n).decode("utf-8", "replace") for n in doc.embfile_names()
        )
        info = " ".join(str(v) for v in (doc.metadata or {}).values())
        xmp = doc.get_xml_metadata() or ""
    finally:
        doc.close()
    return {
        S_TEXT_LAYER: text_layer,
        S_ANNOTATIONS: annotations,
        S_FORM_FIELDS: form_fields,
        S_ATTACHMENTS: attachments,
        S_INFO: info,
        S_XMP: xmp,
    }


# -------------------------------------------------------------------------- PDF assertions
@pytest.mark.parametrize("key", sorted(PDF_MARKERS))
def test_pdf_hidden_surface_is_extractable(pdf_file, key):
    marker = PDF_MARKERS[key]
    res = extract(pdf_file)
    found = [s for s, text in res.by_surface.items() if marker in text]
    assert found, (
        f"{key}: {marker!r} is in the PDF but no extracted surface contains it — "
        "the leak gate would grep this location and report clean"
    )
    assert marker in res.full_text


@pytest.mark.parametrize("key", PDF_GAPS)
def test_pdf_gap_is_real_under_the_legacy_extractor(pdf_file, key):
    marker = PDF_MARKERS[key]
    legacy = _legacy_pdf_surfaces(pdf_file)
    assert not [s for s, text in legacy.items() if marker in text], (
        f"{key}: the legacy extractor CAN see {marker!r} — this fixture does not prove the "
        "gap it claims to, fix the fixture rather than the assertion"
    )


def test_pdf_text_outside_the_cropbox_is_recovered(pdf_file):
    """MuPDF clips text extraction to the CropBox. Shrinking the box is a one-line edit that
    made a whole block of text extract as nothing while any PDF editor restores it."""
    res = extract(pdf_file)
    assert PDF_MARKERS["outside_cropbox"] in res.by_surface[S_TEXT_LAYER]


def test_pdf_text_in_a_hidden_layer_is_recovered(pdf_file):
    """Text in an optional-content group whose default state is OFF is not emitted by
    ``get_text()`` — and is one checkbox away from visible in any viewer."""
    res = extract(pdf_file)
    assert PDF_MARKERS["ocg_hidden_text"] in res.by_surface[S_TEXT_LAYER]


def test_pdf_rotated_tiny_white_and_invisible_text_reach_the_text_layer(pdf_file):
    """Claimed to be covered already — proved, not assumed. Render mode 3 (invisible text) is
    the one that matters most: it is what an OCR layer under a scan uses."""
    text = extract(pdf_file).by_surface[S_TEXT_LAYER]
    for key in ("rotated_text", "tiny_font", "white_text", "invisible_render_mode"):
        assert PDF_MARKERS[key] in text, key


def test_pdf_link_target_is_extracted_even_when_display_text_is_redacted(pdf_file):
    res = extract(pdf_file)
    assert "[MENO_1]" in res.by_surface[S_TEXT_LAYER]
    assert PDF_MARKERS["link_uri_mailto"] in res.by_surface[S_LINKS]


def test_pdf_outline_and_annotation_authorship_are_extracted(pdf_file):
    res = extract(pdf_file)
    assert PDF_MARKERS["toc_bookmark"] in res.by_surface[S_OUTLINE]
    assert PDF_MARKERS["annot_author"] in res.by_surface[S_ANNOTATIONS]
    assert PDF_MARKERS["annot_subject"] in res.by_surface[S_ANNOTATIONS]


def test_pdf_form_field_names_and_labels_are_extracted(pdf_file):
    """A field NAMED ``rodne_cislo_novak`` leaks even with an empty value."""
    fields = extract(pdf_file).by_surface[S_FORM_FIELDS]
    assert PDF_MARKERS["formfield_name"] in fields
    assert PDF_MARKERS["formfield_label"] in fields


def test_pdf_attachment_name_and_description_are_extracted(pdf_file):
    attachments = extract(pdf_file).by_surface[S_ATTACHMENTS]
    assert PDF_MARKERS["embfile_name"] in attachments
    assert PDF_MARKERS["embfile_description"] in attachments


def test_pdf_objects_catch_what_the_typed_apis_do_not_model(pdf_file):
    """Custom /Info keys, catalogue entries and OCG names have no PyMuPDF accessor."""
    objects = extract(pdf_file).by_surface[S_PDF_OBJECTS]
    for key in ("custom_info_key", "catalog_extra_key", "ocg_layer_name"):
        assert PDF_MARKERS[key] in objects, key


# ------------------------------------------------------- the highest-severity PDF vector
_RESIDUE = "RTINCREMENTNOVAK"


def _redact_marker(doc: fitz.Document) -> None:
    for page in doc:
        for rect in page.search_for(_RESIDUE):
            page.add_redact_annot(rect, fill=(0, 0, 0))
        page.apply_redactions()
    doc.set_metadata({})


def _make_residue_source(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 100), f"Predavajuci: {_RESIDUE}", fontsize=11)
    doc.set_metadata({"author": _RESIDUE})
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()
    return path


def test_incremental_save_leaves_the_prior_revision_recoverable(tmp_path):
    """HIGHEST SEVERITY. An incremental save appends a revision and keeps the previous one's
    objects verbatim. Every typed PyMuPDF API then reports the text as gone — ``get_text()``,
    ``metadata``, everything — while it is still sitting in the file for anyone who opens it
    in a hex editor or reverts the revision. The extractor must see it."""
    src = _make_residue_source(tmp_path / "src.pdf")
    out = tmp_path / "incremental.pdf"
    out.write_bytes(src.read_bytes())
    doc = fitz.open(str(out))
    _redact_marker(doc)
    doc.save(str(out), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()

    assert _RESIDUE.encode() in out.read_bytes(), "fixture is wrong: no residue in the bytes"
    legacy = _legacy_pdf_surfaces(out)
    assert not [s for s, t in legacy.items() if _RESIDUE in t], (
        "RED: the legacy extractor reported this file clean"
    )
    res = extract(out)
    assert _RESIDUE in res.by_surface[S_RAW_BYTES]


def test_writer_save_flags_really_rewrite_the_file(tmp_path):
    """``writer/pdf_body.py`` saves with ``garbage=4, deflate=True``. That flag is load-bearing
    and is PROVED here rather than trusted: the same redaction saved without it leaves the
    pre-redaction bytes in the output, and with it does not."""
    src = _make_residue_source(tmp_path / "src.pdf")

    full = tmp_path / "full.pdf"
    doc = fitz.open(str(src))
    _redact_marker(doc)
    doc.save(str(full), garbage=4, deflate=True)       # the writer's own flags
    doc.close()
    assert _RESIDUE not in extract(full).full_text
    assert _RESIDUE.encode() not in full.read_bytes()

    # The control arm: the same file re-saved with no garbage collection keeps the residue,
    # which is what makes the assertion above evidence instead of a tautology.
    incremental = tmp_path / "incremental.pdf"
    incremental.write_bytes(src.read_bytes())
    doc = fitz.open(str(incremental))
    _redact_marker(doc)
    doc.save(str(incremental), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()
    plain = tmp_path / "plain.pdf"
    doc = fitz.open(str(incremental))
    doc.save(str(plain))
    doc.close()
    assert _RESIDUE.encode() in plain.read_bytes()
    assert _RESIDUE in extract(plain).by_surface[S_RAW_BYTES]


def test_raw_bytes_backstop_reads_a_deflate_compressed_stream(tmp_path):
    """The backstop must inflate, not only scan literal bytes."""
    marker = "RTSTREAMNOVAK"
    payload = zlib.compress(f"BT (Kupujuci {marker}) Tj ET".encode())
    body = (
        b"%PDF-1.7\n1 0 obj\n<< /Length " + str(len(payload)).encode()
        + b" /Filter /FlateDecode >>\nstream\n" + payload
        + b"\nendstream\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
    )
    path = tmp_path / "compressed.pdf"
    path.write_bytes(body)
    assert marker.encode() not in body, "fixture is wrong: the marker must only exist compressed"
    assert marker in extract(path).by_surface[S_RAW_BYTES]


# ------------------------------------------------------------------- backward compatibility
def test_existing_surface_keys_are_unchanged(docx_file, pdf_file):
    """``eval/leak.py``, ``eval/metrics.py``, ``eval/retention.py`` and ``eval/run.py`` read
    these keys. New ones may be ADDED; none of these may move."""
    docx_keys = set(extract(docx_file).by_surface)
    pdf_keys = set(extract(pdf_file).by_surface)
    assert {S_DOCUMENT, S_HEADER, S_FOOTER, S_FOOTNOTES, S_ENDNOTES, S_COMMENTS,
            S_CORE, S_APP, S_CUSTOM} <= docx_keys
    assert {S_TEXT_LAYER, S_ANNOTATIONS, S_FORM_FIELDS, S_ATTACHMENTS,
            S_INFO, S_XMP} <= pdf_keys


def test_surface_for_gt_part_still_maps_every_corpus_part():
    for part, surface in (
        ("body", S_DOCUMENT), ("table_cell", S_DOCUMENT), ("textbox", S_DOCUMENT),
        ("tracked_change_ins", S_DOCUMENT), ("tracked_change_del", S_DOCUMENT),
        ("header", S_HEADER), ("footer", S_FOOTER), ("footnote", S_FOOTNOTES),
        ("endnote", S_ENDNOTES), ("comment", S_COMMENTS),
        ("metadata_core", S_CORE), ("metadata_app", S_APP),
    ):
        assert surface_for_gt_part("docx", part) == surface
    for part, surface in (
        ("body", S_TEXT_LAYER), ("annotation", S_ANNOTATIONS), ("form_field", S_FORM_FIELDS),
        ("attachment", S_ATTACHMENTS), ("metadata", S_INFO), ("xmp", S_XMP),
    ):
        assert surface_for_gt_part("pdf", part) == surface
    with pytest.raises(KeyError):
        surface_for_gt_part("docx", "no_such_part")


# ------------------------------------------------------------------- attributability rule
# The deep surfaces are not text, and a short needle collides in them by chance. The rule
# that decides whether an opaque-surface match means anything lives in eval/leak_gate.py and
# was set from a measurement (see the table in that module and redteam/FINDINGS.md). These
# tests pin both what it catches and — just as importantly — what it cannot.
_PANOSE_CONTEXT = (
    "\nfixed\n00000001\n08070000\n00000010\n00000000\n00020000\n00000000\n"
    "Courier\n02000500000000000000\n00\nauto\nvariable\n"
)


def test_structural_hex_blob_is_not_attributable():
    """Verbatim context from ``zmluva_v11_006.docx``: the bank code ``0200`` occurs three
    times in the font tables, every time inside a longer hex run. The body was redacted
    correctly; these are noise."""
    from eval.leak_gate import is_attributable

    assert "0200" in _PANOSE_CONTEXT
    assert not is_attributable(_PANOSE_CONTEXT, "0200")


def test_delimiting_alone_is_not_enough():
    """A four-digit needle standing on its own is still not attributable: measured, a
    delimited 4-digit string occurs by chance in the raw bytes of 18% of PDFs."""
    from eval.leak_gate import is_attributable

    assert not is_attributable("Kod banky: 0200 dalej", "0200")


def test_length_alone_is_not_enough():
    """An eight-digit needle embedded in a longer hex run is structure, not a value."""
    from eval.leak_gate import is_attributable

    assert not is_attributable("cafe8183762432ab", "81837624")


def test_long_delimited_needle_is_attributable():
    """Both halves satisfied — this is what a real value looks like on an opaque surface."""
    from eval.leak_gate import is_attributable

    assert is_attributable("\nICO\n81837624\nDIC\n", "81837624")
    assert is_attributable("/Klient (Jan Novak)", "Jan Novak")


def test_text_surfaces_are_never_subject_to_the_rule():
    """A four-character needle in the document body is a leak, full stop."""
    from eval.leak import Leak
    from eval.leak_gate import split_found_in

    leak = Leak(surface="0200", type="KOD_BANKY", found_in=(S_DOCUMENT,), gt_parts=("body",))
    counted, set_aside = split_found_in(leak, {S_DOCUMENT: "cislo uctu 0200 ..."})
    assert counted == (S_DOCUMENT,)
    assert set_aside == ()


def test_opaque_only_match_of_a_short_needle_is_set_aside_not_dropped():
    from eval.leak import Leak
    from eval.leak_gate import split_found_in

    leak = Leak(surface="0200", type="KOD_BANKY", found_in=(S_XML_ATTRS,), gt_parts=("body",))
    counted, set_aside = split_found_in(leak, {S_XML_ATTRS: _PANOSE_CONTEXT})
    assert counted == ()
    assert set_aside == (S_XML_ATTRS,), "it must be REPORTED as set aside, never silently gone"


def test_a_real_leak_on_an_opaque_surface_still_fails_the_gate():
    from eval.leak import Leak
    from eval.leak_gate import split_found_in

    leak = Leak(surface="Jan Novak", type="MENO", found_in=(S_RAW_BYTES,), gt_parts=("body",))
    counted, set_aside = split_found_in(leak, {S_RAW_BYTES: "\nPredavajuci Jan Novak\n"})
    assert counted == (S_RAW_BYTES,)
    assert set_aside == ()


def test_blind_spot_a_short_needle_hiding_only_in_incremental_residue_is_missed(tmp_path):
    """DOCUMENTED BLIND SPOT, constructed rather than argued.

    A real four-digit bank code left behind in a PDF's previous revision DOES reach
    ``raw_bytes`` — the extractor sees it — and the attributability rule then sets it aside,
    because a four-digit needle cannot be told from the chance noise of that surface. The
    gate PRINTS it, so it is visible, but it does not fail on it. The only reason this is
    tolerable is that such a code is also emitted to a text surface in every realistic
    document, and text surfaces are strict. If a document ever carries a short identifier in
    NO text surface at all, this gate cannot catch its residue. See redteam/FINDINGS.md.
    """
    from eval.leak import Leak
    from eval.leak_gate import split_found_in

    code = "0200"
    src = tmp_path / "src.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 100), f"Kod banky: {code}", fontsize=11)
    doc.save(str(src), garbage=4, deflate=True)
    doc.close()

    out = tmp_path / "incremental.pdf"
    out.write_bytes(src.read_bytes())
    doc = fitz.open(str(out))
    for pg in doc:
        for rect in pg.search_for(code):
            pg.add_redact_annot(rect, fill=(0, 0, 0))
        pg.apply_redactions()
    doc.save(str(out), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()

    res = extract(out)
    assert code in res.by_surface[S_RAW_BYTES], "the extractor DOES see the residue"
    assert code not in res.by_surface[S_TEXT_LAYER], "and the current revision is clean"

    leak = Leak(surface=code, type="KOD_BANKY", found_in=(S_RAW_BYTES,), gt_parts=("body",))
    counted, set_aside = split_found_in(leak, res.by_surface)
    assert counted == (), "this is the blind spot: a real leak the rule cannot attribute"
    assert set_aside == (S_RAW_BYTES,), "it must still be reported as set aside"


def test_run_text_still_reconstructs_across_split_runs(tmp_path):
    """context.md §10: run text is concatenated with NO separator. The attribute sweep must
    not have introduced one — that would hide the classic split-run leak."""
    markers = dict(DOCX_MARKERS)
    path = tmp_path / "split.docx"
    build_docx(path, markers)
    data = {n: zipfile.ZipFile(path).read(n) for n in zipfile.ZipFile(path).namelist()}
    split = (
        b'<w:p><w:r><w:t>Jan</w:t></w:r><w:r><w:t xml:space="preserve"> No</w:t></w:r>'
        b"<w:r><w:t>vak</w:t></w:r></w:p>"
    )
    data["word/document.xml"] = data["word/document.xml"].replace(b"</w:body>", split + b"</w:body>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in data.items():
            z.writestr(name, blob)
    assert "Jan Novak" in extract(path).by_surface[S_DOCUMENT]
