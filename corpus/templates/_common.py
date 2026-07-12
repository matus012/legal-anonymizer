"""Shared seeding used by every doc-type template (context.md §7 failure modes).

The doc-type modules supply the boilerplate wording; this module supplies the people,
identifiers, declension showcase, inconsistent renderings, and the format-specific
failure-mode injection (DOCX vs PDF). Everything placed is auto-recorded by the builders.
"""
from __future__ import annotations

import random

from ..groundtruth import PiiSpec
from ..names.declension import CASES, NameBank, Person
from ..pii import (
    amounts,
    capitalised_common,
    dates,
    decoys,
    dic,
    email,
    ic_dph,
    iban,
    ico,
    phone,
    registry_refs,
    rodne_cislo,
    url,
)


def make_person(rng: random.Random, bank: NameBank, rec, entity_id: str, category="MENO") -> Person:
    """Create a person, register its entity + inconsistent variants in ground truth."""
    p = bank.person(rng)
    variants = [v for v, _ in p.variants()]
    rec.entity(entity_id, p.canonical, category, variants)
    return p


def name_spec(person: Person, case: str, entity_id: str, kind: str = "full") -> PiiSpec:
    surface = person.full(case) if kind == "full" else person.surname(case)
    return PiiSpec(surface, "MENO", entity_id=entity_id, grammatical_case=case)


def identifier_specs(rng: random.Random) -> dict:
    """One PiiSpec per §4.1 type, with correct three-state flags."""
    def flagged(surface, typ):  # checksum-invalid but PII-shaped → review bucket
        return PiiSpec(surface, typ, valid_checksum=False, auto_redact=False, should_flag=True)

    decoy_a, kind_a = decoys.generate(rng)
    decoy_b, kind_b = decoys.generate(rng)
    return {
        "rc": PiiSpec(rodne_cislo.generate(rng, valid=True), "RODNE_CISLO", valid_checksum=True),
        "rc_bad": flagged(rodne_cislo.generate(rng, valid=False), "RODNE_CISLO"),
        "ico": PiiSpec(ico.generate(rng, valid=True), "ICO", valid_checksum=True),
        "ico_bad": flagged(ico.generate(rng, valid=False), "ICO"),
        "iban": PiiSpec(iban.generate(rng, valid=True), "IBAN", valid_checksum=True),
        "iban_bad": flagged(iban.generate(rng, valid=False), "IBAN"),
        "account": PiiSpec(iban.generate_domestic(rng, valid=True), "BANKOVY_UCET", valid_checksum=True),
        "dic": PiiSpec(dic.generate(rng), "DIC"),
        "ic_dph": PiiSpec(ic_dph.generate(rng), "IC_DPH"),
        "email": PiiSpec(email.generate(rng), "EMAIL"),
        "phone": PiiSpec(phone.generate(rng), "TELEFON"),
        "url": PiiSpec(url.generate(rng), "URL"),
        "lv": PiiSpec(registry_refs.lv(rng), "LV"),
        "parcela": PiiSpec(registry_refs.parcela(rng), "PARCELA"),
        "orsr": PiiSpec(registry_refs.orsr_vlozka(rng), "ORSR_VLOZKA"),
        "spis": PiiSpec(registry_refs.spisova_znacka(rng), "SPISOVA_ZNACKA"),
        "suma": PiiSpec(amounts.generate(rng), "SUMA"),
        "datum": PiiSpec(dates.generate(rng), "DATUM"),
        "decoy_a": PiiSpec(decoy_a, kind_a.upper(), auto_redact=False, should_flag=False),
        "decoy_b": PiiSpec(decoy_b, kind_b.upper(), auto_redact=False, should_flag=False),
    }


def declension_showcase(b, person: Person, entity_id: str) -> None:
    """A body paragraph per case — the full name AND the bare surname, every case (§5)."""
    labels = {
        "nom": "V zmluve vystupuje",
        "gen": "Týka sa",
        "dat": "Doručuje sa",
        "acc": "Označujeme",
        "loc": "Hovoríme o",
        "ins": "Podpísané s",
    }
    for c in CASES:
        b.paragraph([f"{labels[c]} ", name_spec(person, c, entity_id, "full"),
                     " (priezvisko ", name_spec(person, c, entity_id, "surname"), ")."])


def inconsistent_mentions(b, person: Person, entity_id: str) -> None:
    """Same person written four ways — one entity, four surfaces (§7)."""
    for surface, style in person.variants():
        b.paragraph([f"({style}) ", PiiSpec(surface, "MENO", entity_id=entity_id), " ďalej v texte."])


def place_rhythmic(rng: random.Random, bank: NameBank):
    """A place exhibiting rhythmic vowel-shortening, in its oblique cases."""
    return bank.place(rng, rhythmic=True)


