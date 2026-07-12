"""§8.1 leak test — the killer test (context.md §8).

Against the UNREDACTED corpus (equivalent to a no-op redactor), every auto_redact surface
must be reported as a leak, and should_flag / decoy surfaces must NOT be — they may
legitimately remain. This is the exact bug class §8.1 targets: text still extractable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from corpus.generate import generate
from eval.extract import extract
from eval.leak import find_leaks


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("corpus")
    generate(n=6, out=out, seed=11, formats=["docx", "pdf"])
    return out


def _text_docs(corpus: Path):
    for gt_path in corpus.glob("*.gt.json"):
        gt = json.loads(gt_path.read_text("utf-8"))
        if gt["text_layer"]:
            yield gt


def test_unredacted_corpus_leaks_every_auto_surface(corpus):
    for gt in _text_docs(corpus):
        res = extract(corpus / gt["source_file"])
        leaks = find_leaks(gt, res)
        leaked = {lk.surface for lk in leaks}
        expected = {p["surface"] for p in gt["pii"] if p["auto_redact"]}
        assert expected, f"{gt['source_file']}: corpus doc has no auto-redact PII?"
        assert expected <= leaked, (
            f"{gt['source_file']}: auto surfaces not reported as leaks: {expected - leaked}"
        )


def test_should_flag_and_decoy_are_never_reported_as_leaks(corpus):
    for gt in _text_docs(corpus):
        res = extract(corpus / gt["source_file"])
        leaked = {lk.surface for lk in find_leaks(gt, res)}
        auto = {p["surface"] for p in gt["pii"] if p["auto_redact"]}
        non_leak = {
            p["surface"] for p in gt["pii"] if not p["auto_redact"]
        } - auto  # a string that is also auto elsewhere is still a real leak
        assert not (leaked & non_leak), (
            f"{gt['source_file']}: non-leak surfaces reported: {leaked & non_leak}"
        )


def test_each_leak_names_a_physical_surface(corpus):
    for gt in _text_docs(corpus):
        res = extract(corpus / gt["source_file"])
        for lk in find_leaks(gt, res):
            assert lk.found_in, f"{lk.surface!r} leak names no surface"
            assert set(lk.found_in) <= set(res.by_surface), lk.found_in
