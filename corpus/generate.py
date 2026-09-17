"""Corpus generator CLI (context.md §7).

Emits N logical Slovak legal documents distributed across the six doc types, each rendered
in the requested formats (DOCX and/or PDF), plus one image-only (no-text-layer) PDF fixture.
Every file gets an exact per-file ground-truth JSON alongside it. Fully deterministic from
``--seed`` so the corpus is reproducible and never needs to live in git.

    python -m corpus.generate --n 60 --out data/synthetic --seed 42 --formats docx,pdf
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

from .builders_plan import PlanBuilder
from .docx_builder import DocxBuilder
from .groundtruth import Recorder
from .names.declension import NameBank
from .pdf_builder import PdfBuilder
from .templates import DOC_TYPES, TEMPLATES

# DocxBuilder's split-run decisions are LAYOUT, not content. Q14: it used to draw them from
# the same Random as the template, so the content stream advanced by a format-specific amount
# and the two renderings stopped being the same document. It now gets its own stream, derived
# from the document seed so the corpus stays reproducible.
_LAYOUT_SEED_OFFSET = 500_000


def _plan(doc_type: str, seed: int, bank: NameBank) -> PlanBuilder:
    """Author the document CONTENT PLAN once per (doc_type, index), from ONE content RNG."""
    plan = PlanBuilder()
    TEMPLATES[doc_type](plan, random.Random(seed), bank)
    return plan


def _emit(plan: PlanBuilder, doc_type: str, index: int, fmt: str, seed: int, out: Path,
          *, image_only: bool = False) -> Path:
    ext = "pdf" if fmt == "pdf" else "docx"
    stem = ("scan_image_only" if image_only else doc_type) + f"_{index:03d}"
    fname = f"{stem}.{ext}"
    rec = Recorder(fname, doc_type, seed)
    if fmt == "docx":
        builder = DocxBuilder(rec, random.Random(seed + _LAYOUT_SEED_OFFSET))
    else:
        builder = PdfBuilder(rec, image_only=image_only)
    plan.render(builder, fmt, rec)
    path = out / fname
    builder.save(path)
    rec.write(out / f"{fname}.gt.json")
    return path


def generate(n: int, out: Path, seed: int, formats: list[str]) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    bank = NameBank.load()
    written: list[Path] = []
    for i in range(n):
        doc_type = DOC_TYPES[i % len(DOC_TYPES)]
        # ONE seed and ONE plan per logical document; every requested format renders that same
        # plan, so .docx and .pdf of index i are the same document in two formats (Q14).
        doc_seed = seed * 1000 + i * 10
        plan = _plan(doc_type, doc_seed, bank)
        for fmt in formats:
            written.append(_emit(plan, doc_type, i, fmt, doc_seed, out))
    # one image-only PDF fixture the app must refuse (§3)
    if "pdf" in formats:
        img_seed = seed * 1000 + 99999
        written.append(
            _emit(_plan("zaloba", img_seed, bank), "zaloba", 0, "pdf", img_seed, out,
                  image_only=True)
        )
    return written


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Synthetic Slovak legal corpus generator (§7)")
    ap.add_argument("--n", type=int, default=60, help="number of logical documents")
    ap.add_argument("--out", type=Path, default=Path("data/synthetic"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--formats", default="docx,pdf", help="comma-separated: docx,pdf")
    args = ap.parse_args(argv)

    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    bad = set(formats) - {"docx", "pdf"}
    if bad:
        ap.error(f"unknown format(s): {', '.join(sorted(bad))}")

    written = generate(args.n, args.out, args.seed, formats)
    print(f"Generated {len(written)} files + ground truth in {args.out}")


if __name__ == "__main__":
    main()
