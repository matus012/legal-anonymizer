"""End-to-end leak gate — redact the whole synthetic corpus, then prove zero leaks.

    python -m eval.leak_gate

This is the committed form of the dual (DOCX + PDF) leak gate that closed the writer
rounds: for every synthetic document it runs the real writers (`writer.docx_body` /
`writer.pdf_body`) into a temp dir outside the repo, extracts every surface of the
output, and greps for ground-truth PII via :func:`eval.leak.find_leaks`. It is both
the demo entry point (the full pipeline, end to end) and the regression gate.

Synthetic data only — real client documents never enter development (context.md §7).
If ``data/synthetic`` is missing, regenerate it (seed-deterministic):

    python -m corpus.generate --n 60 --out data/synthetic --seed 42 --formats docx,pdf

Exit codes: 0 = PASS (zero non-excluded leaks), 1 = FAIL, 2 = corpus missing.

Leak classification is by ``Leak.found_in`` (where the string leaked in the output):
``text_layer`` anywhere in the tuple is a body-redaction failure; a tuple entirely
within the document-surface set (form_fields/attachments/info_metadata/xmp/annotations)
is a scrub failure; anything else is unexpected. All three buckets must be zero.

One qualification, added by the red-team round: the extractor now also reads OPAQUE
surfaces (a PDF's raw bytes and object source, every XML attribute value, binary parts).
Those are not text, and a short needle — a four-digit Slovak bank code, say — occurs in
them by chance. A match on an opaque surface therefore counts only when the
attributability rule below says it can be told apart from that noise, and every match
that rule sets aside is COUNTED AND PRINTED, never silently dropped. Text surfaces are
unaffected: a match there is a leak however short the needle.

Excluded by design (Class A): OBEC / KATASTER / ORG — gazetteer types deferred to v2,
GT-only in v1, genuinely undetectable rather than leaked-by-bug.

This module may import corpus/eval/writer but must NEVER import detect/ — the gate
must exercise detection only through the writers, exactly as production does.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

from eval.extract import extract
from eval.leak import Leak, find_leaks
from writer.docx_body import redact_docx_body
from writer.pdf_body import redact_pdf

# v1.1: OBEC and KATASTER are NO LONGER EXCLUDED. They were Class A only because v1 shipped
# without a gazetteer and they were genuinely undetectable; detect/gazetteer.py now detects
# them from the bundled CC0/CC-BY registers, so leaving them excluded would mean the gazetteer
# -- the largest single addition in this sprint -- was never actually gated. An excluded type
# is an UNTESTED type, and the exclusion list is the easiest place in this repo for a gate to
# quietly stop testing something. ORG stays excluded until its detector exists; that is the
# whole remaining content of Class A and it is tracked in status.txt.
# EMPTY as of v1.1. Class A was "types v1 genuinely could not detect" — OBEC and KATASTER
# left when the gazetteer shipped, and ORG leaves now that detect/orgs.py exists. An excluded
# type is an UNTESTED type, and this list is the easiest place in the repo for a gate to
# quietly stop asking about something.
#
# Worth recording how long ORG sat here after it stopped being true: detect/name_anchors.py
# has emitted ORG from the "Obchodné meno:" field label since the Phase C round, so a PARTIAL
# ORG detector existed and the exclusion was hiding a type that was already half-covered.
# Verified before emptying, on the corpus and with the set already empty: 150 ORG ground-truth
# occurrences, 130 of them in metadata (blanked by POSITION by the writer, never detected at
# all) and 20 in the body; ORG leaks measured text_layer=0 scrub=0 other=0.
CLASS_A_TYPES: set[str] = set()
_SCRUB_SURFACES = {"form_fields", "attachments", "info_metadata", "xmp", "annotations"}

# ---------------------------------------------------------------- attributability
# The §8.1 premise — "grep every GT PII string in every surface" — holds only where the
# haystack is text. The red-team round (redteam/FINDINGS.md) added surfaces that are NOT
# text: the raw bytes of a PDF, the source of every indirect object, the attribute values of
# every XML part (which include font PANOSE/signature hex blobs), and the strings inside
# binary parts. On those, a SHORT needle collides by chance. Measured on 40 redacted corpus
# outputs, as (distinct L-grams over that alphabet) / (alphabet ** L) — i.e. the probability
# that a uniformly random PII surface of that length appears in that surface of ONE document:
#
#   digits, raw_bytes        L=3 1.00      L=4 4.2e-01  L=5 3.7e-02  L=6 3.3e-03
#                            L=7 3.4e-04   L=8 3.4e-05  L=9 3.4e-06
#   digits, raw_bytes, DELIMITED (neither neighbour a hex digit)
#                            L=3 8.7e-01   L=4 1.8e-01  L=5 5.3e-03  L=6 1.3e-04
#                            L=7 5.8e-06   L=8 6.1e-07  L=9 2.9e-08
#   digits, xml_attributes   L=4 1.8e-02 (delimited 1.8e-03)   L=7 7.6e-06 (2.0e-07)
#   digits, pdf_objects      L=4 1.2e-01 (delimited 1.2e-01)   L=7 1.0e-07 (1.0e-07)
#   letters are 2-4 orders of magnitude safer at the same length.
#
# That is why the observed false positives were all KOD_BANKY: a Slovak bank code is FOUR
# digits, and a 4-digit string is present by chance in the font tables of ~1 DOCX in 50 and
# in the raw bytes of ~2 PDFs in 5. The body text of those documents was correctly redacted.
#
# The rule below needs BOTH halves, and the measurement is what says so:
#   * delimiting alone is not enough — a delimited 4-digit needle still collides in 18% of
#     PDFs (1.8e-01), which is ~25 false reds per corpus run;
#   * length alone is not enough — an undelimited 7-digit needle collides in 3.4e-04 of
#     documents, ~0.05 false reds per run, and shorter needles are far worse;
#   * together at L>=7: 5.8e-06 per document, under 0.001 false reds per corpus run.
# TEXT surfaces are NOT subject to this rule: any match there is a leak, however short.
_OPAQUE_SURFACES = {"raw_bytes", "pdf_objects", "xml_attributes", "binary_parts"}
_ATTRIBUTABLE_MIN_LEN = 7
_HEX_CHARS = frozenset("0123456789abcdefABCDEF")

# ---------------------------------------------------------------- the pdf_objects carve-out
# R6-03b. ``pdf_objects`` is ``doc.xref_object()`` -- THE SOURCE OF EVERY DICTIONARY IN THE
# FILE, which is where a PDF keeps its titles, labels, destination names, JavaScript and the
# alt text a screen reader speaks. The opaque premise ("this surface cannot hold document text,
# so a short match is a font table or an xref offset") is simply false for it, exactly as round
# 5 showed it was false for ``binary_parts``: a five-digit Slovak PSC and a four-digit bank
# code in the catalogue -- both AUTO-REDACT types -- were set aside as structural noise.
#
# BOTH REMEDIES THE FINDING OFFERS WERE MEASURED against the 71-document corpus before choosing.
#
#   * Taking ``pdf_objects`` out of ``_OPAQUE_SURFACES`` outright turns the gate RED:
#         leaks: text_layer=0 scrub=0 other=1   VERDICT: FAIL
#         LEAK zmluva_v11_020.pdf: type=KOD_BANKY found_in=('pdf_objects',)
#     and the match is this, in a CID font's /W widths array:
#         ' 1046 1099 750 1100 1102 318 1103 1126 750 '
#     i.e. the premise IS true for the part of ``pdf_objects`` that is font machinery. That is
#     a genuine false red on a correctly redacted document, so option A is unusable as it
#     stands -- it would train the office to ignore the gate.
#   * The carve-out below counts a match that lies inside a PDF **string** -- a literal
#     ``(Kovacova-Maria-)`` or a hex string ``<FEFF0050...>``, which is how Acrobat stores
#     anything with a diacritic. A string is a VALUE, never an offset, a length or a glyph
#     width, so length and hex-delimiting stop being the only evidence available. The /W array
#     above contains no parentheses and stays discounted; the PSC in ``/T (Spis 04001)`` and
#     the bank code in ``/ActualText (ucet 1100)`` are counted at four and five characters.
#
# Scoped to ``pdf_objects`` alone, and not extended to ``raw_bytes``, on purpose: raw_bytes is
# deduplicated printable RUNS of the whole file, where a parenthesis on either side of a needle
# means nothing in particular. Widening the carve-out there would have counted the second
# corpus set-aside ('1111' in zmluva_v11_034.pdf) on no evidence at all.
_STRING_CARVE_OUT_SURFACES = {"pdf_objects"}
_HEX_STRING_RE = re.compile(r"(?<!<)<([0-9A-Fa-f \t\r\n]{2,})>(?!>)")


def _pdf_string_values(text: str) -> list[str]:
    """Every PDF string VALUE in this object source: literals ``(...)`` with nesting and
    backslash escapes, and hex strings ``<...>`` decoded (``<<``/``>>`` are dictionaries)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "(":
            depth, j = 1, i + 1
            while j < n and depth:
                if text[j] == "\\":
                    j += 2
                    continue
                depth += 1 if text[j] == "(" else -1 if text[j] == ")" else 0
                j += 1
            if depth:
                break  # unbalanced source: nothing further can be read as a string
            out.append(text[i + 1 : j - 1])
            i = j
            continue
        i += 1
    for m in _HEX_STRING_RE.finditer(text):
        digits = re.sub(r"\s", "", m.group(1))
        if len(digits) % 2 == 0:
            raw = bytes.fromhex(digits)
            out += [raw.decode(enc, "ignore") for enc in ("utf-16-be", "latin-1")]
    return out


