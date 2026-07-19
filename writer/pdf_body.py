"""Phase 5 P1 (context.md): detect whether a PDF carries a text layer and refuse to redact it
when it does not (scanned/image-only), rather than silently producing an unredacted copy.

A PDF has no text layer when every page's extracted text is empty -- get_text("text") returns
"" for a purely-image page (verified against data/synthetic/scan_image_only_000.pdf). Redacting
such a PDF by text-span matching would be unsafe (nothing to match against), so redact_pdf()
raises NoTextLayerError instead of writing a false-safe copy. Real body redaction lands in P2;
for now a text-layer PDF also raises (NotImplementedError) rather than writing partial output.
"""
from __future__ import annotations

import fitz


class NoTextLayerError(Exception):
    pass


def has_text_layer(doc: "fitz.Document") -> bool:
    return any(page.get_text("text").strip() for page in doc)


def redact_pdf(in_path: str, out_path: str, known_entities: list[str] | None = None) -> str:
    doc = fitz.open(in_path)
    if not has_text_layer(doc):
        doc.close()
        raise NoTextLayerError(
            f"PDF has no text layer (scanned/image-only), cannot redact safely: {in_path}"
        )
    doc.close()
    raise NotImplementedError("PDF body redaction lands in P2")
