"""Self-consistency test for the generator (context.md §7, inverse of the §8 leak test).

The one bug that would silently break every downstream step is ground truth that lies about
*where* a PII string lives. So for every recorded occurrence we extract text from exactly the
part its ground truth names and assert the surface is really there. For the image-only PDF we
assert the opposite: no extractable text layer. We also assert the corpus actually contains
all three decision classes and that the checksum flags match reality.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

import fitz
import pytest
from lxml import etree

from corpus.generate import generate
from corpus.pii import iban, ico, rodne_cislo

@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    generate(n=6, out=out, seed=7, formats=["docx", "pdf"])
    return out


# --------------------------------------------------------------------------- extraction
def _docx_parts(path: Path) -> dict:
    z = zipfile.ZipFile(path)

    def xml_text(name: str) -> str:
        # Concatenate run texts WITHOUT a separator so a name split across runs reconstructs
        # (context.md §10) — this is exactly what the detector must do. No normalization: the
        # DOCX stores characters (NBSP, hyphen) literally, so ground truth must match verbatim.
        return "".join(etree.fromstring(z.read(name)).itertext()) if name in z.namelist() else ""

    doc = xml_text("word/document.xml")
    header = "".join(xml_text(n) for n in z.namelist() if re.search(r"header\d*\.xml", n))
    footer = "".join(xml_text(n) for n in z.namelist() if re.search(r"footer\d*\.xml", n))
    buckets = {
        "body": doc, "table_cell": doc, "textbox": doc,
        "tracked_change_ins": doc, "tracked_change_del": doc,
        "header": header, "footer": footer,
        "footnote": xml_text("word/footnotes.xml"),
        "endnote": xml_text("word/endnotes.xml"),
        "comment": xml_text("word/comments.xml"),
        "metadata_core": z.read("docProps/core.xml").decode("utf-8"),
        "metadata_app": z.read("docProps/app.xml").decode("utf-8"),
    }
    z.close()
    return buckets


def _pdf_parts(path: Path) -> dict:
    # No normalization: ground truth already records the exact extractable form (the generator
    # writes faithful whitespace and mirrors PyMuPDF's hyphen remap). If a surface isn't found
    # verbatim, that is a real generator bug, not something to paper over.
    d = fitz.open(path)
    body = "\n".join(p.get_text() for p in d)
    annotation = " ".join((a.info.get("content") or "") for p in d for a in p.annots())
    form_field = " ".join((w.field_value or "") for p in d for w in p.widgets())
    attachment = " ".join(d.embfile_get(n).decode("utf-8") for n in d.embfile_names())
    metadata = " ".join(str(v) for v in (d.metadata or {}).values())
    xmp = d.get_xml_metadata()
    d.close()
    return {
        "body": body, "annotation": annotation, "form_field": form_field,
        "attachment": attachment, "metadata": metadata, "xmp": xmp,
    }


# --------------------------------------------------------------------------- tests
def test_generation_produced_all_types_and_formats(corpus):
    gts = list(corpus.glob("*.gt.json"))
    assert len(gts) == 6 * 2 + 1  # 6 docs × 2 formats + image-only fixture
    types = {json.loads(p.read_text("utf-8"))["doc_type"] for p in gts}
    assert len(types) == 6


def test_ground_truth_never_lies_about_location(corpus):
    checked = 0
    for gt_path in corpus.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        src = corpus / gt["source_file"]
        if not gt["text_layer"]:
            continue  # image-only handled separately
        parts = _docx_parts(src) if src.suffix == ".docx" else _pdf_parts(src)
        for pii in gt["pii"]:
            part = pii["location"]["surface_part"]
            assert part in parts, f"{src.name}: unknown part {part}"
            assert pii["surface"] in parts[part], (
                f"{src.name}: {pii['surface']!r} not found verbatim in part {part!r}"
            )
            checked += 1
    assert checked > 200  # the corpus really did seed a lot of PII


def test_image_only_pdf_has_no_text_layer(corpus):
    fixtures = [
        json.loads(p.read_text("utf-8"))
        for p in corpus.glob("*.gt.json")
        if not json.loads(p.read_text("utf-8"))["text_layer"]
    ]
    assert fixtures, "expected an image-only fixture"
    for gt in fixtures:
        assert gt["must_be_refused"] is True
        d = fitz.open(corpus / gt["source_file"])
        assert all(p.get_text().strip() == "" for p in d)
        d.close()


def test_all_three_decision_classes_present(corpus):
    auto, flag, decoy = 0, 0, 0
    for gt_path in corpus.glob("*.gt.json"):
        for pii in json.loads(gt_path.read_text("utf-8"))["pii"]:
            if pii["auto_redact"]:
                auto += 1
            elif pii["should_flag"]:
                flag += 1
            else:
                decoy += 1
    assert auto > 0 and flag > 0 and decoy > 0


def test_checksum_flags_match_reality(corpus):
    validators = {"RODNE_CISLO": rodne_cislo.is_valid, "ICO": ico.is_valid, "IBAN": iban.is_valid}
    seen_valid = seen_invalid = 0
    for gt_path in corpus.glob("*.gt.json"):
        for pii in json.loads(gt_path.read_text("utf-8"))["pii"]:
            if "valid_checksum" not in pii or pii["type"] not in validators:
                continue
            is_valid = validators[pii["type"]](pii["surface"])
            assert is_valid == pii["valid_checksum"], pii
            if pii["valid_checksum"]:
                assert pii["auto_redact"] and not pii["should_flag"]
                seen_valid += 1
            else:
                assert pii["should_flag"] and not pii["auto_redact"]
                seen_invalid += 1
    assert seen_valid > 0 and seen_invalid > 0


def test_entities_carry_inconsistent_variants(corpus):
    for gt_path in corpus.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        if not gt["entities"]:
            continue
        assert any(len(set(e["variants"])) >= 3 for e in gt["entities"])