def _inside_pdf_string(text: str, needle: str) -> bool:
    return any(needle in value for value in _pdf_string_values(text))


def _has_delimited_occurrence(text: str, needle: str) -> bool:
    """True if ``needle`` occurs somewhere with a non-hex character on BOTH sides.

    Structural noise embeds the needle inside a longer hex/digit blob — a PANOSE string, a
    font signature, an xref offset, an object length. A genuine value does not: the
    extractor joins attribute values, relationship targets and binary strings with newlines,
    and a PDF string is wrapped in parentheses, so a real ``0200`` has a delimiter on each
    side while the ``0200`` inside ``00020000`` never does.
    """
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            return False
        before = text[idx - 1] if idx else " "
        after = text[idx + len(needle)] if idx + len(needle) < len(text) else " "
        if before not in _HEX_CHARS and after not in _HEX_CHARS:
            return True
        start = idx + 1


def is_attributable(text: str, needle: str, surface: str | None = None) -> bool:
    """Does a match of ``needle`` in this OPAQUE surface mean anything?

    See the measurement above. Never called for a text surface.

    ``surface`` is optional so every existing two-argument caller keeps the length+delimiter
    rule verbatim; naming ``pdf_objects`` adds the R6-03b carve-out, under which a match inside
    a PDF string literal or hex string counts at any length.
    """
    if surface in _STRING_CARVE_OUT_SURFACES and _inside_pdf_string(text, needle):
        return True
    return len(needle) >= _ATTRIBUTABLE_MIN_LEN and _has_delimited_occurrence(text, needle)


