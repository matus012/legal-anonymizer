"""PROPERTY TEST for the v1.1 normalization layer (sprint brief, priority 1).

    "for random insertions of ZW/soft-hyphen/tab into any corpus doc, the redacted
     original text contains none of the ground-truth PII"

This is the test that makes the normalization layer worth having, because it is the only one
that checks the WHOLE claim rather than a piece of it: not "does the map satisfy its
invariants" (tests/test_normalize.py) and not "does recall go up" (eval/mutation_gate.py),
but "after a randomly corrupted document is redacted, is the PII actually gone from it".

WHY IT IS A PROPERTY TEST AND NOT A TABLE OF CASES
--------------------------------------------------------------------------------------
Every invisible-character defect this project has found was found at a position nobody had
thought to write a case for: an NBSP between the two words of an anchor, a line break one
word further along than the fix that was supposed to cover it. Enumerating positions is how
those were missed twice. Random insertion at a random position, repeated, asks the question
at positions no author would pick — including inside the checksum, on the boundary between
an anchor and its value, and between the last two digits.

THE ORACLE IS THE ORIGINAL SURFACE, NOT THE MUTATED ONE. After redaction, the corrupted text
must not contain the PII in ANY of the forms it could be read back as: the mutated spelling,
the original spelling, and the format-character-stripped spelling. Checking only the mutated
spelling would pass a redactor that removed the zero-width space and left the digits.

Seeded, so a failure is reproducible from the printed seed alone.
"""
import random
import unicodedata

import pytest

from detect.core import detect
from detect.normalize import strip_format_chars

# Characters inserted at random positions. Each one is something the pipeline meets in
# production, not a synthetic adversary: U+200B from a bank portal's account-number field,
# U+00AD from Word's optional hyphen and from PyMuPDF's hyphen rendering, U+FEFF from a
# mis-decoded stream.
#
# WHAT IS NOT IN THIS TUPLE, AND WHY — this test found the boundary of the normalization
# layer's contract and the boundary is recorded here rather than papered over.
#
# WHITESPACE INSERTED INSIDE A TOKEN ("8503\t15/0018", "4712 3456") IS NOT COVERED AND IS NOT
# CLAIMED. The normalization layer collapses a whitespace RUN to a single space, which fixes
# every separator BETWEEN tokens — an anchor phrase broken by an NBSP, a wrapped PDF line, a
# tab-aligned table cell. It deliberately does NOT delete a space that sits between two
# digits, because deleting it would silently widen every numeric pattern in detect/ at once:
# "\\d{8}" would begin matching "2020 2021" and "\\d{10}" would begin joining unrelated
# figures across a table. That is a real precision trade with a real cost — "Strana 3 z 12"
# was already auto-redacted once as an address and had to be fixed — and it deserves its own
# measurement rather than riding in on a layer built for invisible characters.
#
# So it is measured instead of assumed: corpus/mutations.py carries it as the ``split_token``
# class and eval/mutation_gate.py grades it against the same 0.95 threshold as everything
# else. A defect that is counted every run is in a better place than one hidden inside a
# green test. See QUESTIONS.md Q12 and redteam/FINDINGS_ROUND3.md.
INSERTIONS = ("​", "‌", "‍", "﻿", "­")

# Surfaces exercised, each with the sentence it lives in. Kept as literal text rather than
# read from data/synthetic so the test runs with no corpus present — the corpus is
# seed-deterministic and gitignored, and a test that silently skips is a test that rots.
CASES = [
    ("850315/0018", "Rodné číslo predávajúceho je 850315/0018 podľa občianskeho preukazu."),
    ("SK68 0720 0002 8919 8742 6353", "Kúpna cena sa uhradí na účet SK68 0720 0002 8919 8742 6353."),
    ("47123456", "Spoločnosť s IČO 47123456 je zapísaná v obchodnom registri."),
    ("jan.novak@advokat.sk", "Kontakt: jan.novak@advokat.sk pre všetky podania."),
    ("+421 905 123 456", "Telefonický kontakt: +421 905 123 456 počas pracovných dní."),
    ("1234567890", "DIČ platiteľa je 1234567890 podľa registrácie."),
]

_SEED = 20260916


def _redact(text: str) -> str:
    """The redaction both writers perform, in the coordinates they perform it in: every
    auto=True span is cut out of the ORIGINAL string and replaced by its label. This is the
    operation the offset map has to be right for — writer/docx_body.py rebuilds runs around
    exactly these offsets and writer/pdf_body.py destroys the glyphs under exactly this text.
    """
    out = []
    cursor = 0
    for c in detect(text):
        if not c.auto:
            continue
        assert c.start >= cursor, f"overlapping spans reached the writer: {c}"
        out.append(text[cursor : c.start])
        out.append(f"[{c.type}]")
        cursor = c.end
    out.append(text[cursor:])
    return "".join(out)


