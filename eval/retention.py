"""§8.3 retention gate — the empty-file blind spot the leak/recall gates cannot see.

Leak (`eval.leak`) and recall (`eval.metrics`) only ask whether GT PII surfaces survive in
the output. A redactor that emits a valid, empty file scores zero leaks and 100%% recall on
every type — there is nothing left to leak — and both gates report PASS. This module scores
the complementary question: how much of the document's non-PII content is still there.

Unit: unicode word tokens (Slovak diacritics are word characters under ``\\w`` in Python's
``re``) of the ORIGINAL (pre-redaction) extracted CONTENT text. A token counts toward the
denominator only if it does NOT overlap any recorded ``auto_redact``/``should_flag`` PII span
(found by exact offset in the original text — not a text-rewrite). Each surviving denominator
token must be found in the REDACTED output's RAW, UNTOUCHED token multiset.

**The redacted side is never masked or rewritten.** Retention's denominator is non-PII
content; the redacted text is what we check that content's presence *against* — altering it
before counting would make retention blind to whatever the redactor actually did at that
exact spot, collapsing "PII genuinely removed" and "PII still sitting right there" into the
same score on retention's own axis (leak/recall already own that distinction; retention must
not silently re-derive it by rewriting the numerator's source). A prior version masked GT PII
surfaces out of both sides to paper over a token-boundary artifact — reverted; see below.

Why exclude by SPAN OVERLAP instead of masking the original text via search-and-replace: DOCX
paragraph/run text reconstructs with NO separator (context.md §10), so a PII surface can be
glued directly to non-PII text with zero whitespace (e.g. "...(chybné)81837624IBAN..." — the
IČO value fused to the next label word). Regex/string substitution on the flat text either
misses that occurrence (boundary-anchored) or corrupts unrelated content that happens to
contain the surface as a substring (plain replace), AND either way it fabricates a token
boundary in the ORIGINAL that may not exist in the (untouched) redacted text — the exact
defect this module was rejected for. Finding each surface by exact character offset and
simply excluding any token whose span overlaps a PII span sidesteps rewriting entirely: a
glued "mixed" token like "81837624IBAN" is dropped from the denominator outright (neither
counted as surviving nor lost) rather than being surgically split. Conservative, but never
wrong in either direction.

Metadata surfaces (``core_xml``/``app_xml``/``custom_xml`` for DOCX, ``info_metadata``/``xmp``
for PDF) are excluded from both sides. The extractor deliberately keeps these as raw XML /
dict-dump text so an attribute-embedded leak is still caught (see ``extract.py``) — but that
means structural boilerplate (tag and attribute names) is identical across any two freshly
generated files of the same format, no matter how much real content survived. Counting it
would let an empty file's own default metadata skeleton masquerade as "surviving content".
"""
from __future__ import annotations

import re
from collections import Counter

from .extract import S_APP, S_CORE, S_CUSTOM, S_INFO, S_XMP, ExtractResult

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_METADATA_SURFACES = {S_CORE, S_APP, S_CUSTOM, S_INFO, S_XMP}


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _content_text(res: ExtractResult) -> str:
    return "\n".join(text for name, text in res.by_surface.items() if name not in _METADATA_SURFACES)


def _pii_spans(text: str, surfaces: list[str]) -> list[tuple[int, int]]:
    """Every occurrence of every surface in ``text``, by exact character offset."""
    spans = []
    for s in surfaces:
        start = 0
        while True:
            idx = text.find(s, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(s)))
            start = idx + len(s)
    return spans


def _non_pii_tokens(text: str, gt: dict) -> list[str]:
    """Tokens of ``text`` whose span does not overlap any auto_redact/should_flag PII span.

    Decoys are deliberately excluded from the span list: a decoy is not PII (context.md §7's
    three-state decision — "innocuous decoy number") and must survive completely unchanged,
    so it is ordinary content for retention's purposes (and has its own dedicated gate,
    ``TypeMetrics.decoy_survival``, for whether it actually does survive).
    """
    surfaces = [pii["surface"] for pii in gt["pii"] if pii["auto_redact"] or pii["should_flag"]]
    spans = _pii_spans(text, surfaces)
    tokens = []
    for m in _TOKEN_RE.finditer(text):
        t_start, t_end = m.span()
        if not any(t_start < e and s < t_end for s, e in spans):
            tokens.append(m.group())
    return tokens


def score(gt: dict, original: ExtractResult, redacted: ExtractResult) -> tuple[int, int]:
    """Return ``(survived, total)`` non-PII content tokens for one document.

    ``redacted`` is tokenized RAW — never masked, never rewritten (see module docstring).
    """
    orig_tokens = _non_pii_tokens(_content_text(original), gt)
    redacted_counts = Counter(_tokenize(_content_text(redacted)))
    survived = 0
    for tok in orig_tokens:
        if redacted_counts[tok] > 0:
            redacted_counts[tok] -= 1
            survived += 1
    return survived, len(orig_tokens)
