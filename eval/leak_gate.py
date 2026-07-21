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

Excluded by design (Class A): OBEC / KATASTER / ORG — gazetteer types deferred to v2,
GT-only in v1, genuinely undetectable rather than leaked-by-bug.

This module may import corpus/eval/writer but must NEVER import detect/ — the gate
must exercise detection only through the writers, exactly as production does.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from eval.extract import extract
from eval.leak import Leak, find_leaks
from writer.docx_body import redact_docx_body
from writer.pdf_body import redact_pdf

CLASS_A_TYPES = {"OBEC", "KATASTER", "ORG"}
_SCRUB_SURFACES = {"form_fields", "attachments", "info_metadata", "xmp", "annotations"}


def _classify(leak: Leak) -> str:
    if "text_layer" in leak.found_in:
        return "text_layer"
    if set(leak.found_in) <= _SCRUB_SURFACES:
        return "scrub"
    return "other"


def run_gate(corpus_dir: Path) -> int:
    files = sorted(
        p
        for p in corpus_dir.glob("*")
        if p.suffix in {".docx", ".pdf"} and "scan_image_only" not in p.name
    )
    if not files:
        print(f"no corpus at {corpus_dir} — regenerate it first:")
        print("  python -m corpus.generate --n 60 --out data/synthetic --seed 42 --formats docx,pdf")
        return 2

    counts = {"text_layer": 0, "scrub": 0, "other": 0}
    failing: list[tuple[str, Leak]] = []
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
            for leak in find_leaks(gt, extract(str(out))):
                if leak.type in CLASS_A_TYPES:
                    continue
                counts[_classify(leak)] += 1
                failing.append((src.name, leak))

    print(f"redacted: {n_docx} docx + {n_pdf} pdf")
    print(
        f"leaks: text_layer={counts['text_layer']} "
        f"scrub={counts['scrub']} other={counts['other']} (Class A excluded)"
    )
    for name, leak in failing:
        print(f"  LEAK {name}: type={leak.type} found_in={leak.found_in}")
    verdict_pass = not failing
    print("VERDICT:", "PASS" if verdict_pass else "FAIL")
    return 0 if verdict_pass else 1


def main() -> int:
    return run_gate(Path("data/synthetic"))


if __name__ == "__main__":
    sys.exit(main())
