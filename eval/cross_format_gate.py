"""Cross-format consistency gate — Phase E, GATED (CONTRACTS_v11.md).

    python -m eval.cross_format_gate

The corpus generator is *supposed* to write the same logical document as both ``.docx`` and
``.pdf`` so the two outputs can be compared surface-for-surface. **They cannot be, as
``corpus/generate.py`` stands today** — see "FINDING" below. This module therefore builds its
own small, hand-authored fixture corpus of matched pairs instead of reading
``data/synthetic``, and states that substitution explicitly rather than silently reusing a
population that does not have the property the gate needs.

--------------------------------------------------------------------------------------
FINDING (reported, not fixed — out of scope for this round, see CONTRACTS_v11.md §11):
--------------------------------------------------------------------------------------
``corpus/generate.py::_emit`` derives each file's RNG seed as
``seed * 1000 + i * 10 + f_idx``, where ``f_idx`` is the position of "docx" / "pdf" in
``--formats``. For the same logical index ``i`` the docx (f_idx=0) and pdf (f_idx=1) are
therefore built from TWO DIFFERENT random streams, not one. Verified directly on
``data/synthetic/kupna_zmluva_000.{docx,pdf}.gt.json``: 53 vs 49 PII rows, and the surface
sets barely overlap (e.g. the docx's BANKOVY_UCET is ``311730-1655351121/1111``, the pdf's is
``616710-5280209847/0200`` — different people, different numbers, same template). So "the
same logical document in two formats" is not a real invariant of the shipped corpus today;
it only held for the hand-authored ``demo/`` fixture (``tools/make_demo.py``), which is
exactly where the NBSP/line-break leaks this gate is meant to catch were actually found. A
second, independent problem would make even fixing the seed derivation insufficient:
``corpus/docx_builder.DocxBuilder`` consumes the SAME ``random.Random`` instance for its
split-run decision (``_split_surface``) as the template uses for content (names, identifiers,
decoys) — interleaved, mid-document. Two builders seeded identically but making a different
number of internal draws (the PDF builder never makes a split-run decision) diverge in their
content draws the moment the first PiiSpec is placed, so re-deriving one shared seed for both
formats would STILL not reproduce identical content. Report this to the orchestrator before
the next round that touches ``corpus/generate.py`` or ``corpus/docx_builder.py``.

Until that is fixed, this gate authors its own fixtures directly from ``corpus.pii.*``
generators (the same ones ``corpus/templates/_common.py`` uses) and ``corpus.docx_builder`` /
``corpus.pdf_builder`` (the same builders ``corpus/generate.py`` uses) — content strings are
computed ONCE, before any builder touches a RNG, and the resulting literal ``PiiSpec``
objects are placed into BOTH builders verbatim. That is the only way to get two files that are
provably the same logical document under the current corpus code.

--------------------------------------------------------------------------------------
COMPARISON UNIT
--------------------------------------------------------------------------------------
Per document, per PII surface STRING (deduplicated, matching ``eval/mutation_gate.py`` and
``eval/leak_gate.py``'s convention). Scope: the ground truth's ``auto_redact`` class only —
"detected" here means "removed from the redacted output", the same predicate the leak gate
and ``eval/metrics.py`` use (:func:`eval.leak.surface_present`, negated). ``should_flag`` /
decoy surfaces are excluded from the comparison: they are not supposed to be redacted in
EITHER format, so a survive/survive pair carries no information about detector parity.

A surface only enters the comparison when its ground-truth ``location.surface_part`` is one
this module calls COMPARABLE — a part that has a real equivalent in both formats and is
placed with byte-identical content in both builders. Everything else is a NAMED, COUNTED
exclusion:

* ``DOCX_ONLY_PARTS`` — header, footer, footnote, endnote, comment, textbox, tracked-change
  ins/del, core/app metadata. No PDF equivalent exists (PDF has no footnotes, no tracked
  changes, no ``docProps/app.xml``).
* ``PDF_ONLY_PARTS`` — annotation, form_field, attachment, PDF ``metadata``/``xmp``. No DOCX
  equivalent (DOCX has no annotations, no AcroForm fields, no XMP packet).
* ``COMPARABLE_PARTS = {"body", "table_cell"}`` — ordinary flowed text. Both builders place
  the SAME literal ``PiiSpec`` surfaces into these parts for a given fixture, so a surface
  found here is genuinely comparable.

Gate: **zero unexplained asymmetries** on the comparable population — a surface removed from
one format's output and left standing in the other's, with the SAME literal input, is a real
per-format detection defect (an anchor phrase, a whitespace normalisation, an offset bug that
only one writer's paragraph-reconstruction triggers). If this fires on the current code it is
a FINDING, printed with the exact document/type/surface — it is not weakened to pass.

This module imports ``writer/`` (to redact) and ``eval/`` (to extract + judge), and
``corpus/docx_builder`` / ``corpus/pdf_builder`` / ``corpus/groundtruth`` / ``corpus/pii/*``
READ-ONLY, to build its own fixtures — never ``detect/`` directly (like ``eval/leak_gate.py``,
this gate's premise is end-to-end: it must exercise detection only through the writers).

Exit codes: 0 = PASS (zero unexplained asymmetries), 1 = FAIL.
"""
from __future__ import annotations

