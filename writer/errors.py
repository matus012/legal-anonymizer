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
