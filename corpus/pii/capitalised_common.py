"""Adversarial decoy class CAPITALISED_COMMON (context.md §5) — the real stage-3 precision risk.

The six numeric decoy classes in ``decoys.py`` (invoice_no, page_count, ...) are trivially
separable from PII by shape — no plausible detector would ever confuse a digit-run decoy for
a name, so decoy survival on those classes measures nothing hard. The actual precision risk
§5 describes is a declension-tolerant, over-matching gazetteer/known-entity matcher: stem the
entity, match "stem + any plausible suffix", case-insensitive, accepting over-matching by
design (§6, recall over precision). That kind of matcher WILL hit ordinary capitalised
Slovak words that are not PII at all. These must survive untouched: ground truth marks every
one ``auto_redact=False, should_flag=False, type="CAPITALISED_COMMON"``.

Five adversarial sources, all seeded deterministically from the caller's ``rng``:

* **sentence-initial common nouns** — capitalised purely by sentence position, zero PII
  content (``Dokument obsahuje...``, ``Predmet tejto zmluvy...``)
* **capitalised legal-drafting terms** — Slovak contracts conventionally capitalise defined
  terms (``Kupujúci``, ``Predávajúci``, ``Zmluvné strany``, ``Článok``, ``Prílohu``); a naive
  "capitalised token" heuristic hits every one
* **month / weekday names** — capitalised, proper-noun-shaped, zero PII content
* **institution words that are NOT the party in this document** (``Okresný súd``,
  ``Notársky úrad``, ``Kataster nehnuteľností``) — generic, never tied to a specific GT
  entity here
* **a REAL Slovak occupational-noun or adjective derivative of THIS document's own seeded
  surname** (e.g. "Kováč" → "Kováčska dielňa"; "Hudák" → "Hudácka kapela") — the case that
  actually breaks a stem+suffix matcher, and the reason it is dangerous in production: Slovak
  surnames are overwhelmingly occupational or descriptive nouns (kováč = blacksmith, hudák =
  dialectal for a folk musician, ...), so the common Slovak adjective derived from that
  occupation is a REAL, ordinary word that a reader would never mistake for the person, yet
  it literally begins with the surname (``Kováčska`` is not ``Kováč`` plus a possessive
  suffix — a possessive adjective, ``Kováčov``, IS a declension of the person and must be
  redacted; ``Kováčska`` is the OCCUPATIONAL adjective, a different word entirely, related by
  etymology, not grammar). These are hand-curated (:data:`SURNAME_REAL_WORD_DECOYS`), not
  algorithmically derived — an earlier version invented plausible-looking non-words
  ("Nováčisko"), which was rejected: an invented word cannot occur in a real document, so it
  validates a stemmer against a string that does not exist. Only surnames in this corpus's
  name bank with a genuine, checkable etymological tie are included; the rest fall back to
  the place-based decoy below, which is always present.

* **a regional/demonym adjective built from THIS document's own seeded place** (e.g. "Košice"
  → "Košický súd") — same reasoning, real Slovak demonym adjectives, always present since
  every place in the corpus's bank has a curated form.

Both entity-derived sources are matched against the entity's own recorded case forms once, by
hand, at authoring time (not at runtime): see the comments by each table. A surface that is a
literal, unmodified declension of the entity (``Kováčov``, ``Kováčovi``, ...) would be PII and
must never appear here.
"""
from __future__ import annotations

import random

# --------------------------------------------------------------------- legal-drafting terms
# (surface, prefix, suffix) — capitalised by legal convention, not sentence position.
LEGAL_TERMS: list[tuple[str, str, str]] = [
    ("Zmluva", "Táto ", " nadobúda platnosť dňom podpisu."),
    ("Kupujúci", "Podľa tejto zmluvy je ", " povinný uhradiť kúpnu cenu."),
    ("Predávajúci", "Podľa tejto zmluvy je ", " povinný odovzdať nehnuteľnosť."),
    ("Zmluvné strany", "", " sa zaväzujú dodržať všetky dohodnuté podmienky."),
    ("Článok", "Pozri ", " tretí tejto zmluvy."),
    ("Prílohu", "Pozri ", " č. 1 tejto zmluvy."),
    ("Splnomocniteľ", "", " udeľuje týmto splnomocnenie v plnom rozsahu."),
    ("Splnomocnenec", "", " je oprávnený konať v mene splnomocniteľa."),
    ("Žalobca", "", " podáva žalobu na príslušný súd."),
    ("Žalovaný", "", " sa vyjadrí k žalobe v stanovenej lehote."),
]