import random
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from corpus.docx_builder import DocxBuilder
from corpus.groundtruth import PiiSpec, Recorder
from corpus.pdf_builder import PdfBuilder
from corpus.pii import amounts, dates, dic, email, ic_dph, iban, ico, phone, registry_refs, rodne_cislo, url
from eval.extract import extract
from eval.leak import surface_present
from writer.docx_body import redact_docx_body
from writer.pdf_body import redact_pdf

COMPARABLE_PARTS = {"body", "table_cell"}
DOCX_ONLY_PARTS = {
    "header", "footer", "footnote", "endnote", "comment", "textbox",
    "tracked_change_ins", "tracked_change_del", "metadata_core", "metadata_app",
}
PDF_ONLY_PARTS = {"annotation", "form_field", "attachment", "metadata", "xmp"}
_KNOWN_PARTS = COMPARABLE_PARTS | DOCX_ONLY_PARTS | PDF_ONLY_PARTS

N_FIXTURES = 6          # matched pairs authored per run
_SEED_BASE = 90000


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


# --------------------------------------------------------------------------- measurement
@dataclass
class Verdict:
    checked: int = 0
    excluded_docx_only: int = 0
    excluded_pdf_only: int = 0
    excluded_unknown_part: int = 0
    asymmetries: list[tuple[str, str, str, bool, bool]] = field(default_factory=list)
    # (doc, type, surface, redacted_in_docx, redacted_in_pdf)


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


def judge_pair(name: str, docx_gt: dict, pdf_gt: dict, docx_text: str, pdf_text: str) -> Verdict:
    """The comparison for ONE matched pair, decoupled from file I/O so it is directly unit
    testable (tests/test_cross_format_gate.py) without redacting a real docx/pdf."""
    v = Verdict()
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

    docx_comp = _comparable_surfaces(docx_gt)
    pdf_comp = _comparable_surfaces(pdf_gt)
    common = set(docx_comp) & set(pdf_comp)
    # Surfaces authored as comparable in one format but not the other would themselves be
    # a fixture-authoring bug (this module builds them identically on purpose) — assert
    # rather than silently exclude, since here (unlike the real corpus) there's no reason
    # for it to happen.
    only_docx = set(docx_comp) - set(pdf_comp)
    only_pdf = set(pdf_comp) - set(docx_comp)
    if only_docx or only_pdf:
        raise AssertionError(
            f"{name}: comparable-part surfaces present in only one format "
            f"(fixture bug, not a product finding): docx_only={only_docx} pdf_only={only_pdf}"
        )

    decoys: list[str] = []
    for type_, surface in sorted(common):
        v.checked += 1
        docx_redacted = not surface_present(docx_text, surface, decoys)
        pdf_redacted = not surface_present(pdf_text, surface, decoys)
        if docx_redacted != pdf_redacted:
            v.asymmetries.append((name, type_, surface, docx_redacted, pdf_redacted))
    return v


def _merge(a: Verdict, b: Verdict) -> Verdict:
    return Verdict(
        checked=a.checked + b.checked,
        excluded_docx_only=a.excluded_docx_only + b.excluded_docx_only,
        excluded_pdf_only=a.excluded_pdf_only + b.excluded_pdf_only,
        asymmetries=a.asymmetries + b.asymmetries,
    )


def measure(pairs: list[Pair]) -> Verdict:
    v = Verdict()
    for pair in pairs:
        docx_res = extract(pair.docx_out)
        pdf_res = extract(pair.pdf_out)
        v = _merge(v, judge_pair(pair.name, pair.docx_gt, pair.pdf_gt,
                                  docx_res.full_text, pdf_res.full_text))
    return v


# --------------------------------------------------------------------------- reporting
def run_gate() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        pairs = [_author_pair(i, out) for i in range(N_FIXTURES)]
        verdict = measure(pairs)

    print(f"cross-format consistency gate: {len(pairs)} matched fixture pair(s), "
          f"{verdict.checked} comparable auto-redact surface(s) checked")
    print("comparison unit: (type, surface) string, per document, restricted to "
          f"surface_part in {sorted(COMPARABLE_PARTS)} — see module docstring for the FINDING "
          "that data/synthetic's real docx/pdf pairs are NOT the same logical document and "
          "cannot be used for this gate as-is")
    print(f"named exclusions, counted: docx-only parts {sorted(DOCX_ONLY_PARTS)} "
          f"= {verdict.excluded_docx_only} surface(s); "
          f"pdf-only parts {sorted(PDF_ONLY_PARTS)} = {verdict.excluded_pdf_only} surface(s)")

    print()
    if verdict.asymmetries:
        print(f"=== {len(verdict.asymmetries)} UNEXPLAINED ASYMMETR{'Y' if len(verdict.asymmetries) == 1 else 'IES'} ===")
        for doc, type_, surface, dr, pr in verdict.asymmetries:
            print(f"  {doc}: type={type_} surface={surface!r} "
                  f"redacted_in_docx={dr} redacted_in_pdf={pr}")
    else:
        print("=== 0 unexplained asymmetries ===")

    passed = not verdict.asymmetries
    print()
    print("VERDICT:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return run_gate()


if __name__ == "__main__":
    sys.exit(main())
