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
    zmluva_v11,
)

TEMPLATES = {
    "kupna_zmluva": kupna_zmluva.build,
    "navrh_vklad": navrh_vklad.build,
    "zaloba": zaloba.build,
    "vypis_lv": vypis_lv.build,
    "splnomocnenie": splnomocnenie.build,
    "vypis_orsr": vypis_orsr.build,
    # v1.1 integration doc type: seeds every type added in the v1.1 sprint (addresses,
    # identity documents, bank/office references) into real .docx/.pdf so the leak gate and
    # per-type recall actually cover them. Before it existed those sixteen types had no
    # ground-truth occurrence anywhere in the corpus, so their recall scored None — which
    # reads as "fine" rather than as "never tested".
    "zmluva_v11": zmluva_v11.build,
}

DOC_TYPES = tuple(TEMPLATES)
