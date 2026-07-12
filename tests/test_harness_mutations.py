"""Mutation tests (context.md rejection, defect 3) — proving the harness can actually FAIL.

Passing on a working extractor proves nothing about whether the harness would catch a
*broken* one. Each test below breaks one specific thing the harness depends on and asserts,
programmatically, that the break is caught: either the extractor's own correctness check
(the same shape of assertion ``tests/test_extract.py`` runs) goes red, or a specific §8.3
gate (retention / coverage) fires, or per-type recall isolates a regression that an averaged
figure would hide.

The headers/footers mutation was verified by hand first (context.md rejection): a blind
extractor that never reads headers/footers makes a no-op (null) redactor look like it
achieved perfect recall on any PII type that lives only in a header or footer — the report
says 100%% recall while the redactor did nothing. That is codified here as one of six.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import pytest
from lxml import etree

from corpus.generate import generate
from eval.baselines import empty_output_redactor, null_redactor, refuse_all_redactor
from eval.extract import S_FOOTER, S_HEADER, S_INFO, S_XMP, ExtractResult, extract
from eval.leak import find_leaks
from eval.metrics import evaluate
from eval.run import run_eval

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    generate(n=10, out=out, seed=23, formats=["docx", "pdf"])
    return out


def _gts(corpus: Path, suffix: str | None = None):
    for gt_path in sorted(corpus.glob("*.gt.json")):
        gt = json.loads(gt_path.read_text("utf-8"))
        if not gt["text_layer"]:
            continue
        if suffix and not gt["source_file"].endswith(suffix):
            continue
        yield gt


def _assert_all_surfaces_found(corpus: Path, extract_fn, *, suffix: str | None = None) -> int:
    """The same correctness check ``tests/test_extract.py`` runs against the real extractor:
    every ground-truth surface must be present in what the extractor pulled out. Returns the
    number of surfaces checked so callers can assert the mutation actually had something to
    bite on (a vacuous loop would let ``pytest.raises`` fail silently for the wrong reason)."""
    checked = 0
    for gt in _gts(corpus, suffix):
        res = extract_fn(corpus / gt["source_file"])
        for pii in gt["pii"]:
            assert pii["surface"] in res.full_text, (
                f"{gt['source_file']}: {pii['surface']!r} "
                f"(part {pii['location']['surface_part']!r}) invisible to this extractor"
            )
            checked += 1
    return checked


# --------------------------------------------------------------- mutation 1: headers/footers
def _blind_headers_footers(path: Path) -> ExtractResult:
    by_surface = dict(extract(path).by_surface)
    by_surface[S_HEADER] = ""
    by_surface[S_FOOTER] = ""
    return ExtractResult(full_text="\n".join(by_surface.values()), by_surface=by_surface)


def test_mutation_headers_footers_removed_drives_extractor_grader_red(corpus):
    with pytest.raises(AssertionError):
        _assert_all_surfaces_found(corpus, _blind_headers_footers, suffix=".docx")


def test_mutation_headers_footers_removed_falsely_reports_perfect_recall_on_noop(corpus):
    # The exact bug found by hand: a blind extractor turns a do-nothing (null) redactor into
    # an apparently perfect one for any type confined to headers/footers.
    graded, originals, header_footer_types = [], [], set()
    for gt in _gts(corpus, suffix=".docx"):
        types_here = {
            p["type"] for p in gt["pii"]
            if p["auto_redact"] and p["location"]["surface_part"] in ("header", "footer")
        }
        if not types_here:
            continue
        header_footer_types |= types_here
        blind = _blind_headers_footers(corpus / gt["source_file"])  # "output" == the unredacted file
        graded.append((gt, blind))
        originals.append(blind)
    assert header_footer_types, "corpus needs auto-redact PII confined to header/footer"

    m = evaluate(graded, originals=originals)
    for ptype in header_footer_types:
        assert m.per_type[ptype].recall == 1.0, (
            f"reproduces the bug: {ptype} must falsely show perfect recall under a blind "
            "extractor even though the redactor did nothing"
        )
    # And the real, non-blind extractor must NOT be fooled — leaks are visible.
    for gt in _gts(corpus, suffix=".docx"):
        real = extract(corpus / gt["source_file"])
        leaked = {lk.type for lk in find_leaks(gt, real)}
        if header_footer_types & {p["type"] for p in gt["pii"] if p["auto_redact"]
                                   and p["location"]["surface_part"] in ("header", "footer")}:
            assert leaked & header_footer_types, "the real extractor must catch what the blind one hides"


# --------------------------------------------------------------- mutation 2: PDF metadata/XMP
def _blind_pdf_metadata(path: Path) -> ExtractResult:
    by_surface = dict(extract(path).by_surface)
    by_surface[S_INFO] = ""
    by_surface[S_XMP] = ""
    return ExtractResult(full_text="\n".join(by_surface.values()), by_surface=by_surface)


def test_mutation_pdf_metadata_removed_drives_extractor_grader_red(corpus):
    checked = 0
    with pytest.raises(AssertionError):
        checked = _assert_all_surfaces_found(corpus, _blind_pdf_metadata, suffix=".pdf")
    # sanity: prove this isn't a vacuous pass by confirming the real extractor DOES find these
    # same surfaces (i.e. the corpus really does seed metadata/XMP PII for PDFs).
    real_checked = _assert_all_surfaces_found(corpus, extract, suffix=".pdf")
    assert real_checked > 0


# --------------------------------------------------------------- mutation 3: tracked changes
def _blind_tracked_changes_docx(path: Path) -> ExtractResult:
    """Re-implements DOCX body extraction but strips <w:ins>/<w:del> before reading text —
    simulating an extractor that never learned tracked changes persist deleted text in the XML."""
    import zipfile

    with zipfile.ZipFile(path) as z:
        root = etree.fromstring(z.read("word/document.xml"))
    for tag in ("ins", "del"):
        for el in list(root.iter(_W + tag)):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
    by_surface = dict(extract(path).by_surface)
    by_surface["document_xml"] = "".join(root.itertext())
    return ExtractResult(full_text="\n".join(by_surface.values()), by_surface=by_surface)


def test_mutation_tracked_changes_removed_drives_extractor_grader_red(corpus):
    with pytest.raises(AssertionError):
        _assert_all_surfaces_found(corpus, _blind_tracked_changes_docx, suffix=".docx")


def test_mutation_tracked_changes_removed_hides_specific_leaks(corpus):
    # Per-surface, not per-type: the same PII type (e.g. MENO) usually also occurs elsewhere
    # in the body, so a type-level recall average would be diluted and miss the point. The
    # actual danger is that a SPECIFIC surface confined to w:ins/w:del becomes invisible.
    hidden = []
    for gt in _gts(corpus, suffix=".docx"):
        real = extract(corpus / gt["source_file"])
        blind = _blind_tracked_changes_docx(corpus / gt["source_file"])
        for pii in gt["pii"]:
            if not pii["auto_redact"]:
                continue
            if pii["location"]["surface_part"] not in ("tracked_change_ins", "tracked_change_del"):
                continue
            surface = pii["surface"]
            assert surface in real.full_text, "sanity: the real extractor must see it"
            if surface not in blind.full_text:
                hidden.append((gt["source_file"], surface))
    assert hidden, (
        "expected the blind extractor to hide at least one tracked-change-only surface — "
        "on a no-op redactor that means a false 'removed' on a leak that is actually still there"
    )


# --------------------------------------------------------------- mutation 4: skip one type
def _almost_perfect_redact(gt: dict, original: ExtractResult, skip_type: str) -> ExtractResult:
    """Replace every auto-redact surface EXCEPT one type's — simulating a near-complete
    redactor with exactly one blind spot. Plain substring replace (not word-boundary-safe):
    DOCX paragraph/run text is reconstructed with NO separator (context.md §10), so a surface
    can be glued directly to adjacent content with no whitespace — a boundary-anchored regex
    would then fail to match a genuine occurrence. This is a test scaffold, not a scoring
    function, so over-matching a short surface elsewhere is an acceptable trade for that."""
    surfaces = {p["surface"] for p in gt["pii"] if p["auto_redact"] and p["type"] != skip_type}
    text = original.full_text
    for s in sorted(surfaces, key=len, reverse=True):
        text = text.replace(s, "[REDACTED]")
    return ExtractResult(full_text=text, by_surface={"body": text})


def test_mutation_all_redacted_skip_one_type_shows_in_per_type_not_averaged(corpus):
    target_gt, skip_type = None, None
    for gt in _gts(corpus):
        auto_types = {p["type"] for p in gt["pii"] if p["auto_redact"]}
        if len(auto_types) >= 3:
            target_gt, skip_type = gt, sorted(auto_types)[0]
            break
    assert target_gt is not None, "need a doc with >=3 auto-redact types to prove isolation"

    original = extract(corpus / target_gt["source_file"])
    almost = _almost_perfect_redact(target_gt, original, skip_type)

    leaks = find_leaks(target_gt, almost)
    leaked_types = {lk.type for lk in leaks}
    assert leaked_types == {skip_type}, f"expected only {skip_type!r} to leak, got {leaked_types}"
    assert leaks, "a fully-skipped type must register as a leak -> the run must go red"

    m = evaluate([(target_gt, almost)])
    assert m.per_type[skip_type].recall == 0.0
    other_auto_types = {p["type"] for p in target_gt["pii"] if p["auto_redact"]} - {skip_type}
    assert other_auto_types, "need other auto-redact types present to prove they're unaffected"
    for t in other_auto_types:
        assert m.per_type[t].recall == 1.0, (
            f"{t}: an unrelated type's recall must stay perfect — the regression must show up "
            "ONLY in the skipped type's own row, never smeared into an average"
        )


# --------------------------------------------------------------- mutation 5: EMPTY_OUTPUT
def test_mutation_empty_output_drives_retention_gate_red(corpus, tmp_path):
    out = tmp_path / "empty"
    out.mkdir()
    for gt in _gts(corpus):
        if gt["must_be_refused"]:
            continue
        empty_output_redactor(corpus / gt["source_file"], out / gt["source_file"])
    outcome = run_eval(corpus, out)
    assert outcome.leaks == [], "an empty file has nothing left to leak"
    assert not outcome.retention_ok, "an empty file must fail retention, not read as success"
    assert not outcome.passed


# --------------------------------------------------------------- mutation 6: REFUSE_ALL
def test_mutation_refuse_all_drives_coverage_gate_red(corpus, tmp_path):
    out = tmp_path / "refuse"
    out.mkdir()
    for gt in _gts(corpus):
        if gt["must_be_refused"]:
            continue
        refuse_all_redactor(corpus / gt["source_file"], out / gt["source_file"])
    outcome = run_eval(corpus, out)
    assert outcome.leaks == [], "nothing was produced, so nothing can leak"
    assert not outcome.coverage_ok, "refusing every input must fail coverage, not read as success"
    assert not outcome.passed


# --------------------------------------------------------------- mutation 7: word-boundary fix
# (context.md rejection round 6) proves the leak.py/metrics.py word-boundary fix cannot hide a
# real leak. Runs against the REAL data/synthetic corpus on disk (seed 42), not a throwaway
# fixture, because that is the exact corpus the user measured 3633 leaks against by hand.
def test_mutation_word_boundary_fix_does_not_drop_real_leaks():
    real_corpus = Path("data/synthetic")
    if not real_corpus.is_dir():
        pytest.skip("data/synthetic not present — regenerate with corpus.generate first")

    # Matches eval.leak.find_leaks' own dedup key exactly: unique (surface, type) pairs per
    # document — NOT unique surface strings alone (the same surface can legitimately appear
    # under two different auto_redact types).
    expected_surfaces = 0
    for gt_path in real_corpus.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        if gt["must_be_refused"]:
            continue
        expected_surfaces += len({
            (p["surface"], p["type"]) for p in gt["pii"] if p["auto_redact"]
        })

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for gt_path in real_corpus.glob("*.gt.json"):
            gt = json.loads(gt_path.read_text("utf-8"))
            if gt["must_be_refused"]:
                continue
            null_redactor(real_corpus / gt["source_file"], out / gt["source_file"])
        outcome = run_eval(real_corpus, out)

    assert len(outcome.leaks) == expected_surfaces, (
        f"word-boundary leak matching dropped real leaks: expected "
        f"{expected_surfaces} (every auto_redact surface, computed fresh from ground truth), "
        f"got {len(outcome.leaks)}. STOP — this means the fix hid a genuine leak, do not "
        f"proceed until this is understood."
    )
    # Floor tied to the exact count the user measured by hand before this fix (context.md
    # rejection round 6) — a regenerated corpus can shift slightly, but not collapse.
    assert len(outcome.leaks) >= 3000, (
        f"leak count {len(outcome.leaks)} is far below the ~3633 baseline measured before "
        f"the word-boundary fix — STOP and report why, do not adjust the metric."
    )
