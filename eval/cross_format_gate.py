"""Cross-format consistency gate — Phase E, GATED (CONTRACTS_v11.md).

    python -m eval.cross_format_gate

This gate compares the ``.docx`` and ``.pdf`` renderings of ONE logical document
surface-for-surface, and grades TWO populations in the same run:

* **A — authored controls** (6 matched pairs, built here from ``corpus.pii.*`` +
  ``corpus.docx_builder`` / ``corpus.pdf_builder``). Hand-authored, content computed ONCE
  before any builder touches a RNG and the literal ``PiiSpec`` objects placed into BOTH
  builders verbatim. This is the only population whose content this module fully controls,
  and it is where the NBSP and line-break leaks this gate exists to catch were actually
  found. Deliberately kept even though the real corpus is now usable — see HISTORY.
* **B — the real corpus** (``data/synthetic``, every stem that exists as both ``.docx`` and
  ``.pdf``). The population the gate was always supposed to have.

Both populations are reported separately — a reader must be able to tell which one an
asymmetry came from — and the VERDICT covers both.

Cost: 152 redactions (76 pairs x 2 formats) through the real writers, ~80 s wall on the
reference machine. That is cheap enough to run every round; if it ever stops being, split
population B off behind a flag rather than shrinking it silently.

--------------------------------------------------------------------------------------
HISTORY — why the authored controls exist (do NOT "simplify" them away)
--------------------------------------------------------------------------------------
THE FINDING (made when this gate was first written; **FIXED 2026-09-17**, QUESTIONS.md Q14):
``data/synthetic``'s two files with the same stem were NOT one document in two formats, so
this gate could not read the corpus at all and authored its own fixtures instead. Two
independent causes:

1. ``corpus/generate.py::_emit`` derived each file's RNG seed as ``seed*1000 + i*10 + f_idx``
   with ``f_idx`` the format's position in ``--formats``, so docx and pdf of the same index
   ran from two different random streams — different people, different identifiers, same
   template. Measured then on ``kupna_zmluva_000``: 46 vs 40 ground-truth surfaces, 3 in
   common, and those three coincidental repeats.
2. ``corpus/docx_builder.DocxBuilder`` drew its split-run decision from the SAME
   ``random.Random`` as the template used for content, so even one shared seed would have
   desynchronised the streams at the first ``PiiSpec``.

THE FIX (2026-09-17): ``corpus/builders_plan.py`` now authors a format-neutral content PLAN
once per (doc_type, index) and replays it into each renderer, dropping only the ops a format
cannot express; ``DocxBuilder`` was given its own layout RNG. Measured across all 70 corpus
pairs: unexplained one-sided ground-truth surfaces 5285 -> 0, surfaces common to both formats
136 -> 3039. ``tools/paired_gt_report.py --corpus data/synthetic`` asserts that invariant
independently and prints ``TOTAL unexplained surfaces across 70 pairs: 0``.

WHY POPULATION A STAYS: the corpus is broad but its content is drawn by a generator, so the
specific traps this gate was built around — a NBSP inside a ``RODNE_CISLO``, a multi-word
anchor split across a line break, a surface deliberately split across DOCX runs — are present
only if a draw happens to produce them. The authored pairs place them every run, by
construction. Dropping them would trade a precise instrument for a broad one; the two
populations answer different questions and the gate needs both.

The format-specific part tables are NOT redefined here: ``DOCX_ONLY_PARTS`` and
``PDF_ONLY_PARTS`` are imported from ``corpus/builders_plan.py``, the same table the corpus
renderer and ``tools/paired_gt_report.py`` use. A second copy would drift.

--------------------------------------------------------------------------------------
COMPARISON UNIT
--------------------------------------------------------------------------------------
Per document, per PII surface STRING (deduplicated, matching ``eval/mutation_gate.py`` and
``eval/leak_gate.py``'s convention). Scope: the ground truth's ``auto_redact`` class only —
"detected" here means "removed from the redacted output", the same predicate the leak gate
uses: :func:`eval.leak.surface_present` negated, per EXTRACTED SURFACE, with
:func:`eval.leak_gate.is_attributable` deciding whether a match that exists only on an opaque
surface can be told from chance collision (see :func:`_survives` — this gate's first run over
the real corpus failed on two four-digit KOD_BANKY matches inside PDF font machinery, which
is precisely the noise class that rule was measured to describe). Decoy suppression uses each
document's own must-survive surfaces, as ``eval.leak.find_leaks`` does. ``should_flag`` /
decoy surfaces are excluded from the comparison: they are not supposed to be redacted in
EITHER format, so a survive/survive pair carries no information about detector parity.

A surface only enters the comparison when its ground-truth ``location.surface_part`` is one
this module calls COMPARABLE — a part that has a real equivalent in both formats and carries
identical content in both renderings. Everything else is a NAMED, COUNTED exclusion:

* ``DOCX_ONLY_PARTS`` (from ``corpus.builders_plan``) — header, footer, footnote, endnote,
  comment, textbox, tracked-change ins/del, ``docProps/app.xml``. No PDF equivalent exists.
* ``PDF_ONLY_PARTS`` (same source) — annotation, form_field, attachment, XMP. No DOCX
  equivalent (DOCX has no annotations, no AcroForm fields, no XMP packet).
* ``SHARED_NON_COMPARABLE_PARTS`` — ``metadata_core`` (DOCX) and ``metadata`` (PDF). Both
  formats DO have document metadata, so neither is format-only, but the two are different
  fields written by different calls (``set_metadata_docx`` vs ``set_metadata_pdf`` in the
  plan) and are not surface-for-surface comparable. Excluded, named, counted.
* ``COMPARABLE_PARTS = {"body", "table_cell"}`` — ordinary flowed text, rendered from the
  same plan ops in both formats, so a surface found here is genuinely comparable.

THREE DIFFERENT ASYMMETRIES, and this gate is explicit about which it measures:

1. **Ground-truth asymmetry** — the two ``.gt.json`` files themselves disagree: a surface is
   recorded in a COMPARABLE part of one format and not of the other. That is a corpus defect,
   not a product defect. Reported separately, per population, and it fails the gate, because
   a population without the property makes the rest of the comparison meaningless.
2. **Output asymmetry** — the surface is comparable in BOTH ground truths, and is gone from
   one format's redacted output while still extractable from the other's. That is the finding
   this gate exists for.
3. Output asymmetry splits further into a DETECTION failure (``detect()`` never proposed the
   span in that format) and a REDACTION failure (proposed in both, removed in only one). This
   gate CANNOT tell those apart and does not claim to: its premise, shared with
   ``eval/leak_gate.py``, is end-to-end — it must exercise detection only through the writers
   and may never import ``detect/``. Splitting an output asymmetry is a follow-up diagnostic,
   run by hand against ``detect/`` on the specific document the gate names.

Gate: **zero ground-truth asymmetries and zero output asymmetries, on BOTH populations.** A
surface removed from one format's output and left standing in the other's, from the same
logical document, is a real per-format defect (an anchor phrase, a whitespace normalisation,
an offset bug that only one writer's paragraph-reconstruction triggers). If this fires on the
current code it is a FINDING, printed with the exact document/type/surface — it is not
weakened to pass.

This module imports ``writer/`` (to redact) and ``eval/`` (to extract + judge), and
``corpus/builders_plan`` / ``corpus/docx_builder`` / ``corpus/pdf_builder`` /
``corpus/groundtruth`` / ``corpus/pii/*`` READ-ONLY, to build its own fixtures — never
``detect/`` directly (like ``eval/leak_gate.py``, this gate's premise is end-to-end: it must
exercise detection only through the writers).

Exit codes: 0 = PASS (zero asymmetries on both populations), 1 = FAIL, 2 = corpus missing.
"""
from __future__ import annotations

