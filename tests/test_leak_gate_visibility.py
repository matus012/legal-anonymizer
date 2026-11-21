"""Can the leak gate SEE the PII it is supposed to be looking for?

THE PREMISE NOTHING WAS CHECKING
--------------------------------------------------------------------------------------
``eval/leak_gate.py`` is the project's one non-negotiable gate: zero leaks. It works by
taking every ``auto_redact`` ground-truth surface and grepping the redacted output for it
with an EXACT substring search (``eval/leak.py:surface_present``).

That rests on an assumption nobody had tested: **that the needle and the haystack spell the
string the same way.** They need not. A PDF text layer does not reproduce the bytes the
generator wrote — PyMuPDF renders the hyphen in an account number as U+00AD SOFT HYPHEN, and
in some documents renders every space as U+00A0. A ground-truth surface holding ``-`` and
``" "`` then cannot match the text however badly the document leaks.

If that happened, the gate would not report an error. It would report **zero leaks** — for those
surfaces, forever, whether or not they were ever redacted. A gate that is structurally
incapable of failing is worse than no gate, because it is believed.

It is currently FINE: ``eval/extract.py`` normalises the soft hyphen when it builds the text
layer, and measured over the whole corpus all 6450 auto_redact surfaces are visible. This
file exists so that stays true. The way it would break is not a code change to the gate — it
is someone adding a PII type whose surface the extractor happens to spell differently, and
that person would see every gate stay green.

WHY THE ASSERTION IS ON THE *UNREDACTED* ORIGINAL
--------------------------------------------------------------------------------------
Running it against a redacted output would prove nothing: a surface absent because it was
correctly removed and a surface absent because the gate cannot see it look identical. The
original still contains every surface by construction, so anything not findable there is a
BLIND SPOT and nothing else.

This is the discovery route that found it, too. A leak check written for ``tools/make_demo.py``
passed while being structurally unable to match any multi-word needle in a PDF; it was caught
by feeding it a string known to be present and seeing whether it noticed. That is the same
trick, applied to the real gate.
"""
import glob
import json
import os

import pytest

from eval.extract import extract
from eval.leak import surface_present

CORPUS = os.path.join("data", "synthetic")
# Spelled as an escape, never as the character itself. A literal U+00AD in source is
# invisible in every editor and diff -- which is the entire class of bug this file is about,
# and the project handoff notes warn about it specifically.
SOFT_HYPHEN = chr(0x00AD)


def _corpus_files() -> list[str]:
    return sorted(glob.glob(os.path.join(CORPUS, "*.docx"))) + sorted(
        glob.glob(os.path.join(CORPUS, "*.pdf"))
    )


def _gt_for(path: str) -> dict | None:
    gt_path = f"{path}.gt.json"
    if not os.path.exists(gt_path):
        return None
    with open(gt_path, encoding="utf-8") as fh:
        return json.load(fh)


def test_every_auto_redact_surface_is_visible_to_the_leak_gate():
    """Every auto_redact ground-truth surface must be findable, by the gate's own mechanism,
    in its own UNREDACTED source file. A surface that fails here is one the leak gate can
    never report — it would be silently exempt from the zero-leak requirement."""
    files = _corpus_files()
    if not files:
        pytest.skip("corpus not generated; see status.txt for the regenerate command")

    invisible: list[tuple[str, str, str]] = []
    checked = 0
    for path in files:
        gt = _gt_for(path)
        if gt is None or gt.get("must_be_refused"):
            continue
        text = extract(path).full_text
        for row in gt["pii"]:
            if not row["auto_redact"]:
                continue
            checked += 1
            if not surface_present(text, row["surface"]):
                invisible.append((os.path.basename(path), row["type"], row["surface"]))

    assert checked, "no auto_redact surfaces were checked — the audit itself is broken"
    assert not invisible, (
        f"{len(invisible)} of {checked} auto_redact surfaces are INVISIBLE to the leak gate "
        f"in their own unredacted source. Each one is silently exempt from the zero-leak "
        f"requirement. First ten: {invisible[:10]}"
    )


def test_the_audit_can_actually_fail():
    """The control. An audit nobody has seen fail is not known to work — which is the exact
    defect this whole file is about, so it would be absurd not to check it here."""
    files = _corpus_files()
    if not files:
        pytest.skip("corpus not generated")
    text = extract(files[0]).full_text
    assert not surface_present(text, "ZZZ-THIS-STRING-IS-NOT-IN-ANY-DOCUMENT-ZZZ")


def test_a_soft_hyphen_in_the_haystack_is_normalised_by_the_extractor():
    """The concrete case that motivated this file, pinned so a future extractor refactor
    cannot drop the normalisation without a test going red.

    PyMuPDF renders the hyphen of a legacy account number as U+00AD. Ground truth records
    U+002D. Without ``eval/extract.py``'s replace, every BANKOVY_UCET in every PDF would be
    invisible to the leak gate — measured: 70 of them, plus 36 spisové značky."""
    pdfs = sorted(glob.glob(os.path.join(CORPUS, "*.pdf")))
    if not pdfs:
        pytest.skip("corpus not generated")

    import fitz

    for path in pdfs:
        gt = _gt_for(path)
        if gt is None or gt.get("must_be_refused"):
            continue
        with fitz.open(path) as doc:
            raw = "\n".join(page.get_text("text") for page in doc)
        if SOFT_HYPHEN not in raw:
            continue
        # This document DOES render a soft hyphen. Every surface must still be visible.
        text = extract(path).full_text
        hyphenated = [r for r in gt["pii"] if r["auto_redact"] and "-" in r["surface"]]
        missing = [r["surface"] for r in hyphenated if not surface_present(text, r["surface"])]
        assert not missing, (
            f"{os.path.basename(path)} renders U+00AD and the extractor did not normalise it: "
            f"{missing[:5]}"
        )
        return
    pytest.skip("no corpus PDF renders a soft hyphen")
