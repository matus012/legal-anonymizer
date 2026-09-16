# LICENSES.md — third-party data bundled into the anonymizer

Every list the application ships inside `detect/gazetteer_data/*.json` is derived from a
public source whose licence is recorded here, with the URL it came from and the date it was
fetched. Raw downloads live in `detect/gazetteer_data/_raw/` and are **gitignored** — only
the small normalised JSON lists are committed. Regenerate everything with:

```
.\.venv\Scripts\python.exe -m tools.build_gazetteer
```

Fetched: **2026-09-16**.

---

## Accepted sources

### 1. Register adries — Register obcí (municipalities)
* **Publisher:** Ministerstvo vnútra SR
* **Dataset:** Register Adries — Register obcí, distribution "Obce - konsolidované dáta"
* **Catalogue:** https://data.slovensko.sk/datasety/1277119c-0c20-40c5-9416-30afcc31e7b3
* **Dataset URI:** https://data.gov.sk/set/1277119c-0c20-40c5-9416-30afcc31e7b3
* **Licence:** **CC0 1.0** (declared on the distribution via
  `http://publications.europa.eu/resource/authority/licence/CC0`) — public domain
  dedication, no attribution required. Also flagged by the publisher as a
  High-Value Dataset (HVD) under the EU Open Data Directive.
* **Rows fetched:** 3 030 → **2 842** current municipality names after filtering.
* **Derived file:** `detect/gazetteer_data/obce.json`

### 2. Register adries — Register ulíc (streets)
* **Publisher:** Ministerstvo vnútra SR
* **Dataset:** Register Adries — Register ulíc, distribution "Ulice - konsolidované dáta"
* **Catalogue:** https://data.slovensko.sk/datasety/f2b3af7a-b4d4-45d7-9605-29fa5d7ad115
* **Licence:** **CC0 1.0** (same EU authority URI as above). HVD.
* **Rows fetched:** 51 158 → **12 000** distinct current street names.
* **Derived file:** `detect/gazetteer_data/ulice.json`

### 3. Katastrálne územia (cadastral areas)
* **Publisher:** Úrad geodézie, kartografie a katastra Slovenskej republiky (ÚGKK SR)
* **Dataset:** Základný číselník CL000026 — Katastrálne územia
* **Catalogue:** https://data.slovensko.sk/datasety/926c7e9a-541b-407d-96c8-a0dc927d1f47
* **Download:** https://metais.slovensko.sk/api/codelist-repo/codelists/codelistheaders/CL000026/download?type=CSV
* **Licence:** **CC BY 4.0** (`http://publications.europa.eu/resource/authority/licence/CC_BY_4_0`).
  **Attribution is required** and is given here and in the application's README:
  *Contains data from ÚGKK SR, codelist CL000026, licensed under CC BY 4.0.*
* **Rows fetched:** 3 559 → **3 416** current cadastral-area names.
* **Derived file:** `detect/gazetteer_data/katastralne_uzemia.json`

### 4. Slovak given names — name-day (meniny) calendar
* **Source:** https://github.com/jozefgrencik/slovak-name-days (`data/names.json`)
* **Licence:** **MIT** (verified by fetching the repository's `LICENSE` file and the GitHub
  API's `license.spdx_id`). Copyright (c) 2023 Jozef Grencik.
* **Derived file:** merged into `detect/gazetteer_data/first_names.json`

### 5. Slovak given names and surnames — names generator corpus
* **Source:** https://github.com/enscope/slovak-names-generator
  (`input/names.male.txt`, `input/names.female.txt`,
  `input/surnames.male.txt`, `input/surnames.female.txt`)
* **Licence:** **CC0 1.0** (GitHub API `license.spdx_id` = `CC0-1.0`) — public domain
  dedication.
* **Derived files:** `first_names.json` (**481** entries, merged with source 4),
  `surnames.json` (**1 169** entries).

---

## Rejected sources

### Facebook-leak-derived name datasets — REJECTED
Name lists circulating as "Slovak names" that are extracted from the 2019/2021 Facebook
data-scrape dumps are **not used and must never be used**. They are personal data obtained
from a breach; bundling them into a tool whose entire purpose is protecting personal data
would be indefensible regardless of how convenient the coverage is. This project's names
come only from sources 4 and 5 above, both of which are curated word lists, not people.

### National Bank of Slovakia bank-code list — NOT OBTAINED
The NBS list of Slovak 4-digit bank codes was not reachable at any documented URL on
2026-09-16 (three candidate paths returned HTTP 404) and it is not published in the national
open-data catalogue. **Consequence:** `KOD_BANKY` ships with its allow-list parameter set to
`None`, which means "accept any 4 digits that follow a `kód banky` anchor or the `/` of a
legacy domestic account". That is the recall-safe default and is consistent with the
governing rule — a bank code that is not on a list is still redacted. If the list is obtained
later it only narrows false positives; it is not required for correctness.

### Czech ČSÚ surname sample and the LaBlazer gist — NOT USED
Both were listed as candidates. Neither was needed once sources 4 and 5 (MIT and CC0, both
unambiguous) supplied 481 given names and 1 169 surnames. Neither gist carries an explicit
licence file, and an unlicensed gist is "all rights reserved" by default — so using them
would have been the only license-unclear item in the bundle, for coverage that is already
largely redundant. Excluded on licence-clarity grounds, not on quality.

---

## Note on how these lists are used

The gazetteer is a **recall aid, not an authority**. A name or place absent from these lists
is still caught by the anchor-based detectors (title anchors, role anchors, field labels,
address anchors) and by the user's own known-entity input, which context.md §4.3 identifies
as the highest-value signal in the system. Entries that are also ordinary Slovak words are
held in `stoplist.json` and are excluded from the auto-redact bucket unless an address or
name anchor independently confirms them.