import json
import random
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from corpus.builders_plan import DOCX_ONLY_PARTS, PDF_ONLY_PARTS
from corpus.docx_builder import DocxBuilder
from corpus.groundtruth import PiiSpec, Recorder
from corpus.pdf_builder import PdfBuilder
from corpus.pii import amounts, dates, dic, email, ic_dph, iban, ico, phone, registry_refs, rodne_cislo, url
from eval.extract import extract
from eval.leak import surface_present
from eval.leak_gate import _OPAQUE_SURFACES, is_attributable
from writer.docx_body import redact_docx_body
from writer.pdf_body import redact_pdf

COMPARABLE_PARTS = {"body", "table_cell"}
# Both formats have document metadata, so neither field is format-ONLY — but they are
# different fields written by different calls, so they are not comparable either.
SHARED_NON_COMPARABLE_PARTS = {"metadata_core", "metadata"}
_KNOWN_PARTS = (
    COMPARABLE_PARTS | SHARED_NON_COMPARABLE_PARTS | set(DOCX_ONLY_PARTS) | set(PDF_ONLY_PARTS)
)

N_FIXTURES = 6          # matched pairs authored per run
_SEED_BASE = 90000
CORPUS_DIR = Path("data/synthetic")
_GT_STEM = re.compile(r"^(?P<stem>.+)\.(?P<ext>docx|pdf)\.gt\.json$")