# --------------------------------------------------------------------- sentence-initial nouns
# (surface, prefix, suffix) — capitalised ONLY because they open the sentence.
SENTENCE_INITIAL: list[tuple[str, str, str]] = [
    ("Dokument", "", " obsahuje všetky náležitosti podľa zákona."),
    ("Predmet", "", " tejto zmluvy je bližšie špecifikovaný nižšie."),
    ("Strany", "", " sa dohodli na nasledujúcich podmienkach."),
    ("Vlastník", "", " potvrdzuje súhlas s prevodom nehnuteľnosti."),
    ("Cena", "", " bola stanovená vzájomnou dohodou zmluvných strán."),
    ("Podpis", "", " potvrdzuje súhlas oboch zúčastnených strán."),
    ("Overenie", "", " totožnosti prebehlo v súlade s predpismi."),
    ("Dodatok", "", " k tejto zmluve nadobúda platnosť okamžite."),
]

# --------------------------------------------------------------------- calendar names
MONTHS = [
    "Január", "Február", "Marec", "Apríl", "Máj", "Jún",
    "Júl", "August", "September", "Október", "November", "December",
]
WEEKDAYS = ["Pondelok", "Utorok", "Streda", "Štvrtok", "Piatok", "Sobota", "Nedeľa"]
CALENDAR: list[tuple[str, str, str]] = (
    [(m, "", " je mesiacom, kedy bola táto zmluva podpísaná.") for m in MONTHS]
    + [(d, "", " je dňom, kedy bola zmluva doručená druhej strane.") for d in WEEKDAYS]
)

# --------------------------------------------------------------------- institutions (not the party)
INSTITUTIONS: list[tuple[str, str, str]] = [
    ("Okresný súd", "", " rozhodol vo veci miestnej príslušnosti."),
    ("Notársky úrad", "", " overil pravosť podpisu na tejto listine."),
    ("Kataster nehnuteľností", "", " eviduje záznam o vlastníctve."),
    ("Obchodný register", "", " obsahuje aktuálny výpis o spoločnosti."),
]

_STATIC_POOL: list[tuple[str, str, str]] = LEGAL_TERMS + SENTENCE_INITIAL + CALENDAR + INSTITUTIONS

# --------------------------------------------------------------------- entity-derived (stem-sharing)
# Hand-curated, real Slovak words derived from the corpus's occupational/descriptive surnames
# (context.md rejection round 6). Each entry: (surface, prefix, suffix). Checked by hand
# against every declined form in corpus/names/data/names.json (nominative, genitive, dative,
# accusative, locative, instrumental, both genders, family plural) — none of these surfaces
# is a substring match under a plain check EXCEPT where the shared letters are followed by a
# lowercase letter (a live Slovak suffix continuing the SAME word, e.g. "Kováč" + "ska" in
# "Kováčska") — exactly the case eval/leak.py's word-boundary fix (round 6) exists to get
# right, verified in tests/test_leak.py and tests/test_generate_smoke.py.
#
# Only surnames with a genuine, checkable etymological tie are included. A surname NOT in
# this table (Baláž, Tóth, Šimko, Molnár, Varga — Hungarian-origin patronymics/occupational
# terms with no live Slovak common-noun cognate) falls back to the place-based decoy, which
# is always present, so every document still gets >=1 real entity-stem-sharing case.
SURNAME_REAL_WORD_DECOYS: dict[str, list[tuple[str, str, str]]] = {
    # Kováč (surname) / kováč (blacksmith, real Slovak occupational noun) -> kováčsky/-a
    # (adjective). "Kováčska ulica" is a genuine Slovak street name pattern.
    "Kováč": [
        ("Kováčska", "", " dielňa sa nachádza v susednej ulici."),
        ("Kováčskej", "Adresa ", " ulice bola uvedená v prílohe."),
    ],
    # Hudák (surname) / hudák (dialectal Slovak for a folk musician/fiddler) -> hudácky/-a.
    "Hudák": [
        ("Hudácka", "", " kapela vystúpila na miestnom podujatí."),
        ("Hudáckej", "Nahrávka ", " skupiny bola priložená k spisu."),
    ],
    # Novák relates to "nový" (new); "nováčik" (novice/newcomer/rookie) is a real, common
    # Slovak word from the same root, distinct from any declension of the surname.
    "Novák": [
        ("Nováčik", "", " sa v tíme rýchlo zaučil."),
        ("Nováčika", "Prijatie ", " prebehlo bez problémov."),
    ],
    # Horváth (Hungarian-origin surname meaning "Croat"); "horvátsky" (Croatian, adjective)
    # is a real, well-known Slovak word from the same root.
    "Horváth": [
        ("Horvátsky", "", " veľvyslanec navštívil úrad v tejto veci."),
        ("Horvátskej", "Kópia ", " zmluvy bola priložená k spisu."),
    ],
    # Kučera relates to "kučeravý" (curly-haired/curly), a real, common Slovak adjective.
    "Kučera": [
        ("Kučeravý", "", " štýl podpisu bol overený znalcom."),
        ("Kučeravej", "Kópia ", " fotografie bola súčasťou prílohy."),
    ],
}


