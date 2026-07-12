"""Baseline "redactors" that grade the harness itself (context.md §8, steps 4 & 5).

Neither is a real detector — they exist so the test suite can prove the harness is not
lying in either direction:

* :func:`null_redactor` copies the input unchanged. The harness MUST report massive leaks
  and ~0%% recall. A harness that passes this is broken.
* :func:`scorch_redactor` destroys every character (emits a valid but empty file). The
  harness MUST report zero leaks, 100%% recall, and terrible precision (decoys destroyed).
  A harness that reports success by finding nothing is caught here.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import docx
import fitz


def null_redactor(src: Path, dst: Path) -> None:
    """No-op: copy the file byte-for-byte. Every PII surface survives."""
    shutil.copyfile(src, dst)


def scorch_redactor(src: Path, dst: Path) -> None:
    """Destroy everything: emit a valid, empty file of the same format. No text, no metadata,
    so no surface — auto, flag, or decoy — survives, and the file still opens cleanly."""
    suffix = src.suffix.lower()
    if suffix == ".docx":
        docx.Document().save(str(dst))
    elif suffix == ".pdf":
        doc = fitz.open()
        doc.new_page()
        doc.save(str(dst))
        doc.close()
    else:
        raise ValueError(f"unsupported file type: {src.suffix!r} ({src.name})")