# --------------------------------------------------------------------------- fixture authoring
def _content(idx: int) -> dict[str, PiiSpec]:
    """Literal PII content for one fixture, computed ONCE from a standalone RNG that no
    builder ever touches — see the module FINDING above for why that matters."""
    rng = random.Random(_SEED_BASE + idx)
    return {
        "name": PiiSpec(f"Ján Novák{idx}", "MENO", entity_id="p1"),
        "rc": PiiSpec(rodne_cislo.generate(rng, valid=True), "RODNE_CISLO", valid_checksum=True),
        "rc_nbsp": PiiSpec(
            rodne_cislo.generate(rng, valid=True).replace("/", " / "),
            "RODNE_CISLO", valid_checksum=True,
        ),
        "ico": PiiSpec(ico.generate(rng, valid=True), "ICO", valid_checksum=True),
        "dic": PiiSpec(dic.generate(rng), "DIC"),
        "ic_dph": PiiSpec(ic_dph.generate(rng), "IC_DPH"),
        "iban": PiiSpec(iban.generate(rng, valid=True), "IBAN", valid_checksum=True),
        "email": PiiSpec(email.generate(rng), "EMAIL"),
        "phone": PiiSpec(phone.generate(rng), "TELEFON"),
        "url": PiiSpec(url.generate(rng), "URL"),
        "lv": PiiSpec(registry_refs.lv(rng), "LV"),
        "parcela": PiiSpec(registry_refs.parcela(rng), "PARCELA"),
        "spis": PiiSpec(registry_refs.spisova_znacka(rng), "SPISOVA_ZNACKA"),
        "suma": PiiSpec(amounts.generate(rng), "SUMA"),
        "datum_narodenia": PiiSpec(dates.generate(rng), "DATUM"),
    }


@dataclass(frozen=True)
class Pair:
    name: str
    docx_gt: dict
    pdf_gt: dict
    docx_out: Path
    pdf_out: Path
    # An authored control may not have a one-sided comparable surface (this module places
    # them identically on purpose), so there it is a fixture bug and raises. In the corpus it
    # is a measurable corpus property and is reported as a ground-truth asymmetry.
    strict: bool = True


