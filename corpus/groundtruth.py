"""Ground-truth schema + recorder (context.md §7, §8).

Ground truth is written **per output file** because failure modes are format-specific
(tracked changes / split runs are DOCX-only; XMP / form fields are PDF-only), so a shared
GT would misreport locations. The recorder is shared by the DOCX and PDF builders; each
builder stamps the correct ``surface_part`` as it places text.

Three-state decision (context.md revision to §7):
* valid identifier / real name        → auto_redact=True,  should_flag=False
* checksum-invalid but PII-shaped      → auto_redact=False, should_flag=True
* innocuous decoy number              → auto_redact=False, should_flag=False
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class PiiSpec:
    """One PII occurrence to place in a document and record in ground truth."""
    surface: str
    type: str
    entity_id: str | None = None
    grammatical_case: str | None = None
    valid_checksum: bool | None = None
    auto_redact: bool = True
    should_flag: bool = False


@dataclass
class Entity:
    entity_id: str
    canonical: str
    category: str
    variants: list[str] = field(default_factory=list)


class Recorder:
    """Accumulates entities + PII occurrences for a single output file."""

    def __init__(self, source_file: str, doc_type: str, seed: int):
        self.source_file = source_file
        self.doc_type = doc_type
        self.seed = seed
        self.text_layer = True
        self.must_be_refused = False
        self._entities: dict[str, Entity] = {}
        self._pii: list[dict] = []
        self._counter = 0

    # -- entities -----------------------------------------------------------------
    def entity(self, entity_id: str, canonical: str, category: str, variants: list[str]):
        self._entities[entity_id] = Entity(entity_id, canonical, category, variants)

    # -- pii ----------------------------------------------------------------------
    def record(
        self, spec: PiiSpec, *, part: str, detail: dict | None = None, surface: str | None = None
    ) -> str:
        """Record one occurrence.

        ``surface`` overrides ``spec.surface`` when the text as it is *extractable from the
        file* differs from the authored form (e.g. the PDF text layer, where PyMuPDF renders
        a hyphen as U+00AD). Ground truth must equal what an extractor sees, or the leak test
        greps for a string that is not there and every multi-word surface silently passes.
        """
        self._counter += 1
        pid = f"pii_{self._counter:04d}"
        entry = {
            "id": pid,
            "surface": spec.surface if surface is None else surface,
            "type": spec.type,
            "auto_redact": spec.auto_redact,
            "should_flag": spec.should_flag,
            "location": {"surface_part": part, "detail": detail or {}},
        }
        if spec.entity_id is not None:
            entry["entity_id"] = spec.entity_id
        if spec.grammatical_case is not None:
            entry["grammatical_case"] = spec.grammatical_case
        if spec.valid_checksum is not None:
            entry["valid_checksum"] = spec.valid_checksum
        self._pii.append(entry)
        return pid

    # -- serialisation ------------------------------------------------------------
    def _validate(self) -> None:
        """Hard-fail if a decoy surface EQUALS a real (auto_redact or should_flag) surface in
        this same document (context.md rejection round 8): eval.leak's exclusion is keyed on
        exact span containment, so a decoy string identical to a real PII surface would blind
        the leak gate to every occurrence of that string — a corpus mistake, not a redactor
        failure, must never silently pass as one."""
        decoy_surfaces = {
            p["surface"] for p in self._pii if not p["auto_redact"] and not p["should_flag"]
        }
        real_surfaces = {
            p["surface"] for p in self._pii if p["auto_redact"] or p["should_flag"]
        }
        collisions = decoy_surfaces & real_surfaces
        if collisions:
            raise ValueError(
                f"{self.source_file}: decoy surface(s) equal a real auto_redact/should_flag "
                f"surface in the same document: {sorted(collisions)!r}"
            )

    def to_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "doc_type": self.doc_type,
            "seed": self.seed,
            "text_layer": self.text_layer,
            "must_be_refused": self.must_be_refused,
            "entities": [asdict(e) for e in self._entities.values()],
            "pii": self._pii,
        }

    def write(self, path: Path) -> None:
        self._validate()
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