def split_found_in(leak: Leak, by_surface: dict[str, str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(surfaces the leak counts on, opaque surfaces where it is not attributable)``.

    A hit on any TEXT surface counts, full stop. A hit that exists ONLY on opaque surfaces
    counts only where :func:`is_attributable` says the match can be told apart from noise.
    """
    counted = tuple(s for s in leak.found_in if s not in _OPAQUE_SURFACES)
    set_aside: list[str] = []
    for surface in leak.found_in:
        if surface not in _OPAQUE_SURFACES:
            continue
        if is_attributable(by_surface.get(surface, ""), leak.surface, surface):
            counted += (surface,)
        else:
            set_aside.append(surface)
    return counted, tuple(set_aside)


def _classify(found_in: tuple[str, ...]) -> str:
    if "text_layer" in found_in:
        return "text_layer"
    if set(found_in) <= _SCRUB_SURFACES:
        return "scrub"
    return "other"


def run_gate(corpus_dir: Path) -> int:
    files = sorted(
        p
        for p in corpus_dir.glob("*")
        if p.suffix in {".docx", ".pdf"}
        and "scan_image_only" not in p.name
        # A corpus file with no ground truth is not gradeable. Historically a stray
        # redaction output left in the corpus dir (foo_anon.docx) crashed the gate on a
        # missing foo_anon.docx.gt.json; skipping GT-less files makes the gate robust to
        # anything that lands next to the corpus without silently reducing coverage —
        # the skipped names are printed.
        and Path(f"{p}.gt.json").exists()
    )
    skipped = sorted(
        p.name
        for p in corpus_dir.glob("*")
        if p.suffix in {".docx", ".pdf"}
        and "scan_image_only" not in p.name
        and not Path(f"{p}.gt.json").exists()
    )
    if skipped:
        print(f"skipped (no .gt.json): {', '.join(skipped)}")
    if not files:
        print(f"no corpus at {corpus_dir} — regenerate it first:")
        print("  python -m corpus.generate --n 60 --out data/synthetic --seed 42 --formats docx,pdf")
        return 2

    counts = {"text_layer": 0, "scrub": 0, "other": 0}
    failing: list[tuple[str, Leak, tuple[str, ...]]] = []
    # Matches on opaque surfaces that the attributability rule could not tell from noise.
    # Counted and PRINTED on every run, zero or not: a limitation nobody can see is a
    # limitation nobody accounts for.
    set_aside: list[tuple[str, Leak, tuple[str, ...]]] = []
    n_docx = n_pdf = 0

    with tempfile.TemporaryDirectory() as tmp:
        for src in files:
            gt = json.loads(Path(f"{src}.gt.json").read_text(encoding="utf-8"))
            known = [e["canonical"] for e in gt["entities"] if e.get("category") == "MENO"]
            out = Path(tmp) / src.name
            if src.suffix == ".docx":
                redact_docx_body(str(src), str(out), known_entities=known)
                n_docx += 1
            else:
                redact_pdf(str(src), str(out), known_entities=known)
                n_pdf += 1
            res = extract(str(out))
            for leak in find_leaks(gt, res):
                if leak.type in CLASS_A_TYPES:
                    continue
                counted, unattributable = split_found_in(leak, res.by_surface)
                if counted:
                    counts[_classify(counted)] += 1
                    failing.append((src.name, leak, counted))
                if unattributable:
                    set_aside.append((src.name, leak, unattributable))

    print(f"redacted: {n_docx} docx + {n_pdf} pdf")
    print(
        f"leaks: text_layer={counts['text_layer']} "
        f"scrub={counts['scrub']} other={counts['other']} "
        + (f"({len(CLASS_A_TYPES)} type(s) excluded: {', '.join(sorted(CLASS_A_TYPES))})"
           if CLASS_A_TYPES else "(NO type exclusions)")
    )
    for name, leak, counted in failing:
        print(f"  LEAK {name}: type={leak.type} found_in={counted}")

    # The visible limitation: what the gate looked at and could not attribute.
    by_surface_count: dict[str, int] = {}
    for _, _, surfaces in set_aside:
        for s in surfaces:
            by_surface_count[s] = by_surface_count.get(s, 0) + 1
    where = ", ".join(f"{s}={n}" for s, n in sorted(by_surface_count.items())) or "-"
    print(
        f"set aside (opaque-surface matches below the attributability rule): "
        f"{len(set_aside)} match(es) in {len({n for n, _, _ in set_aside})} doc(s); {where}; "
        f"rule: needle >= {_ATTRIBUTABLE_MIN_LEN} chars AND one occurrence with a non-hex "
        f"character on both sides -- OR, on {'/'.join(sorted(_STRING_CARVE_OUT_SURFACES))}, "
        f"any occurrence inside a PDF string literal or hex string, which is a value and not "
        f"an offset (redteam/FINDINGS.md, KNOWN BLIND SPOTS; R6-03b)"
    )
    for name, leak, surfaces in set_aside[:20]:
        print(f"  set-aside {name}: type={leak.type} surface={leak.surface!r} in {surfaces}")
    if len(set_aside) > 20:
        print(f"  ... and {len(set_aside) - 20} more")

    verdict_pass = not failing
    print("VERDICT:", "PASS" if verdict_pass else "FAIL")
    return 0 if verdict_pass else 1


def main() -> int:
    return run_gate(Path("data/synthetic"))


if __name__ == "__main__":
    sys.exit(main())