def _author_pair(idx: int, out: Path) -> Pair:
    stem = f"xfmt_{idx:02d}"
    c = _content(idx)
    known = [c["name"].surface]

    docx_rec = Recorder(f"{stem}.docx", "xfmt_fixture", _SEED_BASE + idx)
    pdf_rec = Recorder(f"{stem}.pdf", "xfmt_fixture", _SEED_BASE + idx)
    for rec in (docx_rec, pdf_rec):
        rec.entity("p1", c["name"].surface, "MENO", [c["name"].surface])

    docx_b = DocxBuilder(docx_rec, random.Random(_SEED_BASE + idx))
    pdf_b = PdfBuilder(pdf_rec)

    # --- shared / comparable content: byte-identical PiiSpec objects into BOTH builders ---
    shared_paragraphs = [
        ["Predávajúci: ", c["name"], "."],
        ["Rodné číslo: ", c["rc"], "."],                       # NBSP-adjacent anchor —
        ["Rodné číslo (NBSP v čísle): ", c["rc_nbsp"], "."],        # the historical leak class
        ["IČO: ", c["ico"], ", DIČ: ", c["dic"], ", IČ DPH: ", c["ic_dph"], "."],
        ["IBAN: ", c["iban"], "."],
        ["E-mail: ", c["email"], ", telefón: ", c["phone"], ", web: ", c["url"], "."],
        ["List vlastníctva č. ", c["lv"], ", parcela č. ", c["parcela"], "."],
        ["Spisová značka ", c["spis"], ", kúpna cena ", c["suma"], "."],
        ["Dátum narodenia: ", c["datum_narodenia"], "."],
    ]
    shared_table = [
        [["Typ"], ["Hodnota"]],
        [["Meno"], [c["name"]]],
        [["Rodné číslo"], [c["rc"]]],
    ]
    for items in shared_paragraphs:
        docx_b.paragraph(items)
        pdf_b.paragraph(items)
    docx_b.table(shared_table)
    pdf_b.table(shared_table)

    # --- DOCX-only structural parts (named exclusion, no PDF equivalent) ---
    docx_b.header(["Kontakt: ", PiiSpec(c["email"].surface, "EMAIL")])
    docx_b.footer(["Tel.: ", PiiSpec(c["phone"].surface, "TELEFON")])
    docx_b.footnote("Poznámka.", ["IČO uvedené vyššie: ", PiiSpec(c["ico"].surface, "ICO", valid_checksum=True)])
    docx_b.endnote("Vysvetlivka.", ["DIČ: ", PiiSpec(c["dic"].surface, "DIC")])
    docx_b.comment("overiť", [PiiSpec(c["name"].surface, "MENO", entity_id="p1")])
    docx_b.textbox([PiiSpec(c["suma"].surface, "SUMA")])
    docx_b.tracked_change("Pôvodne: ", [PiiSpec(c["iban"].surface, "IBAN", valid_checksum=True)],
                          [PiiSpec(c["url"].surface, "URL")])
    docx_b.set_metadata(PiiSpec(f"JUDr. {c['name'].surface}", "MENO"))

    # --- PDF-only structural parts (named exclusion, no DOCX equivalent) ---
    pdf_b.annotation(["Overiť: ", PiiSpec(c["name"].surface, "MENO", entity_id="p1")])
    pdf_b.form_field("iban", PiiSpec(c["iban"].surface, "IBAN", valid_checksum=True))
    pdf_b.attachment("priloha.txt", [PiiSpec(c["phone"].surface, "TELEFON")])
    pdf_b.set_metadata(
        PiiSpec(f"JUDr. {c['name'].surface}", "MENO"),
        PiiSpec(c["name"].surface, "MENO"),
    )

    docx_path, pdf_path = out / f"{stem}.docx", out / f"{stem}.pdf"
    docx_b.save(docx_path)
    pdf_b.save(pdf_path)
    docx_out, pdf_out = out / f"{stem}_anon.docx", out / f"{stem}_anon.pdf"
    redact_docx_body(str(docx_path), str(docx_out), known_entities=known)
    redact_pdf(str(pdf_path), str(pdf_out), known_entities=known)
    return Pair(stem, docx_rec.to_dict(), pdf_rec.to_dict(), docx_out, pdf_out)


# --------------------------------------------------------------------------- corpus pairs
def corpus_stems(corpus_dir: Path) -> list[tuple[str, Path, Path]]:
    """``(stem, docx, pdf)`` for every corpus stem that exists in BOTH formats with GT.

    Since QUESTIONS.md Q14 these two files are one logical document rendered twice, which is
    the precondition this gate needs; ``tools/paired_gt_report.py`` is the independent check
    of that claim.
    """
    found: dict[str, dict[str, Path]] = defaultdict(dict)
    for gt_path in sorted(corpus_dir.glob("*.gt.json")):
        m = _GT_STEM.match(gt_path.name)
        if not m or "scan_image_only" in m.group("stem"):
            continue
        doc = corpus_dir / f"{m.group('stem')}.{m.group('ext')}"
        if doc.exists():
            found[m.group("stem")][m.group("ext")] = doc
    return [
        (stem, got["docx"], got["pdf"])
        for stem, got in sorted(found.items())
        if set(got) == {"docx", "pdf"}
    ]


def _redact_corpus_pair(stem: str, docx_src: Path, pdf_src: Path, out: Path) -> Pair:
    """Redact one corpus pair through the real writers, exactly as ``eval/leak_gate.py``
    does (same ``known_entities`` convention: the MENO canonicals of that file's own GT)."""
    docx_gt = json.loads(Path(f"{docx_src}.gt.json").read_text(encoding="utf-8"))
    pdf_gt = json.loads(Path(f"{pdf_src}.gt.json").read_text(encoding="utf-8"))
    docx_out = out / f"{stem}_anon.docx"
    pdf_out = out / f"{stem}_anon.pdf"
    redact_docx_body(str(docx_src), str(docx_out),
                     known_entities=[e["canonical"] for e in docx_gt["entities"]
                                     if e.get("category") == "MENO"])
    redact_pdf(str(pdf_src), str(pdf_out),
               known_entities=[e["canonical"] for e in pdf_gt["entities"]
                               if e.get("category") == "MENO"])
    return Pair(stem, docx_gt, pdf_gt, docx_out, pdf_out, strict=False)


