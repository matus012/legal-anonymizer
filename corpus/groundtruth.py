"""Ground-truth schema + recorder (context.md §7, §8).

Ground truth is written **per output file** because failure modes are format-specific
(tracked changes / split runs are DOCX-only; XMP / form fields are PDF-only), so a shared
GT would misreport locations. The recorder is shared by the DOCX and PDF builders; each
builder stamps the correct ``surface_part`` as it places text.

Three-state decision (v1.1, CONTRACTS_v11.md §7 — the middle row CHANGED):
* valid identifier / real name        → auto_redact=True,  should_flag=False, checksum="valid"/"n/a"
* checksum-invalid but PII-shaped      → auto_redact=True,  should_flag=False, checksum="invalid"
* innocuous decoy number              → auto_redact=False, should_flag=False, checksum="n/a"

The middle row moved from the review bucket into the auto bucket in v1.1 (policy A1): the
checksum is now a TAG, not a filter. A mistyped IČO is still an IČO, and leaving it
un-redacted because one digit is wrong is the exact failure this tool exists to prevent
(context.md §6, recall over precision). Ground truth has to move with the policy, or
per-type recall would keep scoring those surfaces as "correctly left alone".

``should_flag`` is NOT retired: it still marks anything that legitimately belongs in the
review bucket (the Phase C bare-name heuristic, and every identifier when the user turns on
``strict_checksums``). It is simply empty for identifier types under the default config.
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
    # v1.1 (CONTRACTS_v11.md §7): "valid" | "invalid" | "n/a". Left at the default and
    # DERIVED from valid_checksum by Recorder.record when the caller set that instead, so
    # the dozens of existing PiiSpec(..., valid_checksum=True) call sites keep working.
    checksum: str = "n/a"


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
        # Derive the v1.1 tag from valid_checksum when the caller did not set it explicitly.
        checksum = spec.checksum
        if checksum == "n/a" and spec.valid_checksum is not None:
            checksum = "valid" if spec.valid_checksum else "invalid"
        entry["checksum"] = checksum
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
