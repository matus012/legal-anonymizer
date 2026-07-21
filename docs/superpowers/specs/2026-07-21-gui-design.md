# Phase 6 GUI — design spec (approved 2026-07-21)

Desktop review-and-export GUI for the Slovak legal-document anonymizer. Approved by owner
this session; framework and plumbing decisions delegated to the reviewer loop.
Requirements source: context.md §2 (users), §3 (scope), §9 (flow), §10 (technical).

## Decisions (fixed)

- **Framework: PySide6** (6.11.1, installed). Native Windows look, checkable table rows,
  built-in drag-drop. Exe size irrelevant for a 6-lawyer office. LGPL fine for internal use.
- **Batch semantics:** known entities entered ONCE per batch; review is PER FILE
  (file sidebar) because labels and reports are per-document (one LabelMap per document).
- **Scan = the real writer run to a throwaway temp file.** The review model is harvested
  from the writer's own LabelMap side-channels. No second traversal implementation exists,
  so the review screen cannot disagree with export about what is found.
- **Export = the same writer re-run with a `decisions` parameter.** Detection is
  deterministic, so scan and export see identical candidates.
- **No mapping file. Originals never modified. Everything offline.** (context.md §3)

## Writer API extension (the only engine change)

New frozen dataclass `writer/decisions.py :: RedactionDecisions`:

```python
@dataclass(frozen=True)
class RedactionDecisions:
    extra_terms: tuple[str, ...] = ()      # free-text "redact this too" -> joins known_entities
    suppress_groups: frozenset = frozenset()  # group keys: auto candidates NOT to redact
    force_groups: frozenset = frozenset()     # group keys: low-confidence candidates TO redact
```

Group key = `(cand.type, labelmap.group_key(cand))` — reuses the existing grouping
identity from `writer/labelmap.py`; no new matching logic.

Both writers gain `decisions: RedactionDecisions | None = None` (keyword-only, default
None ⇒ byte-identical current behavior; the whole existing suite and `eval/leak_gate.py`
remain valid unmodified).

Semantics at the existing per-candidate branch in each writer:

- `cand.auto and key in suppress_groups` → NOT redacted; recorded via
  `record_low_confidence(location, cand.type, cand.surface)` so the report's
  `[LOW CONFIDENCE / NOT REDACTED]` section honestly records the human decision.
- `not cand.auto and key in force_groups` → redacted with a normal minted label
  (flows through `label_for` + `record_occurrence` like any auto candidate).
- `extra_terms` are appended to `known_entities` before `detect()` (declension-tolerant,
  over-match by design — context.md §5).

Context snippets for the review table: new side-channel
`LabelMap.contexts: dict[str, str]` (label → first-seen ±40-char snippet) via
`record_context(label, snippet)`; low-confidence snippets go to
`LabelMap.lc_contexts: list[str]`, append-aligned index-for-index with
`low_confidence` (same call site, same order — one snippet per recorded row).
`occurrences` / `low_confidence` shapes are UNTOUCHED (build_report unpacks them —
byte-stable reports).

## GUI structure (new `gui/` package; engine imports writer/, never detect/)

- `gui/model.py` — pure logic, no Qt: `ScanResult` / `ReviewRow` dataclasses; harvest
  function (writer temp-run → rows: type, display text, snippet, locations, count,
  bucket, group key); decisions assembly from checkbox state + free text. Fully
  unit-testable headless.
- `gui/worker.py` — QThread wrapper running scan/export per file sequentially; emits
  progress + per-file errors (`NoTextLayerError` → "scanned PDF, not supported v1";
  `RedactionIncompleteError` → "partially redacted — do not send"; both per context.md §3).
- `gui/app.py` — QApplication + QMainWindow + QStackedWidget, three pages:
  1. **Input** — drag-drop zone + Browse (multi-select .docx/.pdf), known-entities
     QPlainTextEdit ("one per line", prominently nudged, skippable), Scan.
  2. **Review** — file sidebar (per-file state); table `☑ | TYPE | text | snippet |
     locations | count`; auto rows pre-ticked, low-confidence rows unticked; free-text
     "redact this too" + Rescan; Export-all button.
  3. **Done** — per-file outcome list (written / refused / incomplete), output folder
     link, and the fixed sentence: outputs must be reviewed before sending anywhere.
- Outputs written next to sources: `<stem>_anon.docx|.pdf` + `<stem>_anon_report.txt`
  (writer derives report name). Temp scan outputs deleted immediately after harvest.
- Entry point: `python -m gui` (`gui/__main__.py`). No console window in the packaged exe
  (Phase 7: PyInstaller `--noconsole`).

## Error handling

Per-file isolation: one refused/failed file never blocks the batch; its row shows the
error and the rest proceed. Unexpected exceptions surface in a dialog with the filename.
The app never claims a document is clean (context.md §9 liability posture).

## Testing & gates

- RED→GREEN unit tests for RedactionDecisions plumbing in BOTH writers
  (suppress/force/extra_terms; hand-built fixtures, tests never import corpus/).
- **Suppression retention proof:** a suppressed group's surface MUST survive in the
  output (decoys-must-not-mask analogue) — asserted at unit level.
- `gui/model.py` harvest + decisions round-trip tested headless (no display).
- **`python -m eval.leak_gate` must PASS after every writer-touching round** (writer
  edits are add-only branches, but the gate is the law).
- End-to-end: launch app offscreen (`QT_QPA_PLATFORM=offscreen`) → scripted scan of a
  synthetic file → export → assert `_anon` + report files exist and open.
- Manual: owner double-clicks, scans, unticks a row, exports, reads the report.

## Out of scope (unchanged)

OCR/scans, signature/stamp removal, ML NER, non-docx/pdf formats, any network, gazetteer
(v2), per-occurrence review (grouping is by entity — fatigue trap otherwise, §9).