# --------------------------------------------------------------------------- measurement
@dataclass
class Verdict:
    pairs: int = 0
    checked: int = 0
    excluded_docx_only: int = 0
    excluded_pdf_only: int = 0
    excluded_shared_non_comparable: int = 0
    excluded_unknown_part: int = 0
    asymmetries: list[tuple[str, str, str, bool, bool]] = field(default_factory=list)
    # (doc, type, surface, redacted_in_docx, redacted_in_pdf) — OUTPUT asymmetry (kind 2)
    gt_asymmetries: list[tuple[str, str, str, str]] = field(default_factory=list)
    # (doc, type, surface, format that has it in a comparable part) — GROUND-TRUTH (kind 1)
    set_aside: list[tuple[str, str, str, str, tuple[str, ...]]] = field(default_factory=list)
    # (doc, type, surface, format, opaque surfaces) — matches the attributability rule
    # could not tell from chance collision. Printed every run: a limitation nobody can see
    # is a limitation nobody accounts for.

    @property
    def failed(self) -> bool:
        return bool(self.asymmetries or self.gt_asymmetries)


def _comparable_surfaces(gt: dict) -> dict[tuple[str, str], str]:
    """{(type, surface): surface_part} for this GT's auto_redact rows in COMPARABLE_PARTS,
    deduped per document (mirrors mutation_gate/leak_gate convention)."""
    out: dict[tuple[str, str], str] = {}
    for pii in gt["pii"]:
        if not pii["auto_redact"]:
            continue
        part = pii["location"]["surface_part"]
        if part not in COMPARABLE_PARTS:
            continue
        out[(pii["type"], pii["surface"])] = part
    return out


def _all_parts(gt: dict) -> set[str]:
    return {pii["location"]["surface_part"] for pii in gt["pii"]}


def _decoys(gt: dict) -> list[str]:
    """Must-survive surfaces of this document (``eval.leak.find_leaks``'s convention)."""
    return [p["surface"] for p in gt["pii"] if not p["auto_redact"] and not p["should_flag"]]


def _survives(text: str, by_surface: dict[str, str] | None, surface: str,
              decoys: list[str]) -> tuple[bool, tuple[str, ...]]:
    """``(still extractable, opaque surfaces whose match was set aside)``.

    With ``by_surface`` given this is ``eval/leak_gate.py``'s predicate exactly: a match on
    any TEXT surface counts however short the needle; a match that exists only on an OPAQUE
    surface (raw bytes, PDF object source, XML attribute values, binary parts) counts only
    where :func:`eval.leak_gate.is_attributable` says it can be told from chance collision.
    That rule is NOT a weakening added to make this gate green — it is the predicate the leak
    gate already grades the same corpus with, and running the two gates on two different
    definitions of "still present" is what produced the first FAIL here: both hits were a
    four-digit KOD_BANKY inside a CID font's /W widths array and inside a compressed stream,
    on documents whose text layer was correctly redacted. Every set-aside is counted and
    printed, zero or not.

    With ``by_surface`` None the haystack is the plain concatenated text — the pure form the
    unit tests use.
    """
    if by_surface is None:
        return surface_present(text, surface, decoys), ()
    counted: list[str] = []
    set_aside: list[str] = []
    for part, hay in by_surface.items():
        if not surface_present(hay, surface, decoys):
            continue
        if part in _OPAQUE_SURFACES and not is_attributable(hay, surface, part):
            set_aside.append(part)
        else:
            counted.append(part)
    return bool(counted), tuple(sorted(set_aside))