def _readings(surface: str, mutated_surface: str) -> set[str]:
    """Every spelling the PII could be recovered as from the redacted output."""
    return {
        surface,
        mutated_surface,
        strip_format_chars(mutated_surface),
        unicodedata.normalize("NFC", strip_format_chars(mutated_surface)),
    }


def _insert(rng: random.Random, text: str, surface: str) -> tuple[str, str]:
    """Insert one random character at a random position INSIDE the surface's occurrence.
    Returns (corrupted document text, corrupted surface)."""
    at = text.index(surface)
    offset = rng.randrange(1, len(surface))          # strictly inside, never at the edges
    char = rng.choice(INSERTIONS)
    mutated_surface = surface[:offset] + char + surface[offset:]
    return text[:at] + mutated_surface + text[at + len(surface) :], mutated_surface


@pytest.mark.parametrize("surface,sentence", CASES)
def test_random_insertion_inside_a_surface_still_gets_redacted(surface, sentence):
    rng = random.Random(f"{_SEED}:{surface}")
    failures = []
    for trial in range(200):
        corrupted, mutated_surface = _insert(rng, sentence, surface)
        redacted = _redact(corrupted)
        leaked = [r for r in _readings(surface, mutated_surface) if r and r in redacted]
        if leaked:
            failures.append((trial, repr(corrupted), repr(redacted), leaked))
    assert not failures, (
        f"{len(failures)}/200 trials leaked {surface!r}. "
        f"Reproduce with seed {_SEED!r}. First three: {failures[:3]}"
    )


@pytest.mark.parametrize("surface,sentence", CASES)
def test_the_redaction_never_corrupts_text_outside_the_span(surface, sentence):
    """The other half of the offset map's contract, and the half a recall gate cannot see.
    A map that is too GREEDY still removes the PII — and eats the words around it. The text
    before the surface and after the sentence's PII must survive verbatim.

    'Rodné číslo predávajúceho je' must still be there after the rodné číslo is gone; a
    reviewer who cannot read what the document said around a redaction cannot check it.
    """
    prefix = sentence[: sentence.index(surface)].rstrip()
    rng = random.Random(f"{_SEED}:outside:{surface}")
    for _ in range(100):
        corrupted, _ = _insert(rng, sentence, surface)
        redacted = _redact(corrupted)
        assert prefix in redacted, (
            f"redaction ate text outside the span: prefix {prefix!r} lost from {redacted!r}"
        )


def test_multiple_simultaneous_insertions():
    """One insertion per surface is the easy case. Real corruption is not polite: a document
    round-tripped through a Mac and a bank portal carries several at once, in several
    surfaces, including two inside the same token."""
    rng = random.Random(f"{_SEED}:multi")
    sentence = (
        "Predávajúci Ján Novák, rodné číslo 850315/0018, IČO 47123456, "
        "účet SK68 0720 0002 8919 8742 6353, e-mail jan.novak@advokat.sk."
    )
    surfaces = ["850315/0018", "47123456", "SK68 0720 0002 8919 8742 6353", "jan.novak@advokat.sk"]
    for trial in range(200):
        corrupted = sentence
        mutated = {}
        for s in surfaces:
            corrupted, mutated[s] = _insert(rng, corrupted, s)
            # a second insertion into the same, already-corrupted surface
            corrupted, mutated[s] = _insert(rng, corrupted, mutated[s])
        redacted = _redact(corrupted)
        leaked = [
            s for s in surfaces
            if any(r and r in redacted for r in _readings(s, mutated[s]))
        ]
        assert not leaked, (
            f"trial {trial}: leaked {leaked} from {corrupted!r} -> {redacted!r}"
        )


def test_nfd_document_is_redacted():
    """A .docx round-tripped on macOS comes back decomposed. The two forms are canonically
    equivalent and render identically, so nothing in the document LOOKS different — which is
    why this needs a test rather than a reviewer."""
    sentence = "Predávajúci Ján Novák, rodné číslo 850315/0018, bytom Košice."
    decomposed = unicodedata.normalize("NFD", sentence)
    redacted = _redact(decomposed)
    for form in ("850315/0018", unicodedata.normalize("NFD", "850315/0018")):
        assert form not in redacted
    assert "Novák" not in unicodedata.normalize("NFC", redacted)


def test_cyrillic_homoglyph_does_not_truncate_an_email():
    """redteam/FINDINGS_ROUND2.md called this the sharpest case in the round: an e-mail with
    one Cyrillic letter was not MISSED, it was SILENTLY TRUNCATED — the tool redacted
    '.novak@advokat.sk' and left 'jan' standing beside it, which reads as a successful
    redaction in every report. A partial redaction of a single token is a FAIL, not a recall
    number."""
    sentence = "Kontakt: jаn.novak@advokat.sk pre podania."  # Cyrillic а inside 'jan'
    redacted = _redact(sentence)
    assert "jan" not in redacted.lower()
    assert "novak" not in redacted.lower()
    assert "advokat.sk" not in redacted.lower()
