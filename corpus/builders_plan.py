"""Format-neutral document CONTENT PLAN (QUESTIONS.md Q14).

Before this module existed, ``corpus/generate.py::_emit`` ran the template ONCE PER FORMAT
with a per-format seed (``seed*1000 + i*10 + f_idx``) and a per-format ``is_docx`` branch.
Three separate mechanisms made ``kupna_zmluva_000.docx`` and ``kupna_zmluva_000.pdf``
different documents rather than one document in two formats:

1. different seeds -> different people, identifiers and addresses from the first draw on;
2. ``DocxBuilder`` drew its split-run decisions from the SAME ``random.Random`` as the
   content, so even one shared seed would have desynchronised the two streams;
3. the ``is_docx`` branches in the templates consumed DIFFERENT numbers of RNG draws, so
   everything authored after a branch diverged too.

The fix is this module. A :class:`PlanBuilder` exposes the union of both builders' APIs but
renders nothing: it records the ordered list of calls a template makes. The template runs
ONCE, against ONE content RNG, with no format branch at all — both formats' hiding places
are seeded unconditionally. Each renderer then replays that one plan and DROPS the ops its
format cannot express (a DOCX has no PDF annotation; a PDF has no header, footer, footnote,
endnote, comment or textbox). ``DocxBuilder`` is handed a SEPARATE layout RNG by
``generate.py``, so its split-run draws can no longer perturb the content stream.

The residual differences between the two ``.gt.json`` files are therefore exactly the
format-specific surfaces, and nothing else — which is what ``tools/paired_gt_report.py``
asserts.
"""
from __future__ import annotations

from typing import Any

from .groundtruth import Recorder

# Every builder call a template may make, mapped to the formats that can render it.
# A format not listed DROPS the op; that drop is the only legitimate source of a
# ground-truth difference between the two renderings of one plan.
_SHARED = frozenset({"docx", "pdf"})
_DOCX = frozenset({"docx"})
_PDF = frozenset({"pdf"})

OPS: dict[str, frozenset[str]] = {
    # -- shared body content ---------------------------------------------------------
    "heading": _SHARED,
    "paragraph": _SHARED,
    "table": _SHARED,
    # A split-run surface is a DOCX storage trap, not different CONTENT: the PDF renders
    # the identical sentence as an ordinary paragraph, so the surface stays common.
    "split_run_paragraph": _SHARED,
    # -- DOCX-only surfaces ----------------------------------------------------------
    "header": _DOCX,
    "footer": _DOCX,
    "footnote": _DOCX,
    "endnote": _DOCX,
    "comment": _DOCX,
    "textbox": _DOCX,
    "tracked_change": _DOCX,
    # DocxBuilder.set_metadata takes (author, Company); PdfBuilder.set_metadata takes
    # (author, dc:creator). Two different calls, so the plan keeps them apart by name.
    "set_metadata_docx": _DOCX,
    # -- PDF-only surfaces -----------------------------------------------------------
    "annotation": _PDF,
    "form_field": _PDF,
    "attachment": _PDF,
    "set_metadata_pdf": _PDF,
}

# Ground-truth ``surface_part`` values a format cannot produce at all. Used by the paired-GT
# report to classify every surface that appears in only one of the two renderings.
DOCX_ONLY_PARTS = frozenset(
    {"header", "footer", "footnote", "endnote", "comment", "textbox",
     "tracked_change_ins", "tracked_change_del", "metadata_app"}
)
PDF_ONLY_PARTS = frozenset({"annotation", "form_field", "attachment", "xmp"})


class _PlanRecorder:
    """Stands in for :class:`Recorder` while the plan is being authored.

    Templates register entities through ``b.rec.entity(...)`` before any text is placed.
    The plan captures those calls and replays them into each format's real recorder, so both
    ``.gt.json`` files carry the identical entity table.
    """

    def __init__(self) -> None:
        self.entities: list[tuple] = []

    def entity(self, entity_id: str, canonical: str, category: str, variants: list[str]) -> None:
        self.entities.append((entity_id, canonical, category, variants))


class PlanBuilder:
    """Records a template's builder calls instead of rendering them."""

    def __init__(self) -> None:
        self.rec = _PlanRecorder()
        self.ops: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        if name not in OPS:
            raise AttributeError(
                f"template called builder op {name!r}, which corpus/builders_plan.py does not "
                f"know; add it to OPS with the formats that can render it"
            )

        def record(*args: Any, **kwargs: Any) -> None:
            self.ops.append((name, args, kwargs))

        return record

    # -- rendering ---------------------------------------------------------------------
    def render(self, builder, fmt: str, rec: Recorder) -> None:
        """Replay this plan into one concrete builder, dropping ops ``fmt`` cannot express."""
        for entity_id, canonical, category, variants in self.rec.entities:
            rec.entity(entity_id, canonical, category, variants)
        apply = _APPLY[fmt]
        for name, args, kwargs in self.ops:
            if fmt in OPS[name]:
                apply(builder, name, args, kwargs)


def _apply_docx(builder, name: str, args: tuple, kwargs: dict) -> None:
    if name == "set_metadata_docx":
        builder.set_metadata(*args, **kwargs)
    else:
        getattr(builder, name)(*args, **kwargs)


def _apply_pdf(builder, name: str, args: tuple, kwargs: dict) -> None:
    if name == "set_metadata_pdf":
        builder.set_metadata(*args, **kwargs)
    elif name == "heading":
        builder.heading(args[0])  # PdfBuilder.heading takes no level
    elif name == "split_run_paragraph":
        prefix, spec, suffix = args[:3]
        builder.paragraph([prefix, spec, suffix])
    else:
        getattr(builder, name)(*args, **kwargs)


_APPLY = {"docx": _apply_docx, "pdf": _apply_pdf}
