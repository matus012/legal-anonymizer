"""The ONE definition of "what text does this PDF actually contain" (red-team round 6, R6-05/R6-06).

WHY THIS MODULE EXISTS. ``eval/extract.py`` has always widened every CropBox to its MediaBox
and dropped ``/OCProperties`` before reading a PDF's text layer, because MuPDF's structured-text
device clips to the page box and honours optional-content visibility: text outside the CropBox
or inside an OFF layer is returned by NOTHING, while any PDF tool still recovers it. The writer
did not do either, so ``writer/pdf_body.py`` ran ``detect()`` over a DIFFERENT DOCUMENT from the
one the leak gate grades -- text on an off layer (R6-05) and text cropped away by Acrobat's
"Crop Pages" (R6-06) shipped verbatim, on ``text_layer``, the strictest surface there is.

Two copies of that logic would reproduce the root cause the first time one of them was edited,
so there is exactly one, here, and both the writer and the extractor call it. It lives in
``writer/`` rather than in ``eval/`` because the dependency direction in this project already
runs eval -> writer (``eval/leak_gate.py`` and ``eval/cross_format_gate.py`` import
``writer.pdf_body``); the reverse would make the shipping application depend on its own test
harness.

WHY THE WRITER PUTS THE PAGE BACK (``rehide``) AND THE EXTRACTOR DOES NOT. The extractor mutates
a throw-away in-memory document and never writes it. The writer SAVES what it mutated, so
leaving the view open would ship a different-looking document than the lawyer handed in: an
un-cropped letterhead band returning to the page, and every "off" layer -- an attorney's own
margin notes -- becoming visible. The PII on those planes is destroyed while they are open;
putting the boxes and the layer configuration back afterwards is what keeps that a REDACTION
rather than an unrequested edit of the document.
"""
from __future__ import annotations

from typing import NamedTuple

import fitz


class HiddenView(NamedTuple):
    """What ``unhide`` changed, and everything ``rehide`` needs to undo it.

    ``ocproperties`` is the catalogue's original ``/OCProperties`` value as PDF source (or None
    when the document had none); ``cropboxes`` holds (page number, original CropBox) for every
    page whose box was widened -- pages already at their MediaBox are absent, so restoring is a
    no-op for the 71 corpus PDFs and the demo.
    """
    ocproperties: str | None
    cropboxes: tuple[tuple[int, fitz.Rect], ...]


def unhide(doc: "fitz.Document") -> HiddenView:
    """Make text that MuPDF's text device would skip visible to ``get_text()``.

    Two mechanisms hide text from extraction while leaving it fully recoverable by any other
    PDF tool -- i.e. they are leaks that the gate would score as clean:

    * **CropBox** -- the structured-text device clips to the page rect, which is the CropBox.
      Text drawn outside it (trivially restored by resetting the box in any PDF editor) is
      returned by nothing. Widening every CropBox to its MediaBox recovers it.
    * **Optional content (layers)** -- text inside an OCG whose default state is OFF is not
      emitted. Dropping ``/OCProperties`` from the catalogue makes MuPDF ignore the
      visibility configuration and emit everything. (``set_layer``/``set_layer_ui_config``
      were both tried first: ``set_layer(-1, on=[...])`` does not change what ``get_text()``
      returns, and the ui-config call only TOGGLES, so it would hide an ON layer just as
      often as it reveals an OFF one.)

    This mutates the in-memory document only. A caller that SAVES the document afterwards must
    pass the returned ``HiddenView`` to ``rehide`` first; a caller that only reads (the
    extractor) can discard it.

    The try/except arms are production behaviour, not defensive scaffolding: a malformed page
    box or a catalogue MuPDF will not let us edit must cost the caller that one plane, never the
    other five surfaces and never the document.
    """
    ocproperties: str | None = None
    try:
        kind, value = doc.xref_get_key(doc.pdf_catalog(), "OCProperties")
        if kind != "null":
            ocproperties = value
        doc.xref_set_key(doc.pdf_catalog(), "OCProperties", "null")
    except Exception:  # not a PDF catalogue we can edit; the raw-bytes surface still applies
        pass
    boxes: list[tuple[int, fitz.Rect]] = []
    for page in doc:
        try:
            if page.cropbox != page.mediabox:
                boxes.append((page.number, fitz.Rect(page.cropbox)))
                page.set_cropbox(page.mediabox)
        except Exception:  # a malformed box must not cost us the other 5 surfaces
            pass
    return HiddenView(ocproperties, tuple(boxes))


def rehide(doc: "fitz.Document", view: HiddenView) -> None:
    """Undo ``unhide`` on ``doc``: put the CropBoxes and the ``/OCProperties`` configuration back.

    Called by the writer immediately before the save, so the redacted file has the same page
    geometry and the same layer visibility as the input. Nothing is restored that ``unhide``
    did not change, so this is a no-op on a document with no layers and no crop.
    """
    for number, rect in view.cropboxes:
        try:
            doc[number].set_cropbox(rect)
        except Exception:
            pass
    if view.ocproperties is not None:
        try:
            doc.xref_set_key(doc.pdf_catalog(), "OCProperties", view.ocproperties)
        except Exception:
            pass
