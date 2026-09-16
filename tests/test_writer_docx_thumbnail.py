"""v1.1 red-team finding B-2: docProps/thumbnail.* must not survive redaction.

Word writes a RENDERED PICTURE OF PAGE 1 into ``docProps/thumbnail.jpeg`` whenever "Save
Thumbnail" is on, and python-docx copies unknown package parts through byte-for-byte. So a
redacted output shipped a small image of the *un-redacted* first page — names, rodné číslo and
all — while every gate scored the document clean, because the leak test greps TEXT and a
thumbnail is pixels. No extractor can ever see it. It has to be deleted, not graded.

Fixtures are hand-built here (a real .docx has no thumbnail unless Word made it, so the test
injects one). ``corpus/`` is never imported.
"""
from __future__ import annotations

import zipfile

from docx import Document
from lxml import etree

from writer.docx_body import redact_docx_body

_RELS = "_rels/.rels"
_THUMB = "docProps/thumbnail.jpeg"
# Two-byte JPEG SOI marker plus a marker string: enough to be a distinct, findable part.
_THUMB_BYTES = b"\xff\xd8" + b"THUMBNAIL-PAGE-ONE-RENDER-NOVAK" + b"\xff\xd9"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _docx_with_thumbnail(path, body_text: str) -> None:
    """Write a .docx containing a thumbnail part plus its relationship, the way Word does."""
    doc = Document()
    doc.add_paragraph(body_text)
    doc.save(str(path))

    with zipfile.ZipFile(path) as zin:
        items = [(n, zin.read(n)) for n in zin.namelist()]

    out = []
    for name, data in items:
        if name.lower().startswith("docprops/thumbnail"):
            continue  # python-docx's template already ships one; replace, never duplicate
        if name == _RELS:
            root = etree.fromstring(data)
            rel = etree.SubElement(root, f"{{{_REL_NS}}}Relationship")
            rel.set("Id", "rIdThumb")
            rel.set(
                "Type",
                "http://schemas.openxmlformats.org/package/2006/"
                "relationships/metadata/thumbnail",
            )
            for existing in list(root):
                if (existing.get("Target") or "").lower().lstrip("/").startswith(
                    "docprops/thumbnail"
                ):
                    root.remove(existing)
            rel.set("Target", _THUMB)
            data = etree.tostring(root, encoding="UTF-8", standalone=True)
        out.append((name, data))
    out.append((_THUMB, _THUMB_BYTES))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in out:
            zout.writestr(name, data)


def _names(path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def test_fixture_really_carries_a_thumbnail(tmp_path):
    """Precondition. Without this the removal test could pass on a file that never had one."""
    src = tmp_path / "in.docx"
    _docx_with_thumbnail(src, "Zmluvu podpisal Novak.")
    assert _THUMB in _names(src)
    with zipfile.ZipFile(src) as z:
        assert b"NOVAK" in z.read(_THUMB)


def test_thumbnail_is_removed_from_the_redacted_output(tmp_path):
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    _docx_with_thumbnail(src, "Zmluvu podpisal Novak.")

    redact_docx_body(str(src), str(out), known_entities=["Novak"])

    assert _THUMB not in _names(out), "page-1 thumbnail survived redaction"
    assert not any(n.lower().startswith("docprops/thumbnail") for n in _names(out))


def test_thumbnail_bytes_are_gone_from_the_whole_package(tmp_path):
    """Belt and braces: the marker must not survive anywhere in the output, not merely under
    its own part name. A rewrite that renamed the part instead of dropping it would pass the
    test above and still ship the pixels."""
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    _docx_with_thumbnail(src, "Zmluvu podpisal Novak.")

    redact_docx_body(str(src), str(out), known_entities=["Novak"])

    assert b"THUMBNAIL-PAGE-ONE-RENDER" not in out.read_bytes()


def test_dangling_relationship_is_stripped_so_word_still_opens_the_file(tmp_path):
    """Removing the part but leaving its Relationship makes Word report the document corrupt —
    which would turn a privacy fix into a data-loss bug for a non-technical user."""
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    _docx_with_thumbnail(src, "Zmluvu podpisal Novak.")

    redact_docx_body(str(src), str(out), known_entities=["Novak"])

    with zipfile.ZipFile(out) as z:
        rels = z.read(_RELS).decode("utf-8")
    assert "thumbnail" not in rels.lower()


def test_output_still_opens_and_is_still_redacted(tmp_path):
    """Format integrity (context.md §8.2) plus the actual redaction — the ZIP rewrite must not
    have cost either."""
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    _docx_with_thumbnail(src, "Zmluvu podpisal Novak dna 1.1.2025.")

    redact_docx_body(str(src), str(out), known_entities=["Novak"])

    reopened = Document(str(out))
    text = "\n".join(p.text for p in reopened.paragraphs)
    assert "Novak" not in text
    assert "[MENO_1]" in text


def test_plain_document_loses_only_the_thumbnail_and_nothing_else(tmp_path):
    """A PLAIN document — no hand-injected thumbnail — still exercises this path, because
    python-docx's own default template ALREADY ships a docProps/thumbnail.jpeg. That is worth
    stating plainly: every document this tool has ever produced carried one, which is exactly
    why red-team finding B-2 rated it HIGH rather than theoretical.

    So the assertion is not "nothing changed" but the sharper one: the ONLY part that
    disappears is the thumbnail. The rewrite must not silently drop anything else it does not
    recognise."""
    src, out = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    doc.add_paragraph("Zmluvu podpisal Novak.")
    doc.save(str(src))

    assert any(n.lower().startswith("docprops/thumbnail") for n in _names(src)), (
        "premise of this test: python-docx's template ships a thumbnail"
    )

    redact_docx_body(str(src), str(out), known_entities=["Novak"])

    removed = set(_names(src)) - set(_names(out))
    assert all(n.lower().startswith("docprops/thumbnail") for n in removed), removed
    assert removed, "nothing was removed at all"

    # The output DOES gain word/header1.xml and word/footer1.xml, and that is pre-existing v1
    # behaviour rather than anything the thumbnail rewrite did: _redact_docx walks doc.sections
    # and touches section.header / section.footer, and python-docx MATERIALISES those parts on
    # first access. Asserted explicitly instead of loosened to "ignore additions", so that a
    # future rewrite which really did invent a part would still fail here.
    added = set(_names(out)) - set(_names(src))
    assert added <= {"word/header1.xml", "word/footer1.xml"}, added
