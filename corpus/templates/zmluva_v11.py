"""Nájomná zmluva — the v1.1 integration document type.

Purpose: give EVERY type added in the v1.1 sprint real end-to-end coverage. Before this
template existed the new detectors were proven only by hand-built unit fixtures — the
synthetic corpus contained no addresses, no ID-document numbers and no bank-office
references at all, so both the leak gate and per-type recall were silently VACUOUS for
sixteen types (a type with no ground-truth occurrence scores ``recall = None``, which reads
as "no problem" rather than as "never tested").

It doubles as one of the new document types ADDENDUM 1 R4 asks for (nájomná zmluva).

THE ANCHOR CONTRACT — the reason this file is not a trivial loop over ``make_all``:

Several v1.1 detectors are deliberately ANCHOR-REQUIRED, because their bare shape is far too
generic to claim on sight — a 4-digit run is a year, a house number or an amount long before
it is a bank code. Their generators in ``corpus/pii/*`` therefore emit the VALUE only, and it
is this template's job to place the anchor text around it. Get that wrong and the corpus
contains a PII surface no detector can ever see, which shows up as a leak-gate failure that
looks like a detector bug but is actually a fixture bug.

Anchor-required here, with the anchor this template supplies:

    NAZOV_UCTU        "Názov účtu: "        (value runs to end of line)
    CISLO_KLIENTA     "Číslo klienta: "
    KOD_BANKY         "Kód banky "
    FAX               "Fax: "
    VODICSKY_PREUKAZ  "Vodičský preukaz č. "
    PSC / ADRESA      the generators already embed their own context ("PSČ …", "trvale
                      bytom …"), so the placed string is used verbatim — see ``_placed``.

Self-shape-sufficient (no anchor needed): CISLO_OP, CISLO_PASU, ECV, VIN, BIC,
SUPISNE_CISLO, CISLO_BYTU, VCHOD, POSCHODIE.

Placement is spread deliberately across body, table cells, header, footer, footnote and a
textbox so the writers' surface coverage is exercised too, not just the detectors'.
"""
from __future__ import annotations

from ..groundtruth import PiiSpec
from ..pii import addresses, documents, names_anchored, office_refs, orgs, ulica
from . import _common

# Anchor prefixes for the anchor-required types. The anchor is NOT part of the ground-truth
# surface — it is ordinary document text that must SURVIVE redaction; only the value is PII.
_ANCHORS = {
    "NAZOV_UCTU": "Názov účtu: ",
    "CISLO_KLIENTA": "Číslo klienta: ",
    "KOD_BANKY": "Kód banky ",
    "FAX": "Fax: ",
    "VODICSKY_PREUKAZ": "Vodičský preukaz č. ",
}


def _items(placed: str, spec: PiiSpec) -> list:
    """Turn one (placed, spec) generator result into a builder items list.

    ``placed`` is what the generator wants written; ``spec.surface`` is the PII substring
    inside it. When they differ, the surrounding context (an anchor the generator embedded,
    e.g. "PSČ " or "trvale bytom ") is emitted as PLAIN TEXT and only ``spec.surface`` is
    recorded as PII — otherwise ground truth would claim the anchor is PII and the leak test
    would demand the document be made unreadable.
    """
    anchor = _ANCHORS.get(spec.type, "")
    if placed == spec.surface:
        return ([anchor, spec] if anchor else [spec])
    head, _, tail = placed.partition(spec.surface)
    return [anchor + head, spec, tail]


def _one(maker, rng) -> list:
    return _items(*maker(rng))


