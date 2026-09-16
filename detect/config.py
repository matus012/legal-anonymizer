"""v1.1 detection configuration (CONTRACTS_v11.md §2).

Three user-facing toggles whose defaults reproduce the governing rule (context.md §6,
recall over precision). This module imports NOTHING from the project — it sits below
detect/core.py so any detector module can take a DetectConfig without a circular import.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectConfig:
    """Detection-time toggles. Defaults are the recall-first v1.1 policy.

    ``strict_checksums`` — False (default): a shape-valid identifier whose checksum FAILS is
    still auto-redacted and merely TAGGED ``checksum="invalid"`` (v1.1 policy A1: checksum is
    a tag, not a filter). True restores the v1 behaviour where such a surface is routed to
    the review bucket unticked. A law office that would rather re-tick a handful of mistyped
    IČOs than risk one un-redacted rodné číslo leaves this False.

    ``redact_all_dates`` — False (default): every date in the document is DETECTED, but only
    a date of birth (one standing near ``nar.`` / ``narodený`` / ``dátum narodenia`` /
    ``r.č.``) is auto-redacted; the rest stay, because destroying every contract date makes
    the document unreadable. True auto-redacts every detected date.
    """

    strict_checksums: bool = False
    redact_all_dates: bool = False


DEFAULT = DetectConfig()