def judge_pair(name: str, docx_gt: dict, pdf_gt: dict, docx_text: str, pdf_text: str,
               strict: bool = True,
               docx_by_surface: dict[str, str] | None = None,
               pdf_by_surface: dict[str, str] | None = None) -> Verdict:
    """The comparison for ONE matched pair, decoupled from file I/O so it is directly unit
    testable (tests/test_cross_format_gate.py) without redacting a real docx/pdf.

    ``strict`` (authored controls) raises on a comparable surface present in only one format,
    because this module builds those pairs identically on purpose and any difference is a
    fixture bug. On the corpus (``strict=False``) the same observation is a measurable
    GROUND-TRUTH asymmetry and is recorded, not raised.
    """
    v = Verdict(pairs=1)
    unknown = (_all_parts(docx_gt) | _all_parts(pdf_gt)) - _KNOWN_PARTS
    if unknown:
        raise AssertionError(f"{name}: unclassified surface_part(s) {unknown} — "
                              f"add them to COMPARABLE_PARTS/DOCX_ONLY_PARTS/PDF_ONLY_PARTS")

    for pii in docx_gt["pii"]:
        if pii["auto_redact"] and pii["location"]["surface_part"] in DOCX_ONLY_PARTS:
            v.excluded_docx_only += 1
    for pii in pdf_gt["pii"]:
        if pii["auto_redact"] and pii["location"]["surface_part"] in PDF_ONLY_PARTS:
            v.excluded_pdf_only += 1
    for gt in (docx_gt, pdf_gt):
        for pii in gt["pii"]:
            if pii["auto_redact"] and pii["location"]["surface_part"] in SHARED_NON_COMPARABLE_PARTS:
                v.excluded_shared_non_comparable += 1

    docx_comp = _comparable_surfaces(docx_gt)
    pdf_comp = _comparable_surfaces(pdf_gt)
    common = set(docx_comp) & set(pdf_comp)
    # Surfaces authored as comparable in one format but not the other would themselves be
    # a fixture-authoring bug (this module builds them identically on purpose) — assert
    # rather than silently exclude, since here (unlike the real corpus) there's no reason
    # for it to happen.
    only_docx = set(docx_comp) - set(pdf_comp)
    only_pdf = set(pdf_comp) - set(docx_comp)
    if (only_docx or only_pdf) and strict:
        raise AssertionError(
            f"{name}: comparable-part surfaces present in only one format "
            f"(fixture bug, not a product finding): docx_only={only_docx} pdf_only={only_pdf}"
        )
    for type_, surface in sorted(only_docx):
        v.gt_asymmetries.append((name, type_, surface, "docx"))
    for type_, surface in sorted(only_pdf):
        v.gt_asymmetries.append((name, type_, surface, "pdf"))

    docx_decoys, pdf_decoys = _decoys(docx_gt), _decoys(pdf_gt)
    for type_, surface in sorted(common):
        v.checked += 1
        docx_alive, docx_aside = _survives(docx_text, docx_by_surface, surface, docx_decoys)
        pdf_alive, pdf_aside = _survives(pdf_text, pdf_by_surface, surface, pdf_decoys)
        for fmt, aside in (("docx", docx_aside), ("pdf", pdf_aside)):
            if aside:
                v.set_aside.append((name, type_, surface, fmt, aside))
        docx_redacted, pdf_redacted = not docx_alive, not pdf_alive
        if docx_redacted != pdf_redacted:
            v.asymmetries.append((name, type_, surface, docx_redacted, pdf_redacted))
    return v


def _merge(a: Verdict, b: Verdict) -> Verdict:
    return Verdict(
        pairs=a.pairs + b.pairs,
        checked=a.checked + b.checked,
        excluded_docx_only=a.excluded_docx_only + b.excluded_docx_only,
        excluded_pdf_only=a.excluded_pdf_only + b.excluded_pdf_only,
        excluded_shared_non_comparable=(
            a.excluded_shared_non_comparable + b.excluded_shared_non_comparable),
        asymmetries=a.asymmetries + b.asymmetries,
        gt_asymmetries=a.gt_asymmetries + b.gt_asymmetries,
        set_aside=a.set_aside + b.set_aside,
    )


def measure(pairs: list[Pair]) -> Verdict:
    v = Verdict()
    for pair in pairs:
        docx_res = extract(pair.docx_out)
        pdf_res = extract(pair.pdf_out)
        v = _merge(v, judge_pair(pair.name, pair.docx_gt, pair.pdf_gt,
                                  docx_res.full_text, pdf_res.full_text, strict=pair.strict,
                                  docx_by_surface=docx_res.by_surface,
                                  pdf_by_surface=pdf_res.by_surface))
    return v


