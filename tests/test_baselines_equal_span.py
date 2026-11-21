"""Equal-span / equal-rect suppression hole in greedy_redactor's helpers (mirrors the
eval/leak.py::surface_present round-8 fix).

greedy_redactor is a falsification instrument: it must fail the §8.3 flag gate and ONLY the
flag gate. A decoy may suppress a target occurrence ONLY when the decoy STRICTLY covers it —
strictly larger AND fully covering, exactly like ``surface_present``'s
``d0 <= start and end <= d1 and (d1 - d0) > target_len``. An EQUAL decoy suppresses nothing;
otherwise a decoy surface identical to a real auto_redact surface (trivially constructible in
any hand-built GT — Recorder.write()'s assertion guards the CORPUS, not the baselines) blinds
the oracle to that PII, and greedy silently leaks instead of failing the flag gate cleanly.

These fixtures are hand-built, NOT corpus-derived: they exercise ``_substitute`` (DOCX/text
path) and ``_rect_inside`` (PDF geometry path) directly.
"""
from __future__ import annotations

import fitz

from eval.baselines import _GREEDY_LABEL, _rect_inside, _substitute


# ------------------------------------------------------------------- _substitute (text path)
def test_substitute_equal_span_decoy_does_not_suppress_target():
    # Decoy surface identical to a target surface -> the decoy span EQUALS the target span.
    # Current code (`d0 <= span[0] and span[1] <= d1`) accepts the equal span and drops the
    # target, so the PII survives verbatim in greedy's output. It must be redacted.
    out = _substitute("zmluvu uzavrel Jan Novak dna", ["Jan Novak"], ["Jan Novak"])
    assert "Jan Novak" not in out, f"equal-span decoy suppressed a real target: {out!r}"
    assert _GREEDY_LABEL in out


def test_substitute_strictly_larger_decoy_still_protects_its_substring():
    # The genuine substring artifact must still be protected: "Novak" sits STRICTLY inside the
    # decoy "Novakov dom", so it is not an independent occurrence and must survive untouched.
    out = _substitute("Novakov dom pri ceste", ["Novak"], ["Novakov dom"])
    assert out == "Novakov dom pri ceste", f"strictly-larger decoy must protect substring: {out!r}"


# ------------------------------------------------------------------- _rect_inside (PDF path)
def test_rect_inside_equal_rect_does_not_suppress():
    # Same defect in the PDF path: an equal decoy rect satisfies all four <= comparisons, so
    # `_rect_inside` reports the target as contained and greedy skips redacting it. Equal rects
    # suppress nothing.
    target = fitz.Rect(10, 10, 50, 20)
    equal = fitz.Rect(10, 10, 50, 20)
    assert not _rect_inside(target, equal)


def test_rect_inside_strictly_larger_covering_rect_still_suppresses():
    # A decoy rect that STRICTLY covers the target (larger area, fully containing) is a real
    # substring artifact and must still suppress — the fix stays targeted, like leak.py.
    target = fitz.Rect(10, 10, 50, 20)
    larger = fitz.Rect(5, 5, 60, 30)
    assert _rect_inside(target, larger)
