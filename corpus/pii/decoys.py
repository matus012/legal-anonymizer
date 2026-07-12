"""Innocuous decoy numbers — the precision bait (context.md revision to §7).

These are NOT PII: invoice numbers, page counts, order numbers, plain digit runs and
date/time stamps that superficially resemble identifiers. Ground truth records them with
``auto_redact=False, should_flag=False`` so the precision test can assert the detector
leaves them alone. They are deliberately NOT shaped like a valid RČ/IČO/IBAN.
"""
from __future__ import annotations

import random

# Kinds are labelled so ground truth can carry a meaningful ``type``.
KINDS = ("invoice_no", "page_count", "order_no", "article_no", "clause_ref", "time_stamp")


def generate(rng: random.Random, kind: str | None = None) -> tuple[str, str]:
    """Return ``(surface, kind)`` for a non-PII look-alike number."""
    kind = kind or rng.choice(KINDS)
    if kind == "invoice_no":
        return f"Faktúra č. {rng.randint(2018, 2025)}{rng.randint(1, 999):03d}", kind
    if kind == "page_count":
        n = rng.randint(2, 40)
        return f"Strana {rng.randint(1, n)} z {n}", kind
    if kind == "order_no":
        return f"Obj. č. {rng.randint(1, 999)}/{rng.randint(2018, 2025)}", kind
    if kind == "article_no":
        return f"čl. {rng.randint(1, 30)} ods. {rng.randint(1, 9)}", kind
    if kind == "clause_ref":
        return f"bod {rng.randint(1, 12)}.{rng.randint(1, 9)}", kind
    return f"{rng.randint(8, 18):02d}:{rng.randint(0, 59):02d} hod.", kind
