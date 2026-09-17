"""The .docx and .pdf of one index are ONE document in two formats (QUESTIONS.md Q14).

Before the content-plan refactor, ``corpus/generate.py::_emit`` ran each template once PER
FORMAT with a per-format seed, so ``kupna_zmluva_000.docx`` and ``kupna_zmluva_000.pdf`` were
two unrelated documents (measured: 46 vs 40 ground-truth surfaces, 3 in common, and those
three coincidental). Every cross-format claim made against such a pair was meaningless.

This test pins the property that made the claim meaningful again: the only ground-truth
surface that may appear in one format and not the other is one whose every occurrence lives
in a ``surface_part`` the other format has no equivalent for.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from corpus.generate import generate
from tools.paired_gt_report import compare


@pytest.fixture(scope="module")
def paired_corpus(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("paired")
    generate(n=7, out=out, seed=11, formats=["docx", "pdf"])
    return out


def test_every_one_sided_surface_is_a_format_specific_surface(paired_corpus: Path) -> None:
    rows, unexplained = compare(paired_corpus)
    assert rows, "no docx/pdf ground-truth pairs were generated"
    assert unexplained == 0, "\n".join(
        f"{r['stem']}: {s!r} {occ} (only in {side})"
        for r in rows for s, occ, side in r["unexplained"]
    )


def test_the_pair_shares_the_overwhelming_majority_of_its_surfaces(paired_corpus: Path) -> None:
    """A guard against a future change that makes the pair 'explainable' by emptying it.

    Zero unexplained surfaces is also what you get if both formats stop sharing anything and
    every surface lands in a format-specific part. Requiring most surfaces to be COMMON is
    what actually says 'same document': the old corpus scored 3/46 here.
    """
    rows, _ = compare(paired_corpus)
    for r in rows:
        assert r["n_common"] >= 0.8 * max(r["n_docx"], r["n_pdf"]), (
            f"{r['stem']}: only {r['n_common']} of {r['n_docx']}/{r['n_pdf']} surfaces are "
            "shared — the two formats have drifted apart again"
        )


def test_the_two_formats_carry_the_same_entity_table(paired_corpus: Path) -> None:
    import json

    for docx_gt in sorted(paired_corpus.glob("*.docx.gt.json")):
        pdf_gt = paired_corpus / docx_gt.name.replace(".docx.", ".pdf.")
        if not pdf_gt.exists():
            continue
        d = json.loads(docx_gt.read_text(encoding="utf-8"))["entities"]
        p = json.loads(pdf_gt.read_text(encoding="utf-8"))["entities"]
        assert d == p, f"{docx_gt.name}: entity tables differ between the two formats"
