"""The extractor's own grader (context.md §8, step 1).

Run the extractor over the UNREDACTED corpus and assert EVERY ground-truth surface is
found — reporting which physical surface each was found in. If the extractor cannot find
PII in a file that is 100%% unredacted, it cannot be trusted to find a leak, and the whole
leak test is a false green. So this test is built first and is the extractor's grader.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from corpus.generate import generate
from eval.extract import extract, surface_for_gt_part


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    generate(n=6, out=out, seed=7, formats=["docx", "pdf"])
    return out


def _gts(corpus: Path):
    for gt_path in corpus.glob("*.gt.json"):
        yield gt_path, json.loads(gt_path.read_text("utf-8"))


def test_every_ground_truth_surface_is_found_and_located(corpus):
    """Every recorded PII surface must be extractable from the physical surface its ground
    truth names. The assertion reports which surface each was found in."""
    checked = 0
    for _, gt in _gts(corpus):
        if not gt["text_layer"]:
            continue  # image-only fixture: no text layer by design
        src = corpus / gt["source_file"]
        fmt = "docx" if src.suffix == ".docx" else "pdf"
        res = extract(src)
        for pii in gt["pii"]:
            part = pii["location"]["surface_part"]
            surface = surface_for_gt_part(fmt, part)
            assert surface in res.by_surface, f"{src.name}: extractor has no surface {surface!r}"
            assert pii["surface"] in res.by_surface[surface], (
                f"{src.name}: {pii['surface']!r} (gt part {part!r}) not found in "
                f"extracted surface {surface!r}"
            )
            # full_text is the union of all surfaces, so it must contain it too.
            assert pii["surface"] in res.full_text
            checked += 1
    assert checked > 200, "the corpus should seed a lot of PII; found too little"


def test_every_auto_redact_surface_is_found(corpus):
    """Headline guarantee: nothing that must be redacted is invisible to the extractor."""
    misses = []
    for _, gt in _gts(corpus):
        if not gt["text_layer"]:
            continue
        res = extract(corpus / gt["source_file"])
        for pii in gt["pii"]:
            if pii["auto_redact"] and pii["surface"] not in res.full_text:
                misses.append((gt["source_file"], pii["surface"]))
    assert not misses, f"auto-redact surfaces invisible to extractor: {misses[:10]}"


def test_extraction_succeeds_on_every_output(corpus):
    """Formatting integrity (§8.2): every corpus file opens and extracts without error."""
    for _, gt in _gts(corpus):
        res = extract(corpus / gt["source_file"])
        assert isinstance(res.full_text, str)
