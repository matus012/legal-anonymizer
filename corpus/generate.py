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

from .docx_builder import DocxBuilder
from .groundtruth import Recorder
from .names.declension import NameBank
from .pdf_builder import PdfBuilder
from .templates import DOC_TYPES, TEMPLATES


def _emit(doc_type: str, index: int, fmt: str, seed: int, out: Path, bank: NameBank,
          *, image_only: bool = False) -> Path:
    rng = random.Random(seed)
    ext = "pdf" if fmt == "pdf" else "docx"
    stem = ("scan_image_only" if image_only else doc_type) + f"_{index:03d}"
    fname = f"{stem}.{ext}"
    rec = Recorder(fname, doc_type, seed)
    if fmt == "docx":
        builder = DocxBuilder(rec, rng)
    else:
        builder = PdfBuilder(rec, image_only=image_only)
    TEMPLATES[doc_type](builder, rng, bank, is_docx=(fmt == "docx"))
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
        for f_idx, fmt in enumerate(formats):
            doc_seed = seed * 1000 + i * 10 + f_idx
            written.append(_emit(doc_type, i, fmt, doc_seed, out, bank))
    # one image-only PDF fixture the app must refuse (§3)
    if "pdf" in formats:
        written.append(_emit("zaloba", 0, "pdf", seed * 1000 + 99999, out, bank, image_only=True))
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