def surname_stem_decoy(
    surname_nom: str, rng: random.Random
) -> tuple[str, str, str] | None:
    """A real, curated Slovak word derived from ``surname_nom`` — ``None`` if this surname
    has no entry in :data:`SURNAME_REAL_WORD_DECOYS` (caller falls back to the place-based
    decoy, always present)."""
    options = SURNAME_REAL_WORD_DECOYS.get(surname_nom)
    if not options:
        return None
    return rng.choice(options)


# Regional/demonym adjectives for the corpus's fixed place list (context.md §4.2) — hand
# curated, real Slovak words, not derived: Slovak demonyms are irregular (Nitra -> nitriansky,
# not "nitrský"). Checked by hand against every declined form of each place (nominative
# through instrumental) — none collides even under a plain substring check.
_PLACE_ADJECTIVES = {
    "Košice": "košický",
    "Levoča": "levočský",
    "Michalovce": "michalovský",
    "Bratislava": "bratislavský",
    "Žilina": "žilinský",
    "Nitra": "nitriansky",
    "Trnava": "trnavský",
    "Prešov": "prešovský",
    "Poprad": "popradský",
    "Trenčín": "trenčiansky",
    "Zvolen": "zvolenský",
    "Banská Bystrica": "banskobystrický",
    "Staré Mesto": "staromestský",
    "Ružinov": "ružinovský",
}


def place_adjective(place_nom: str, rng: random.Random) -> tuple[str, str, str] | None:
    """A regional adjective built from ``place_nom`` (e.g. "Košice" -> "Košický súd") if a
    curated form exists."""
    adj = _PLACE_ADJECTIVES.get(place_nom)
    if adj is None:
        return None
    surface = f"{adj[0].upper()}{adj[1:]} {rng.choice(('súd', 'register', 'úrad'))}"
    return surface, "", " potvrdil prevzatie dokumentácie."


def generate(
    rng: random.Random,
    *,
    surname_nom: str | None = None,
    place_nom: str | None = None,
    n: int = 5,
) -> list[tuple[str, str, str]]:
    """Return ``n`` adversarial CAPITALISED_COMMON decoys as ``(surface, prefix, suffix)``.

    Includes a real, curated entity-stem-sharing decoy when ``surname_nom`` has an entry in
    :data:`SURNAME_REAL_WORD_DECOYS`, plus a place-based one whenever ``place_nom`` has a
    curated adjective (always true for this corpus's place bank) — the case that actually
    breaks a stem+suffix matcher (context.md §5). The rest is filled from the static pool
    (legal terms, sentence-initial nouns, calendar names, institutions), sampled without
    replacement so a single document never repeats a surface.
    """
    picks: list[tuple[str, str, str]] = []
    if surname_nom:
        entity = surname_stem_decoy(surname_nom, rng)
        if entity is not None:
            picks.append(entity)
    if place_nom:
        adj = place_adjective(place_nom, rng)
        if adj is not None:
            picks.append(adj)

    remaining = max(0, n - len(picks))
    picks.extend(rng.sample(_STATIC_POOL, k=min(remaining, len(_STATIC_POOL))))
    return picks