def seed_docx_failure_modes(b, rng, bank, ids: dict, p_extra: Person, e_extra: str) -> None:
    """Footnote, endnote, comment, textbox, split-run, tracked-change, header/footer, metadata."""
    b.split_run_paragraph("Kupujúci ", name_spec(p_extra, "nom", e_extra, "surname"),
                          " je uvedený vyššie.")
    b.header([PiiSpec(ids["email"].surface, "EMAIL"), "  |  ", PiiSpec(ids["url"].surface, "URL")])
    b.footer(["Kontakt: ", PiiSpec(ids["phone"].surface, "TELEFON")])
    b.footnote("Poznámka pod čiarou.", ["Rodné číslo účastníka ", ids["rc"], "."])
    b.endnote("Vysvetlivka.", ["IČO spoločnosti ", ids["ico"], "."])
    b.comment("sporná pasáž", ["Overiť totožnosť ", PiiSpec(p_extra.full("gen"), "MENO", entity_id=e_extra)])
    place = place_rhythmic(rng, bank)
    b.textbox(["Nehnuteľnosť v k. ú. ", PiiSpec(place.form("loc"), "OBEC", grammatical_case="loc")])
    b.tracked_change(
        "Pôvodná suma ",
        [ids["suma"]],
        [PiiSpec(p_extra.full("nom"), "MENO", entity_id=e_extra)],
    )
    b.set_metadata(
        PiiSpec(f"JUDr. {p_extra.canonical}", "MENO"),
        PiiSpec(f"Advokátska kancelária {p_extra.surname('nom')}", "ORG"),
    )


def seed_pdf_failure_modes(b, rng, bank, ids: dict, p_extra: Person, e_extra: str) -> None:
    """Annotation, form field, attachment, metadata + XMP."""
    b.annotation(["Poznámka: overiť ", PiiSpec(p_extra.full("acc"), "MENO", entity_id=e_extra),
                  ", IČO ", PiiSpec(ids["ico"].surface, "ICO", valid_checksum=True)])
    b.form_field("ucastnik", PiiSpec(p_extra.canonical, "MENO", entity_id=e_extra))
    b.form_field("iban", PiiSpec(ids["iban"].surface, "IBAN", valid_checksum=True))
    b.attachment("priloha.txt", ["Telefón ", PiiSpec(ids["phone"].surface, "TELEFON"),
                                 ", DIČ ", PiiSpec(ids["dic"].surface, "DIC")])
    b.set_metadata(
        PiiSpec(f"JUDr. {p_extra.canonical}", "MENO"),
        PiiSpec(p_extra.full("nom"), "MENO"),
    )


def capitalised_common_decoys(b, rng: random.Random, person: Person, place) -> None:
    """The real stage-3 precision risk (context.md §5, rejection rounds 5–6): a
    declension-tolerant, over-matching gazetteer/known-entity matcher will hit ordinary
    capitalised Slovak words that are NOT PII. >=3 per document. Where THIS document's own
    seeded surname has a curated real-word derivative (``capitalised_common.
    SURNAME_REAL_WORD_DECOYS`` — e.g. "Kováč" -> "Kováčska"), it's included; the place-based
    decoy (a real regional adjective, e.g. "Košice" -> "Košický") is always present — the
    case that actually breaks a stem+suffix matcher, not a generic corpus-wide word list.
    Both are hand-curated REAL Slovak words, never algorithmically invented (context.md
    rejection round 6) and never a declension of the entity itself."""
    for surface, prefix, suffix in capitalised_common.generate(
        rng, surname_nom=person.last["nom"], place_nom=place.nom, n=5,
    ):
        b.paragraph([prefix, PiiSpec(surface, "CAPITALISED_COMMON", auto_redact=False,
                                      should_flag=False), suffix])


def seed_all(b, rng, bank, rec, *, is_docx: bool, ids: dict, people: list) -> None:
    """Common failure-mode seeding shared by every template."""
    p_main, e_main = people[0]
    p_extra, e_extra = people[1]
    declension_showcase(b, p_main, e_main)
    inconsistent_mentions(b, p_main, e_main)
    # a rhythmic place in the body, several cases
    place = place_rhythmic(rng, bank)
    b.paragraph(["Kataster: ",
                 PiiSpec(place.form("gen"), "KATASTER", grammatical_case="gen"),
                 ", ",
                 PiiSpec(place.form("loc"), "KATASTER", grammatical_case="loc"), "."])
    # identifiers table + decoys (each cell is an items list of str | PiiSpec)
    b.table([
        [["Položka"], ["Hodnota"]],
        [["Rodné číslo"], [ids["rc"]]],
        [["Rodné číslo (chybné)"], [ids["rc_bad"]]],
        [["IČO (chybné)"], [ids["ico_bad"]]],
        [["IBAN (chybný)"], [ids["iban_bad"]]],
        [["Účet"], [ids["account"]]],
        [["Faktúra (nie PII)"], [ids["decoy_a"]]],
    ])
    b.paragraph(["Ďalšie údaje: ", ids["dic"], ", ", ids["ic_dph"], ", ", ids["lv"], ", ",
                 ids["parcela"], ", ", ids["spis"], ", ", ids["orsr"], ", dátum ", ids["datum"], "."])
    b.paragraph(["Referencie (nie PII): ", ids["decoy_b"], "."])
    capitalised_common_decoys(b, rng, p_main, place)
    if is_docx:
        seed_docx_failure_modes(b, rng, bank, ids, p_extra, e_extra)
    else:
        seed_pdf_failure_modes(b, rng, bank, ids, p_extra, e_extra)
