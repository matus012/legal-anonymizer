"""Refusals the writers raise for a file they cannot open at all.

WHY THESE EXIST
--------------------------------------------------------------------------------------
``context.md`` §3 promises that a document the tool cannot process is REFUSED, with a message
the reviewer can act on. That promise was kept for a PDF with no text layer and, since
red-team round 3, for one whose text cannot be decoded or is shredded into single characters.
It was not kept for a file that cannot be OPENED.

Measured (red-team round 4, R4-X3): a ``.docx`` with a malformed ``.rels`` part raised
``lxml.etree.XMLSyntaxError: Couldn't find end of Start Tag broken line 1``; one that is not a
ZIP raised ``PackageNotFoundError``; a password-protected PDF raised
``ValueError: document closed or encrypted``; a truncated PDF raised ``FileDataError``.

The application does not crash on any of them — ``gui/worker.py`` isolates each file and the
review screen shows the exception's text. That is the problem: what it shows is a library
message written for a developer. It does not say what went wrong in terms the lawyer can act
on, and it does not say the thing they most need to know, which is **whether a file was
written**. Somebody reading "Couldn't find end of Start Tag" cannot tell whether there is now
a half-redacted document on disk.

So the writers convert these into named refusals with Slovak messages, raised BEFORE anything
is written, and the original exception is kept as ``__cause__`` for the bug report.
"""
from __future__ import annotations


class UnreadableDocumentError(Exception):
    """The input file could not be opened or parsed at all.

    Raised before any output exists, so a caller seeing this knows nothing was written.
    ``path`` is the file, ``detail`` the underlying library message — kept because it is what
    a maintainer needs, while the GUI shows the human sentence instead.
    """

    def __init__(self, path: str, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(
            f"document cannot be opened or is damaged, nothing was written: {path} ({detail})"
        )


class PasswordProtectedError(UnreadableDocumentError):
    """The input is encrypted and needs a password to open.

    A SUBCLASS, so any caller that already refuses an unreadable document refuses this one
    too. It is named separately because the remedy is completely different and completely
    within the lawyer's reach: open the file, enter the password, save an unprotected copy.
    The Slovak land registry issues password-protected PDFs, so this is ordinary, not exotic.
    """

    def __init__(self, path: str) -> None:
        super().__init__(path, "encrypted / password-protected")


class EmbeddedSubDocumentError(UnreadableDocumentError):
    """The .docx merges in a whole second document through ``<w:altChunk>``.

    A SUBCLASS, for the same reason as PasswordProtectedError: every caller that already
    refuses an unreadable document refuses this one unchanged, and the distinct type exists so
    the GUI can name the remedy, which is specific and within the lawyer's reach.

    WHAT AN ALTCHUNK IS. ``<w:altChunk r:id="..."/>`` is not content — it is a placeholder for
    an ENTIRE EXTERNAL DOCUMENT stored as its own part in the package (typically HTML, an
    ``.mht`` bundle, plain text, or a nested ``.docx``). Word parses that part and splices its
    content onto the page when the file is opened. It is how Word stores pasted HTML, how
    ``Insert > Object > Text from File`` stores an inserted file on several code paths, and
    what essentially every HTML-to-DOCX pipeline, mail-merge engine and DMS export emits.

    WHY A REFUSAL AND NOT A REDACTION (red-team round 5, R5-02). The part is not WordprocessingML
    and no pass in this writer can read it: the paragraph walk looks for ``w:p`` and an altChunk
    contains none, only a relationship id. Before this refusal existed the sub-document shipped
    BYTE-FOR-BYTE UNREDACTED while the report said the document was redacted -- the one failure
    mode this project treats as unacceptable, because the reviewer reads the report, not the ZIP.

    WHY NOT JUST DELETE THE PART. Dropping the element and its part would silently remove a
    merged-in annex from a filing, and the reviewer cannot see what is no longer there. This
    project refuses rather than half-redacts (see UnreadableTextLayerError,
    ShreddedTextLayerError and MojibakeTextLayerError in writer/pdf_body.py).

    WHY EVERY ALTCHUNK AND NOT ONLY THE ONES THAT LOOK LIKE THEY CARRY PII. "No PII was detected
    in a part we cannot properly parse" is precisely the reasoning that produced the
    undecodable-text and shredded-text leaks: a detector that never ran cleanly cannot license a
    clean verdict. Running detect() over bytes the writer has no way to rewrite would also buy
    nothing -- a hit could not be redacted either way.

    Carries ``parts`` (the package part names, in package order) so the message can name them.
    """

    def __init__(self, path: str, parts: list[str]) -> None:
        self.parts = list(parts)
        self.path = path
        self.detail = "w:altChunk -> " + ", ".join(self.parts)
        # Not super().__init__: the parent's sentence is about a damaged file, and this file is
        # not damaged. It is intact, readable by Word, and carries content this tool cannot
        # reach -- which needs its own sentence.
        Exception.__init__(
            self,
            f"document contains {len(self.parts)} embedded sub-document(s) that this tool "
            f"cannot redact, nothing was written: {path}. Word merges the content of "
            f"{', '.join(self.parts)} onto the page when the document is opened (it is stored "
            f"as a separate file inside the .docx, typically pasted HTML or an inserted file), "
            f"and this tool cannot read it, so it would have shipped unredacted. Remedy: open "
            f"the document in Word and re-save it as .docx (File > Save As) -- Word writes the "
            f"merged content out as ordinary document text -- then run the tool again."
        )
