"""``writer/pdf_body._locate`` — finding a surface on the page when search_for cannot.

WHY THIS NEEDED ITS OWN FILE
--------------------------------------------------------------------------------------
The PDF writer does not redact by offset. It re-locates each candidate by SEARCHING THE PAGE
for its surface, because ``get_text("text")`` is not positionally reversible to glyph boxes.
That was fine while detect()'s regexes refused to span a line break: no candidate surface ever
contained a character the page had not drawn.

The v1.1 normalization layer changed that premise. Surfaces are now byte-faithful to the
document, so they can legitimately contain a ``\\n`` (a wrapped line) or a U+200B (a zero-width
space pasted in from a bank portal) — and ``search_for`` matches neither, because neither has
a glyph. Without a fallback the detection improvement would have converted silent misses into
``RedactionIncompleteError``: the writer refusing to produce a file at all.

So the fallback is load-bearing, and its failure mode is the dangerous direction. These tests
use a FAKE page (``search_for`` is the only method ``_locate`` touches) so each attempt can be
driven exactly, including the one that must NOT happen.
"""
import pytest

from writer.pdf_body import _locate

ZWSP = "​"
SHY = "­"


class FakePage:
    """A page that knows a fixed set of drawn strings. Records every needle tried, so a test
    can assert on the SEQUENCE of attempts and not merely the result."""

    def __init__(self, drawn):
        self.drawn = set(drawn)
        self.queries: list[str] = []

    def search_for(self, needle):
        self.queries.append(needle)
        return [f"rect({needle})"] if needle in self.drawn else []


def test_an_ordinary_surface_is_found_on_the_first_attempt():
    page = FakePage(["850315/0018"])
    rects, complete = _locate(page, "850315/0018")
    assert rects and complete
    assert page.queries == ["850315/0018"], "no fallback should run when the direct search works"


def test_a_missing_surface_reports_incomplete_with_no_rects():
    """The anti-theatre invariant: an unlocatable surface must NOT come back looking located."""
    page = FakePage([])
    rects, complete = _locate(page, "850315/0018")
    assert rects == []
    assert complete is False


def test_an_invisible_character_is_stripped_and_the_surface_is_found():
    """A zero-width space inside an account number has no glyph, so the page was drawn without
    it. Searching for the surface as the DOCUMENT holds it finds nothing; searching for what
    was actually drawn finds it."""
    page = FakePage(["850315/0018"])
    rects, complete = _locate(page, f"8503{ZWSP}15/0018")
    assert rects and complete
    assert page.queries == [f"8503{ZWSP}15/0018", "850315/0018"]


def test_a_soft_hyphen_is_stripped_too():
    page = FakePage(["SK6807200002891987426353"])
    rects, complete = _locate(page, f"SK68072000028919{SHY}87426353")
    assert rects and complete


def test_a_surface_split_by_a_line_break_is_located_piece_by_piece():
    """The wrapped-line case. Both halves are genuine contiguous runs of the surface, so each
    is findable on its own line even though the whole never is."""
    page = FakePage(["+421 905", "123 456"])
    rects, complete = _locate(page, "+421 905\n123 456")
    assert complete
    assert len(rects) == 2


def test_a_partially_located_surface_is_reported_INCOMPLETE():
    """The case that must never be reported as success. Half the phone number is destroyed and
    half survives, which reads as a clean redaction in every report unless this says otherwise
    -- and a partial redaction of a single token is a leak, not a lower score."""
    page = FakePage(["+421 905"])          # the second line is not drawn
    rects, complete = _locate(page, "+421 905\n123 456")
    assert rects, "the half it CAN destroy is still destroyed"
    assert complete is False, "but the caller must be told the job was not finished"


def test_the_fallback_NEVER_splits_on_a_plain_space():
    """The single most dangerous thing this function could do.

    Splitting a surface into whitespace-separated tokens would put "01" or "25" on the page as
    a search needle and black out every unrelated occurrence of that fragment -- damage spread
    across the whole document in the name of redacting one span. Splitting happens at NEWLINES
    ONLY. Asserted on the QUERIES, not on the result, because a fallback that produced the
    right answer by the wrong route would pass a result-only test and still be a hazard.
    """
    page = FakePage(["Hlavná", "25", "040", "01", "Košice"])
    rects, complete = _locate(page, "Hlavná 25, 040 01 Košice")
    assert rects == []
    assert complete is False
    assert page.queries == ["Hlavná 25, 040 01 Košice"], (
        f"only the whole surface may be searched for; tried {page.queries}"
    )


def test_a_single_line_surface_never_reaches_the_piecewise_stage():
    page = FakePage([])
    _locate(page, "Ján Novák")
    assert page.queries == ["Ján Novák"]


@pytest.mark.parametrize("needle", ["", " ", "\n", ZWSP, f"{ZWSP}{SHY}"])
def test_degenerate_needles_do_not_raise(needle):
    """These reach _locate only through a bug upstream, but an exception here would surface as
    the PDF writer crashing mid-document -- exactly what detector isolation exists to prevent,
    and it would be embarrassing to reintroduce it in the writer."""
    rects, complete = _locate(FakePage([]), needle)
    assert rects == []
    assert complete is False
