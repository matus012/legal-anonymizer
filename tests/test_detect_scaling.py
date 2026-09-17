"""A guard against detect() becoming catastrophically slow on a pathological unit.

WHY THIS EXISTS, AND WHAT IT DOES **NOT** CLAIM
--------------------------------------------------------------------------------------
Red-team round 4 (R4-X2) reported ``detect()`` taking **3.19 s on 11 360 characters** of
capitalised surnames — a land-registry owner column — and suspected catastrophic backtracking
in ``detect/name_anchors.py``. That would be a denial of service: a single document hanging
the application forever.

**I could not reproduce it.** Measured on the committed tree, both with and without a
known-entity list, and for both the one-name-per-line and the one-long-line shapes:

    chars    blind    with known entities
     3 814   0.115 s  0.033 s
     7 624   0.064 s  0.087 s
    15 249   0.183 s  0.257 s
    30 499   0.585 s  0.868 s

That is roughly 3x per doubling — super-linear, about O(n^1.6), and nowhere near the reported
figure at that size (0.13 s where 3.19 s was reported). The likeliest explanation is that the
round measured against a tree another agent was mid-refactor in; the round itself flagged the
number as unisolated. Recorded here rather than silently dropped, because a wrong performance
number is as misleading as a wrong recall number.

**The growth is real and the exposure is not**, because of what the UNIT is:

  * ``writer/docx_body.py`` calls ``detect()`` once per ``<w:p>`` — one PARAGRAPH;
  * ``writer/pdf_body.py`` calls it once per PAGE.

Measured over the whole corpus: the longest paragraph is **157 characters** and the longest
PDF page **1 713**. The smallest input in the table above is already twice the largest real
unit. And ``gui/worker.py`` runs every scan on a ``QThread``, so even a slow unit cannot
freeze the window.

So this test does not pin the exponent, which would be flaky on a loaded machine and would
also be pinning a number nobody depends on. It pins a CEILING far above anything real, so that
a change which genuinely reintroduces exponential backtracking fails loudly while ordinary
variation never does.
"""
import time

import pytest

from detect.core import detect

NAMES = ["Novák", "Kováčová", "Horváth", "Molnárová", "Zelinka", "Baláž", "Šimko", "Tóthová"]
KNOWN = ["Ján Novák", "Mária Kováčová"]

# Far above any real unit (longest corpus paragraph 157 chars, longest page 1 713) and far
# above the measured 0.6-0.9 s at this size. A limit this loose only fires on a change of
# COMPLEXITY CLASS, which is the only thing worth failing a build over here.
_CHARS = 30_000
_CEILING_SECONDS = 15.0


def _owner_column(chars: int) -> str:
    out: list[str] = []
    total = 0
    i = 0
    while total < chars:
        name = NAMES[i % len(NAMES)]
        out.append(name)
        total += len(name) + 1
        i += 1
    return "\n".join(out)


@pytest.mark.parametrize("known", [[], KNOWN], ids=["blind", "known"])
def test_detect_does_not_blow_up_on_a_column_of_capitalised_names(known):
    """The shape red-team round 4 suspected of catastrophic backtracking: nothing but
    capitalised tokens, one per line, which is what a land-registry owner list looks like."""
    text = _owner_column(_CHARS)
    start = time.perf_counter()
    detect(text, known)
    elapsed = time.perf_counter() - start
    assert elapsed < _CEILING_SECONDS, (
        f"detect() took {elapsed:.1f}s on {len(text)} characters of capitalised names "
        f"(ceiling {_CEILING_SECONDS}s). Measured ~0.6-0.9s when this guard was written, so "
        f"this is a change of complexity class, not slow hardware."
    )


def test_a_realistic_unit_is_fast():
    """What the pipeline actually hands detect(): one paragraph, one page. If THIS ever became
    slow the tool would be unusable, and no amount of asymptotic argument would matter."""
    text = _owner_column(2_000)
    start = time.perf_counter()
    detect(text, KNOWN)
    assert time.perf_counter() - start < 2.0