def build(b, rng, bank, *, is_docx: bool) -> None:
    rec = b.rec
    p1 = _common.make_person(rng, bank, rec, "prenajimatel")
    p2 = _common.make_person(rng, bank, rec, "najomca")
    people = [(p1, "prenajimatel"), (p2, "najomca")]

    b.heading("Nájomná zmluva")
    b.paragraph([
        "uzavretá podľa § 663 a nasl. Občianskeho zákonníka medzi prenajímateľom ",
        _common.name_spec(p1, "ins", "prenajimatel", "full"),
        " a nájomcom ",
        _common.name_spec(p2, "ins", "najomca", "full"), ".",
    ])

    # ---- the shared v1 failure-mode seeding (identifiers, declension, decoys, metadata) ----
    ids = _common.identifier_specs(rng)
    _common.seed_all(b, rng, bank, rec, is_docx=is_docx, ids=ids, people=people)

    # ---- v1.1 ADDRESS BLOCK -------------------------------------------------------------
    b.heading("Článok II — Predmet nájmu")  # PdfBuilder.heading takes no level; keep the call shape shared
    b.paragraph(["Prenajímateľ prenecháva nájomcovi byt na adrese "]
                + _one(addresses.make_adresa, rng)
                + [", "]
                + _one(addresses.make_supisne_cislo, rng)
                + [", "]
                + _one(addresses.make_cislo_bytu, rng)
                + [", "]
                + _one(addresses.make_vchod, rng)
                + [", "]
                + _one(addresses.make_poschodie, rng)
                + ["."])
    b.paragraph(["Doručovacia adresa nájomcu"] + _one(addresses.make_psc, rng) + ["."])

    # ---- v1.1 IDENTITY-DOCUMENT BLOCK, in a table --------------------------------------
    b.table([
        [["Doklad"], ["Číslo"]],
        [["Občiansky preukaz"], _one(documents.make_cislo_op, rng)],
        [["Cestovný pas"], _one(documents.make_cislo_pasu, rng)],
        [["Vodičský preukaz"], _one(documents.make_vodicsky_preukaz, rng)],
        [["Evidenčné číslo vozidla"], _one(documents.make_ecv, rng)],
        [["VIN vozidla"], _one(documents.make_vin, rng)],
        [["Lehota (nie PII)"], ["30 dní"]],
    ])

    # ---- v1.1 BANK / OFFICE-REFERENCE BLOCK (vyhláška 482/2011 clause f) ----------------
    b.heading("Článok III — Platobné údaje")
    b.paragraph(["Nájomné sa uhrádza na účet. "]
                + _one(office_refs.make_nazov_uctu, rng)
                + [". "]
                + _one(office_refs.make_kod_banky, rng)
                + [". BIC "]
                + _one(documents.make_bic, rng)
                + [". "]
                + _one(office_refs.make_cislo_klienta, rng)
                + ["."])

    # ---- v1.1 ANCHORED NAMES (Phase C) ---------------------------------------------------
    # The title / role / field-label anchors had unit fixtures but NO corpus occurrence, so
    # neither the leak gate nor per-type recall was asking about them at all. Each generator
    # already embeds its own anchor text ("zmluvu podpisal ... , PhD.", "Meno:", "Sidlo:"),
    # so the placed string is used verbatim and only the VALUE is recorded as PII -- the
    # anchor itself is ordinary document text that must SURVIVE redaction.
    b.heading("Článok V — Účastníci a zastúpenie")
    for maker in (
        names_anchored.make_title_name,
        names_anchored.make_role_name,
        names_anchored.make_field_meno,
        names_anchored.make_field_adresa,
        names_anchored.make_field_statna_prislusnost,
        names_anchored.make_field_org,
    ):
        b.paragraph(_one(maker, rng) + ["."])

    # ---- v1.1 ULICA (CONTRACTS_v11.md §12 ADDENDUM 1 R3; redteam/FINDINGS_ROUND2.md C-2) --
    # Zero ground-truth ULICA occurrences existed anywhere in the corpus before this round —
    # an excluded type is an untested type. Every shape the task asks for gets a real
    # occurrence: the "ul." prefix, one of the other five keyword prefixes (spread across
    # documents by rng.choice), a trailing house number, and the declined-form hard case,
    # which corpus/pii/ulica.py documents as an EXPECTED miss — seeded anyway so the recall
    # gate records the gap instead of the type staying silently untested for that shape too.
    # Placed in the shared (non-format-branch) part of the template so it lands in both DOCX
    # and PDF output, same as every other v1.1 block above.
    b.heading("Článok VI — Adresa nehnuteľnosti (ulica)")
    b.paragraph(["Nehnuteľnosť leží na "] + _one(ulica.make_ulica_ul, rng) + ["."])
    b.paragraph(["Správca budovy sídli na "] + _one(ulica.make_ulica_keyword, rng) + ["."])
    b.paragraph(["Vchod do budovy je na "] + _one(ulica.make_ulica_housenum, rng) + ["."])
    # make_ulica_declined's ``placed`` already starts with "na " ("na Hlavnej ulici"), so the
    # wrapping sentence must NOT prepend its own "na " too (that produced a doubled "na na" —
    # caught by regenerating and reading the output, not assumed correct).
    b.paragraph(["Zmluvné strany sa dostavili "] + _one(ulica.make_ulica_declined, rng) + ["."])
    if is_docx:
        # Split across multiple <w:r> runs (context.md §7/§10) — reuses the mechanism
        # corpus/templates/_common.py already uses for a split surname.
        _, split_spec = ulica.make_ulica_ul(rng)
        b.split_run_paragraph("Poštová adresa je na ul. ", split_spec, ", v prízemí.")

    # ---- v1.1 ORG + NAZOV_BANKY ----------------------------------------------------------
    # NAZOV_BANKY had a detector and NO corpus occurrence, so no gate was asking about it —
    # the same vacuous-coverage trap this template exists to close. ORG already had corpus
    # coverage (150 occurrences, mostly metadata) but no body occurrence carrying a legal-form
    # suffix, which is the signal the detector actually keys on.
    b.paragraph(["Účet je vedený v "] + _one(orgs.make_nazov_banky, rng) + ["."])
    b.paragraph(["Zhotoviteľom je "] + _one(orgs.make_org, rng) + ["."])

    # ---- spread across the OTHER surfaces each format offers ----------------------------
    # The two builders expose DIFFERENT surface sets, and that asymmetry is the point: a
    # DOCX hides text in headers/footers/notes/textboxes, a PDF hides it in annotations,
    # form fields and attachments. Seeding each format's own hiding places is what makes the
    # leak gate meaningful per format rather than testing the body twice.
    if is_docx:
        b.header(["Nájomná zmluva — "] + _one(office_refs.make_fax, rng))
        b.footer(["Kontaktná adresa: "] + _one(addresses.make_adresa, rng))
        b.footnote(
            "Podrobnosti o vozidle sú uvedené nižšie.",
            ["Evidenčné číslo: "] + _one(documents.make_ecv, rng),
        )
        b.textbox(["Byt: "] + _one(addresses.make_cislo_bytu, rng))
    else:
        b.annotation(["Kontaktný fax: "] + _one(office_refs.make_fax, rng))
        b.attachment(
            "poznamka.txt",
            ["Evidenčné číslo vozidla: "] + _one(documents.make_ecv, rng),
        )

    b.paragraph(["Zmluvné strany vyhlasujú, že zmluvu uzavreli slobodne a vážne."])
