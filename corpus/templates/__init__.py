"""Document-type templates (context.md §7).

Each template populates a builder (DOCX or PDF) with doc-type-flavoured body text plus the
shared seeded failure modes. ``TEMPLATES`` maps the six required doc types to build fns.
"""
from __future__ import annotations

from . import (
    kupna_zmluva,
    navrh_vklad,
    zaloba,
    vypis_lv,
    splnomocnenie,
    vypis_orsr,
)

TEMPLATES = {
    "kupna_zmluva": kupna_zmluva.build,
    "navrh_vklad": navrh_vklad.build,
    "zaloba": zaloba.build,
    "vypis_lv": vypis_lv.build,
    "splnomocnenie": splnomocnenie.build,
    "vypis_orsr": vypis_orsr.build,
}

DOC_TYPES = tuple(TEMPLATES)