# --------------------------------------------------------------------------- reporting
def _report(label: str, what: str, v: Verdict) -> None:
    print(f"--- POPULATION {label}: {what}")
    print(f"    {v.pairs} matched pair(s), {v.checked} comparable auto-redact surface(s) checked")
    print(f"    excluded, counted: docx-only parts = {v.excluded_docx_only}, "
          f"pdf-only parts = {v.excluded_pdf_only}, "
          f"shared-but-not-comparable {sorted(SHARED_NON_COMPARABLE_PARTS)} = "
          f"{v.excluded_shared_non_comparable}")
    if v.gt_asymmetries:
        print(f"    {len(v.gt_asymmetries)} GROUND-TRUTH asymmetr"
              f"{'y' if len(v.gt_asymmetries) == 1 else 'ies'} (the corpus itself differs: "
              f"surface recorded in a comparable part of one format only)")
        for doc, type_, surface, side in v.gt_asymmetries:
            print(f"      GT {doc}: type={type_} surface={surface!r} comparable_in={side}_only")
    else:
        print("    0 ground-truth asymmetries (both formats' comparable parts hold the "
              "same surfaces)")
    if v.asymmetries:
        print(f"    {len(v.asymmetries)} OUTPUT asymmetr"
              f"{'y' if len(v.asymmetries) == 1 else 'ies'} (present in both ground truths, "
              f"removed from one output only — detection-or-redaction, see docstring)")
        for doc, type_, surface, dr, pr in v.asymmetries:
            print(f"      OUT {doc}: type={type_} surface={surface!r} "
                  f"redacted_in_docx={dr} redacted_in_pdf={pr}")
    else:
        print("    0 output asymmetries")
    print(f"    set aside (opaque-surface matches below eval/leak_gate.py's attributability "
          f"rule, NOT counted as surviving): {len(v.set_aside)} match(es)")
    for doc, type_, surface, fmt, parts in v.set_aside:
        print(f"      set-aside {doc}.{fmt}: type={type_} surface={surface!r} in {parts}")


def run_gate(corpus_dir: Path = CORPUS_DIR, limit: int | None = None) -> int:
    """``limit`` caps POPULATION B, and exists for one caller: the suite's smoke test, which
    asks whether the real author -> redact -> extract -> compare path runs end to end. Two pairs
    answer that as well as seventy, and seventy cost 75 seconds on every full-suite run.

    IT IS NOT A KNOB FOR MAKING THE GATE PASS. Running the gate as a gate -- ``python -m
    eval.cross_format_gate`` -- takes no limit and grades every pair, and the printed header
    says how many were compared so a truncated run cannot be mistaken for a full one."""
    stems = corpus_stems(corpus_dir)
    if limit is not None:
        stems = stems[:limit]
    if not stems:
        print(f"no docx/pdf corpus pairs at {corpus_dir} — regenerate it first:")
        print("  python -m corpus.generate --n 60 --out data/synthetic --seed 42 "
              "--formats docx,pdf")
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        authored = measure([_author_pair(i, out) for i in range(N_FIXTURES)])
        corpus = measure([_redact_corpus_pair(stem, d, p, out) for stem, d, p in stems])

    print("cross-format consistency gate — TWO populations, graded separately")
    print("comparison unit: (type, surface) string, per document, restricted to "
          f"surface_part in {sorted(COMPARABLE_PARTS)}; part tables imported from "
          "corpus/builders_plan.py (single source of truth)")
    print(f"  docx-only parts: {sorted(DOCX_ONLY_PARTS)}")
    print(f"  pdf-only parts:  {sorted(PDF_ONLY_PARTS)}")
    print()
    _report("A", "authored controls (hand-built matched fixtures, NBSP + split-run traps "
                 "placed every run)", authored)
    print()
    _report("B", f"real corpus {corpus_dir} (one logical document rendered to both formats "
                 "since QUESTIONS.md Q14, 2026-09-17)", corpus)

    total = _merge(authored, corpus)
    print()
    print(f"TOTAL: {total.pairs} pair(s), {total.checked} comparable surface(s) checked, "
          f"{len(total.gt_asymmetries)} ground-truth asymmetr"
          f"{'y' if len(total.gt_asymmetries) == 1 else 'ies'}, "
          f"{len(total.asymmetries)} output asymmetr"
          f"{'y' if len(total.asymmetries) == 1 else 'ies'}")
    print()
    print("VERDICT:", "FAIL" if total.failed else "PASS")
    return 1 if total.failed else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return run_gate()


if __name__ == "__main__":
    sys.exit(main())
