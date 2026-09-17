"""Paired ground-truth report — is the .docx / .pdf pair ONE document in two formats? (Q14)

For every (doc_type, index) that exists in both formats, compare the two ``.gt.json`` files
by GROUND-TRUTH SURFACE STRING and classify every surface that appears in only one of them:

* ``docx-only surface`` — every occurrence lives in a ``surface_part`` a PDF has no
  equivalent for (header, footer, footnote, endnote, comment, textbox, tracked change,
  app.xml Company).
* ``pdf-only surface``  — every occurrence lives in a PDF-only part (annotation, form field,
  attachment, XMP).
* ``UNEXPLAINED``       — anything else. A surface that lives in a SHARED part (body, table
  cell, core metadata) in one format and is absent from the other means the two files are
  still not the same document. That is the finding this script exists to surface.

    .venv/Scripts/python.exe -m tools.paired_gt_report --corpus data/_paired_trial

Exit code 1 if any pair has an unexplained surface.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from corpus.builders_plan import DOCX_ONLY_PARTS, PDF_ONLY_PARTS

_STEM = re.compile(r"^(?P<stem>.+)\.(?P<ext>docx|pdf)\.gt\.json$")


def _load(path: Path) -> dict[str, set[tuple[str, str]]]:
    """surface -> {(type, surface_part)} for every recorded occurrence."""
    gt = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for p in gt["pii"]:
        out[p["surface"]].add((p["type"], p["location"]["surface_part"]))
    return out


def _classify(occurrences: set[tuple[str, str]], only_parts: frozenset[str]) -> bool:
    """True when EVERY occurrence of this surface lives in a part the other format lacks."""
    return all(part in only_parts for _, part in occurrences)


def compare(corpus: Path) -> tuple[list[dict], int]:
    pairs: dict[str, dict[str, Path]] = defaultdict(dict)
    for gt_path in sorted(corpus.glob("*.gt.json")):
        m = _STEM.match(gt_path.name)
        if m:
            pairs[m.group("stem")][m.group("ext")] = gt_path

    rows: list[dict] = []
    unexplained_total = 0
    for stem in sorted(pairs):
        got = pairs[stem]
        if set(got) != {"docx", "pdf"}:
            continue
        d, p = _load(got["docx"]), _load(got["pdf"])
        common = set(d) & set(p)
        docx_only = {s: d[s] for s in set(d) - set(p)}
        pdf_only = {s: p[s] for s in set(p) - set(d)}
        unexplained = (
            [(s, sorted(occ), "docx") for s, occ in sorted(docx_only.items())
             if not _classify(occ, DOCX_ONLY_PARTS)]
            + [(s, sorted(occ), "pdf") for s, occ in sorted(pdf_only.items())
               if not _classify(occ, PDF_ONLY_PARTS)]
        )
        unexplained_total += len(unexplained)
        rows.append({
            "stem": stem,
            "n_docx": len(d), "n_pdf": len(p), "n_common": len(common),
            "docx_only": docx_only, "pdf_only": pdf_only, "unexplained": unexplained,
        })
    return rows, unexplained_total


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--detail", default="", help="print the per-surface breakdown for this stem")
    args = ap.parse_args(argv)

    rows, unexplained_total = compare(args.corpus)
    if not rows:
        print(f"no docx/pdf ground-truth pairs found in {args.corpus}")
        return 1

    print(f"PAIRED GROUND TRUTH — {args.corpus}  ({len(rows)} pairs)")
    print(f"{'document':<26}{'docx':>6}{'pdf':>6}{'common':>8}{'dx-only':>9}{'pdf-only':>10}"
          f"{'UNEXPL':>8}")
    for r in rows:
        print(f"{r['stem']:<26}{r['n_docx']:>6}{r['n_pdf']:>6}{r['n_common']:>8}"
              f"{len(r['docx_only']):>9}{len(r['pdf_only']):>10}{len(r['unexplained']):>8}")

    for r in rows:
        if r["stem"] == args.detail:
            print(f"\n--- {r['stem']} : surfaces present in ONE format only ---")
            for label, d, cat in (("docx-only", r["docx_only"], "docx-only part (no PDF equiv.)"),
                                  ("pdf-only", r["pdf_only"], "pdf-only part (no DOCX equiv.)")):
                for s, occ in sorted(d.items()):
                    parts = sorted({part for _, part in occ})
                    types = sorted({t for t, _ in occ})
                    ok = _classify(occ, DOCX_ONLY_PARTS if label == "docx-only" else PDF_ONLY_PARTS)
                    print(f"  [{label}] {s!r} type={','.join(types)} part={','.join(parts)} "
                          f"-> {cat if ok else 'UNEXPLAINED'}")

    print(f"\nTOTAL unexplained surfaces across {len(rows)} pairs: {unexplained_total}")
    if unexplained_total:
        for r in rows:
            for s, occ, side in r["unexplained"]:
                print(f"  UNEXPLAINED {r['stem']} [{side}] {s!r} {sorted(occ)}")
        return 1
    print("OK — every one-sided surface is a genuine format-specific surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
