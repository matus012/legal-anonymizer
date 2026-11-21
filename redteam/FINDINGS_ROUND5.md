# Red-team findings, round 5 — WORD TEMPLATE STRUCTURES, HAND-AUTHORED AS RAW OOXML

*Transcribed to disk by the orchestrator: the round's own harness forbids subagents writing
report files, and the agent declined to route around that guard with a shell redirect rather
than circumvent its configuration. The judgement, the measurements and the expectations below
are the round's; the transcription is mine. Every number here is reproduced by
`tests/test_redteam_round5.py`, which IS on disk and is the authority if the two ever disagree.*

**Target: the package shapes a Word *template* produces, which `python-docx` cannot emit and
which the corpus generator has therefore never once put in front of a gate.**

Rounds 1–4 attacked the EXTRACTOR, the DETECTORS, the CONTAINER and THE NEW CODE. Every round
found real bugs while the gate stayed green, and the reason is always the same:
`corpus/generate.py` writes documents through `python-docx`, so the corpus can only contain the
shapes `python-docx` can write.

A real Slovak law-office document is written by Word, from a `.dotx`, and carries: a cover page
assembled from a building block, a letterhead on a first-page-only header, content controls with
client dropdowns, legacy Developer-tab form fields, footnotes with hyperlink field codes, pasted
HTML merged in as an `altChunk`, and a table of contents. **None of those shapes exists anywhere
in `data/synthetic`.** Round 5 hand-authors each one as raw OOXML, zips a valid OPC package, and
re-opens it before asserting anything.

Round 5 attacks five things:

1. **The PARTS the traversal does not enumerate** — first-page/even-page header and footer
   parts, the building-block glossary, `w:altChunk` sub-documents.
2. **The PASSES wired to the wrong roots** — `_scrub_field_codes` and `_strip_data_bindings`
   run on `doc.element` and the header/footer elements, and on nothing else.
3. **`docProps/app.xml`**, whose scrub is a two-item tag list applied with a regex.
4. **The ATTRIBUTE plane of `document.xml`** — the writer's only attribute sweep is
   `w:author`/`w:initials`.
5. **The R4 fixes, again** — whether the bookmark exemption survives contact with the spelling
   Word actually writes.

---

## 1. RESULT

**19 attacks attempted. 11 found a real defect.** One expectation (F2) was falsified in an
unexpected direction — `_TEXT_BEARING` is wrong in *both* directions at once — and four
"CLEAN expected" statements held.

```
.venv/Scripts/python.exe -m pytest tests/test_redteam_round5.py -q
24 passed, 11 xfailed, 0 xpassed
```

The 11 xfails are the findings (R5-01 … R5-10, plus R5-02b, which is R5-02's *gate verdict*
rather than a second leak). The 24 passing tests are CONTROLS, of two kinds, because in this
round "the needle is on no surface" was going to be ambiguous twice over:

* **reachability controls** — the needle is provably present on the expected surface of the
  UNREDACTED package, so "absent from the output" can only mean "removed";
* **contrast controls** — the identical construct in the location the writer DOES cover is
  redacted correctly, so each finding is attributable to the missing traversal rather than to a
  detector that never fired.

Every package built in this round is re-opened through `python-docx` and every XML and `.rels`
part re-parsed, on the SOURCE fixture and again on the OUTPUT, before anything is asserted.
Two fixtures were rejected by that check during development and rebuilt; one is in §5.

**Expectations for all 19 attacks were written and frozen before the first probe ran.** The
"expected" column below has not been edited since.

---

## 2. FINDINGS, RANKED BY SEVERITY

Severity order is the project's: PII survives > document corrupted / partial redaction >
ordinary document wrongly refused > wrong label in the report > over-redaction.

### R5-02 · SEVERITY 1, THE WORST IN THE ROUND — a `w:altChunk` sub-document ships entirely unredacted, Word merges it onto the page, and for a short needle the leak gate scores it CLEAN

`<w:altChunk r:id="rIdAC"/>` is a placeholder for an *entire external document* stored as its
own package part. On open (and on any save) Word parses that part and splices its content into
the document at the placeholder's position. It is how Word stores pasted HTML, how
`Insert > Object > Text from File` stores an inserted file in several code paths, and what
essentially every HTML→DOCX pipeline, mail-merge engine and DMS export emits.

Nothing in `writer/` opens it. `_all_paragraph_elements` walks `.//w:p` under
`doc.element.body` — an `altChunk` contains no `w:p` at all, only a relationship id.

**Reproduction** (`test_r5_02_altchunk_content_is_redacted`): a normal body paragraph
`Predavajuci: Ján Novák.` plus `<w:altChunk r:id="rIdAC"/>` pointing at `word/afchunk.mht`
containing `Kupujuci: Mária Kováčová, rodné číslo 855612/7788, PSC 04001, kod banky 1100.`

```
AssertionError: embedded altChunk document shipped unredacted:
    ['Mária Kováčová', '855612/7788', '04001']
```

Contrast control passes: the body paragraph in the same document IS redacted
(`occurrences == {'[MENO_1]': [('body', 'Ján Novák')]}`), so this is the part nobody opens,
not a detector miss.

**Surface**: `binary_parts`. `eval/extract.py`'s `_XML_PART_RE` matches `.xml`/`.rels`;
`afchunk.mht` is neither, so the chunk is swept as a binary part.

**Does the leak gate see it?** *It depends on the length of the needle, which is the worst
possible answer.* `binary_parts` is in `_OPAQUE_SURFACES`, so the attributability rule applies
(≥ 7 characters AND a non-hex character on both sides). Measured, filed as **R5-02b**:

```
'Mária Kováčová'           counted=('binary_parts',)  -> GATE FAIL
'SK3112000000198742637541' counted=('binary_parts',)  -> GATE FAIL
'04001'                    set_aside=('binary_parts',) -> GATE CLEAN
'1100'                     set_aside=('binary_parts',) -> GATE CLEAN
```

A Slovak PSČ is five digits and a bank code is four. Both are auto-redact types. In an
`altChunk` they are invisible to the gate BY DESIGN — the attributability rule was calibrated
for font tables and xref offsets, structural noise, and is being asked here to grade a
**plain-text HTML document that Word renders on the page**.

**Severity**: LEAK. The premise of the rule in `leak_gate.py` is that opaque surfaces cannot
hold document text. An `altChunk` is a counter-example: document text, on an opaque surface,
rendered to the reader.

**Suggested fix, not implemented.** Two parts, and the second is the important one:

1. In `writer/docx_body.py`, resolve every `altChunk` relationship and either refuse the
   document by name — `UnreadableDocumentError("embedded sub-document (w:altChunk) cannot be
   redacted")` — or drop the element and its part. Given this project's asymmetry, **refusal is
   the honest choice**: silently deleting a merged-in annex is document damage the reviewer
   cannot see.
2. In `eval/extract.py`, stop classifying a part as opaque by *file extension*. An `.mht`,
   `.htm`, `.txt` or nested `.docx` altChunk part is text; give it a surface that is NOT in
   `_OPAQUE_SURFACES`. **Otherwise fix (1) is ungated** — the gate cannot tell whether it worked
   for short needles.

*If the writer half lands without the extractor half,
`test_r5_02_altchunk_content_is_redacted` XPASSes while
`test_r5_02_the_leak_gate_grades_a_short_needle_in_an_altchunk` stays xfail. Both are
`strict=True`, so that split is the signal the fix is half-done rather than the suite going
quietly green.*

### R5-01 · SEVERITY 1 — the first-page and even-page header and footer parts are never redacted, and the letterhead is exactly what lives there

```python
roots = [(doc.element.body, doc, "body")]
for section in doc.sections:
    roots.append((section.header._element, section.header, "header"))
    roots.append((section.footer._element, section.footer, "footer"))
```

`python-docx` 1.2.0's `Section` exposes **six** header/footer properties, not two: `header`,
`footer`, `first_page_header`, `first_page_footer`, `even_page_header`, `even_page_footer`.
Each resolves to its own `w:hdr`/`w:ftr` OPC part. The same omission applies to
`_strip_tracked_changes`, the field-code scrub and the data-binding strip — all iterate the
same two-item list.

`w:titlePg` ("Different first page") is how every law-office letterhead is built: firm name,
address, IČO, fee-earner and client/matter line on page 1, plain page numbers after.
Double-sided filings add `w:evenAndOddHeaders`.

**Reproduction** (`test_r5_01_first_and_even_page_headers_and_footers_are_redacted`):

```
AssertionError: PII survived in non-default header/footer parts:
    [('word/header2.xml', 'Mária Kováčová'),
     ('word/header3.xml', 'Mária Kováčová'),
     ('word/footer2.xml', 'Ján Novák')]
```

Output bytes, `word/header2.xml` (first-page header) after redaction:

```xml
<w:p><w:r><w:t xml:space="preserve">Klient: Mária Kováčová, prva strana</w:t></w:r></w:p>
```

and `word/header1.xml` (the default header) from the *same run*, the contrast control:

```xml
<w:p><w:r><w:t xml:space="preserve">Advokat: </w:t></w:r>
     <w:r><w:t xml:space="preserve">[MENO_1]</w:t></w:r>
     <w:r><w:t xml:space="preserve">, default</w:t></w:r></w:p>
```

A second reproduction covers the first-page-header-only case (`w:titlePg` with no `default`
reference): nothing is redacted and nothing raises.

**Surface**: `header` / `footer` — both TEXT surfaces.
**Does the leak gate see it?** **Yes, with no discount.** The gate has simply never been handed
a document with a first-page header, because `corpus/generate.py` cannot make one.

**Severity**: LEAK, and the highest-frequency one in the round: it fires on *every* document
produced from the office's own template.

**Suggested fix, not implemented.** Enumerate all six, de-duplicated by part identity (a linked
header resolves to the previous section's element and must not be processed twice), and use the
same list for `_strip_tracked_changes`, `_scrub_field_codes` and `_strip_data_bindings`.
**Whichever form the fix takes, it must be the SAME list in all four places** — the four call
sites drifting apart is the root cause of both R5-01 and R5-04.

### R5-03 · SEVERITY 1 — `word/glossary/document.xml`: the cover-page building block is not touched by any pass at all

A Word template ships its cover pages, letterheads and Quick Parts in a *glossary document* — a
second `w:document`-shaped part at `word/glossary/document.xml`, related from `document.xml` by
reltype `glossaryDocument`. Inserting a cover page copies a `w:docPart` out of the glossary into
the body; **the glossary keeps its own copy forever.** A small office that does "Save selection
to the cover page gallery" on a real filing puts a real client's details into the template, and
every document made from it afterwards carries them.

`_redact_docx` knows four kinds of root: the body, header/footer elements, note parts, and the
package-level parts touched by `_scrub_extra_parts`. The glossary is none of them.

**Reproduction** (`test_r5_03_the_building_block_glossary_is_redacted`):

```
AssertionError: building-block glossary shipped unredacted:
    ['Mária Kováčová', '855612/7788', 'JUDr. Ján Novák', 'maria.kovacova@gmail.com']
```

That list is deliberately four different *passes* failing on one part:

| needle | the pass that should have handled it |
|---|---|
| `Mária Kováčová`, `855612/7788` | `_redact_paragraph` (body text) |
| `JUDr. Ján Novák` | `_strip_tracked_changes` (a `w:ins` author) |
| `maria.kovacova@gmail.com` | `_scrub_field_codes` (a `w:fldSimple` HYPERLINK) |

Contrast control passes: the SAME cover-page `w:sdt`/`w:docPartObj` **in the body** is redacted
— content controls are not the problem, the part is.

**Surface**: `other_xml_parts` for the text (a TEXT surface, counts with no discount),
`xml_attributes` for the revision author and the field destination.
Round 1 catalogued this exact part as readable (D-10); nothing ever made the writer scrub it.

**Severity**: LEAK.

**Suggested fix, not implemented.** Treat it as one more root: find the part by reltype, run
`_strip_tracked_changes`, `_scrub_field_codes`, `_strip_data_bindings` and the `.//w:p` walk
over it, and tag its paragraphs with a new location (`"glossary"` — a reviewer needs to know the
hit is in the TEMPLATE, not on the page). It is blob-backed, so it needs the element-vs-`._blob`
asymmetry `_redact_notes_part` already implements; reuse that branch rather than writing a third
copy of it.

### R5-04 · SEVERITY 1 — `_scrub_field_codes` and `_strip_data_bindings` never run on the footnote, endnote or comment parts

```python
for tree in [doc.element] + [hf._element for s in doc.sections for hf in (s.header, s.footer)]:
    _scrub_field_codes(tree, known_entities, config)
    _strip_data_bindings(tree)
```

The three note parts are handled separately by `_redact_notes_part`, which runs `.//w:p` and
nothing else. So R4-T4 and R4-T5 — the two hyperlink field spellings, fixed for the body — are
still live in every footnote. This is the brief's footnote-reference-in-a-table-cell shape, and
it is ordinary: Slovak filings footnote their authorities and their contact addresses.

**Reproduction** (`test_r5_04_field_instructions_in_note_parts_are_scrubbed`):

```
AssertionError: field-code destinations survived in note parts:
    [('word/footnotes.xml', 'maria.kovacova@gmail.com'),
     ('word/footnotes.xml', 'Jan-Novak'),
     ('word/endnotes.xml',  'maria.kovacova@gmail.com')]
```

Two contrast controls make it attributable: the footnote's ordinary TEXT *is* redacted in the
same run, so `_redact_notes_part` reaches the part; and both field spellings in the BODY *are*
scrubbed in an otherwise identical document.

**Surface**: `footnotes` / `endnotes` for the `w:instrText` spelling — a TEXT surface, no
discount, the same "STRICT text surface" argument `_FIELD_TYPES_WITH_PII_ARGS`'s own comment
relies on to justify its recall cost. The `fldSimple` half is opaque.

**Severity**: LEAK.

**Suggested fix, not implemented.** Same fix as R5-01, and it should be the same code: build ONE
list of `(tree, location, writeback)` for every tree the document has — body, all six
header/footer parts, the three note parts, the glossary — and run *every* pass over *every*
entry. Today there are four separate enumerations and each knows a different subset. **That
divergence is the bug; adding a fifth loop would reproduce it.**

### R5-05 · SEVERITY 1 — `docProps/app.xml` leaks every heading in the document, because the scrub is a two-item tag list

```python
_APP_XML_PII_TAGS = ("Company", "Manager")
```

ECMA-376 Part 1 §15.2.12.1: the extended-properties part carries `HeadingPairs` and
`TitlesOfParts`, and **Word populates `TitlesOfParts` with the text of every heading in the
document** — that is how the properties pane and Explorer's preview show a document's outline.
A contract whose Article I reads *"Kúpna zmluva – Mária Kováčová"* ships that string in its
metadata. `HyperlinkBase` is the office's own share path, which on a Windows domain contains the
account name.

**Reproduction** (`test_r5_05_app_xml_free_text_carrying_pii_is_blanked`):

```
AssertionError: docProps/app.xml shipped PII:
    ['Mária Kováčová', 'Petra Horvátha', 'kovacova.maria']
```

```xml
<Company></Company><Manager></Manager>   <!-- contrast control: these DO get blanked -->
<TitlesOfParts><vt:vector size="2" baseType="lpstr">
  <vt:lpstr>Kúpna zmluva – Mária Kováčová</vt:lpstr>
  <vt:lpstr>Splnomocnenie pre Petra Horvátha</vt:lpstr>
</vt:vector></TitlesOfParts>
<HyperlinkBase>\\fileserver\klienti\kovacova.maria</HyperlinkBase>
```

**Surface**: `app_xml` — a NAMED, non-opaque surface. The control asserts the gate verdict
directly: `counted == ('app_xml',)`, `set_aside == ()`.
**Does the leak gate see it?** **Yes, no discount whatsoever.** Reachable since v1.0.

**Severity**: LEAK.

**Suggested fix, not implemented.** Stop enumerating tags. `app.xml` is an application's private
bookkeeping part that no reviewer reads, so the asymmetry this tool is built on says: blank
every free-text value BY POSITION, exactly as `_scrub_extra_parts` already does for
`customXml/item*.xml`. Keep the numeric/structural elements Word validates against (`Pages`,
`Words`, `Characters`, `Lines`, `Paragraphs`, `DocSecurity`, `ScaleCrop`, `LinksUpToDate`,
`SharedDoc`, `HyperlinksChanged`, `AppVersion`, `Application`, `Template`) and blank the rest,
including every `vt:lpstr` inside `TitlesOfParts`. Do it with `lxml`, not a regex — see R5-06.

### R5-06 · SEVERITY 2 — the `app.xml` scrub is a regex over raw XML and is blind to namespace prefixes

```python
xml = part._blob.decode("utf-8")
for tag in _APP_XML_PII_TAGS:
    xml = re.sub(rf"<{tag}>.+?</{tag}>", f"<{tag}></{tag}>", xml, flags=re.DOTALL)
```

`<ep:Company>` and `<Company>` are the same element in XML and different strings in a regex. The
docstring's justification — "so every unrelated tag is byte-preserved" — is a real concern, but
`lxml` preserves what it does not touch just as well, and this is the only scrub in the writer
that parses XML with a regular expression; every other branch uses Clark names and is
prefix-safe.

**Reproduced by hand from the OOXML spec**, not captured from a real exporter: LibreOffice is
not installed on this machine (QUESTIONS.md Q18). The fixture control asserts both spellings
resolve to the same expanded names. It is *representative of* a foreign producer's idiom and is
ranked below R5-05 for exactly that reason. **No finding in this round depends on an unverified
claim about what LibreOffice emits.**

```
AssertionError: prefixed app.xml was not scrubbed: ['Ján Novák', 'Mária Kováčová']
```

**Severity**: LEAK. **Suggested fix**: fold into R5-05 — parse with `lxml`, match on the
expanded name, blank by position.

### R5-07 · SEVERITY 2 — attribute-borne PII: alt text, bookmark names, content-control aliases, dropdown lists and legacy form-field defaults

The only attribute sweep in the writer is the blanket added for R4-M4b: two attribute names
(`w:author`, `w:initials`), on trees the writer happens to visit. Word stores far more free text
in attributes. All of the following survive redaction in a single document:

```
AssertionError: attribute values shipped PII:
    ['Podpis klienta: Ján Novák',   # wp:docPr/@descr   — scanned-signature alt text
     'Peciatka: Mária Kováčová',    # v:shape/@alt      — legacy VML stamp
     'Adresa_Maria_Kovacova',       # w:bookmarkStart/@w:name
     'Klient: Ján Novák',           # w:sdtPr/w:alias/@w:val
     'klient_jan_novak',            # w:sdtPr/w:tag/@w:val
     'Peter Horváth',               # w:dropDownList/w:listItem/@w:displayText
     'Meno klienta: Ján Novák']     # w:ffData/w:statusText/@w:val
```

plus `w:textInput/w:default/@w:val` and `w:dropDownList/@w:lastValue` in the same output.

**This is the brief's `w:showingPlcHdr` shape, and it is worse than it sounds.** The control in
the fixture carries `<w:showingPlcHdr/>`, so the page displays *"Kliknite sem a zadajte meno."*
— a placeholder with no personal data. The reviewer sees a clean page. The selected client and
**the office's entire client list** sit in the `w:sdtPr` attributes underneath. The contrast
control confirms the visible plane is handled: the `FORMTEXT` result run the reader actually
sees IS redacted to `[MENO_1]`.

**Surface**: `xml_attributes` — OPAQUE. **Gate: only above 7 characters.** A control measures the
boundary directly: `alt="Klient Ján"` → `counted=()`, `set_aside=('xml_attributes',)`. So a first
name, a four-digit bank code, a five-digit PSČ or a short surname in an alt text is a leak the
gate scores CLEAN.

Note the asymmetry with round 1: the extractor was taught to READ `wp:docPr/@descr` (D-01/D-02,
closed) and the writer was never taught to REMOVE it. Same extractor–writer asymmetry round 4
found for `settings.xml`, `custom.xml` and `people.xml` — this is its attribute plane.

**Severity**: LEAK. **Suggested fix**: extend the existing blanket sweep rather than adding
another whitelist — the R4-M4b comment already argues that case and it applies verbatim. Blank
by position on every tree the writer visits: `wp:docPr`/`pic:cNvPr`/`a:cNvPr` `@descr @title
@name`; `v:shape`/`v:image`/`v:rect` `@alt @title`; `w:bookmarkStart/@w:name` **except** names
starting `_` (Word's own `_Toc`/`_Ref`/`_GoBack` namespace — renaming those breaks the TOC, see
R5-08 for what that costs); `w:alias`/`w:tag/@w:val`; `w:dropDownList`/`w:comboBox` `@w:lastValue`
and `w:listItem/@w:displayText @w:value`; `w:ffData` name/statusText/helpText/default/listEntry;
`w:smartTagPr/w:attr/@w:val`.

The `w:listItem` case deserves a note: removing the list items changes what the control
*offers*, which is a behaviour change, not just a redaction. Blanking the attributes in place
keeps the structure Word validates and empties the data — the same choice `_scrub_extra_parts`
made for `customXml`, for the same reason.

### R5-08 · DOCUMENT DAMAGE — the `_Ref`/`_Toc` exemption tests the BARE token only, and Word writes a TOC hyperlink with the bookmark name QUOTED

**FIXED 2026-09-17, daytime run — see the note at the end of this entry.**

`_scrub_field_instruction` carries a long, correct, measured comment about how a blanket rule
destroyed roughly every second cross-reference and TOC entry in a real document, and how the fix
is to exempt Word's internal bookmark namespace. The exemption was:

```python
if bare is not None and (bare.startswith("\\") or bare.startswith("_")):
```

`bare is not None` — so a **quoted** `"_Toc53871234"` was not exempt. The docstring stated the
reasoning out loud: *"a switch is always written bare (`\* MERGEFORMAT`) and so is a bookmark
name (`_Ref53871234`)"*. The second half is false. Word writes a TOC entry with `\h` as:

```xml
<w:instrText xml:space="preserve"> HYPERLINK \l "_Toc53871234" </w:instrText>
```

Same for a `\h` cross-reference rendered as a HYPERLINK field. The bare spelling the earlier
round tested is what `REF` and `PAGEREF` use — and neither is in `_FIELD_TYPES_WITH_PII_ARGS`,
so the exemption never had to fire for them at all.

```
AssertionError: ordinary Word cross-references destroyed:
    [' HYPERLINK \l "_Toc53871234" ', ' HYPERLINK \l "_Ref53871234" ',
     ' HYPERLINK \l "_Toc5387123456" ']
```

Digit-count sweep, the same coin flip R4 documented:

```
"_Toc538712"      (6)  ok          _Toc538712      (6)  ok
"_Toc5387123"     (7)  ok          _Toc5387123     (7)  ok
"_Toc53871234"    (8)  DESTROYED   _Toc53871234    (8)  ok
"_Toc538712345"   (9)  ok          _Toc538712345   (9)  ok
"_Toc5387123456" (10)  DESTROYED   _Toc5387123456 (10)  ok
```

Eight digits is the IČO shape; ten is a rodné číslo shape.

**Does the leak gate see it?** **No, and it cannot.** `eval/leak_gate.py` grades *surviving PII*,
never *destroyed content*. A broken table of contents is invisible to every gate in this repo and
invisible to the reviewer too, because the *displayed* TOC text is unchanged — only the link
behind it is dead. Precisely the failure mode R4-R1 named: "a tool that breaks every working link
in a contract gets switched off, and the links it breaks are the ones the reviewer never sees."

**Severity**: DOCUMENT DAMAGE, on an entirely ordinary document. A Slovak `kúpna zmluva`,
`spoločenská zmluva` or `žaloba` of any length has a `TOC \h` field.

**PROVENANCE, recorded because it matters more than the fix.** This was an ORCHESTRATOR SPEC
ERROR, not an implementation slip. When the first field-code scrub was rejected on review that
morning, the exemption was specified as "a **bare** (unquoted) argument beginning with `_`, since
that is Word's internal bookmark namespace". The implementing round built exactly that. The
parenthesis is the bug, and the docstring faithfully records the false premise it was given.
A spec defect found by measurement is the loop working; it belongs in the deviation log, not on
a kill counter.

**Fix as landed.** The two exemptions are NOT symmetric, and both halves now say why: the
BACKSLASH test stays on the bare token, because a quoted argument starting with a backslash is a
UNC path and is a destination this must examine (`INCLUDETEXT "\\fileserver\users\jan.novak\..."`,
pinned by `tests/test_docx_field_codes.py`); the BOOKMARK test moved to the VALUE, matched against
`^_(?:Toc|Ref|GoBack|Hlk)\w*$` so an argument that merely happens to start with an underscore is
still examined.

### R5-09 · DOCUMENT DAMAGE — `_TEXT_BEARING` disagrees with `python-docx`'s own `run.text` in BOTH directions

`_TEXT_BEARING` is documented as "the `<w:r>` children that CONTRIBUTE CHARACTERS to `run.text`,
and therefore to the offsets `detect()` is given", and `_rebuild_run` removes exactly that set
from each cloned fragment. The set is
`{w:t, w:tab, w:br, w:cr, w:noBreakHyphen, w:softHyphen, w:delText}`.

`python-docx` 1.2.0's `CT_R.text` is:

```python
return "".join(str(e) for e in self.xpath("w:br | w:cr | w:noBreakHyphen | w:ptab | w:t | w:tab"))
```

Two mismatches, in opposite directions, both measured by a fixture control before any redaction:

* **`w:ptab` renders as `"\t"` and is NOT in `_TEXT_BEARING`.** So it is cloned into *every*
  fragment (the exact bug the comment says was fixed for `w:t`) *and* the tab it contributed is
  separately re-emitted as `<w:tab/>`.
* **`w:softHyphen` renders as `""` and IS in `_TEXT_BEARING`.** Stripped from every clone and
  never re-emitted — silently deleted.
* Third, milder: `w:noBreakHyphen` renders as `"-"`, is in the set, and the split regex only
  splits `\t` and `\n` — so it comes back as a literal hyphen-minus inside a `<w:t>`, i.e. a
  *non-breaking* hyphen downgraded to a breaking one.

```
AssertionError: run rebuild damaged inner content:
    ['w:ptab duplicated: 2 copies',
     'w:ptab additionally re-emitted as a plain w:tab',
     'w:softHyphen deleted from the rebuilt run',
     'w:noBreakHyphen downgraded to a literal hyphen-minus']
```

```xml
<!-- in  --> <w:r><w:t>Ján Novák</w:t><w:ptab w:alignment="right" w:leader="dot"/><w:t>strana 1</w:t></w:r>
<!-- out --> <w:r><w:ptab w:alignment="right" w:leader="dot"/><w:t>[MENO_1]</w:t></w:r>
             <w:r><w:ptab w:alignment="right" w:leader="dot"/><w:tab/><w:t>strana 1</w:t></w:r>
```

`w:ptab` is Word's **Alignment Tab** — what puts the page number at the right margin of a header
and the leader dots in a TOC line. A header reading `Advokát Ján Novák ......... strana 1` hits
this on the first redaction.

**Gate**: no. There is no formatting-integrity check that would notice a duplicated position tab.

**Severity**: DOCUMENT DAMAGE, low-to-moderate — the output opens and reads correctly, but the
line's alignment shifts and the hyphenation point is gone.

**Suggested fix, not implemented.** Do not hand-maintain the set — DERIVE it from the library
that defines it, extend the re-emission so a `"\t"` reconstructs the element it came from
(remembering per fragment whether it was `w:tab` or `w:ptab`, and with which attributes), and
re-emit `w:noBreakHyphen` as itself. `w:softHyphen` contributes nothing to `run.text`, so it
should simply LEAVE the set — it is not text-bearing, and removing it from the clone is what
deletes it. Pin the whole thing with a test asserting `_TEXT_BEARING` equals the xpath `CT_R.text`
actually uses, so a `python-docx` upgrade that adds an inner-content element turns the suite red
instead of silently corrupting documents.

### R5-10 · CONTRACT DEFECT / REFUSAL — a `docProps/app.xml` that is not UTF-8 leaves the writer as `UnicodeDecodeError`

```python
xml = part._blob.decode("utf-8")
```

No `errors=`, no guard. `context.md` §3 promises a refusal the reviewer can act on, and R4-X3
introduced `_open_docx` and the `.rels` guard to deliver exactly that. `app.xml` slips past both:
`python-docx` never parses it, so `_open_docx` succeeds, and it is not a `.rels` part.

The part in the fixture is **valid XML** — it declares `encoding="windows-1250"` and `lxml` reads
the Slovak text back correctly (fixture control asserts this). It is simply not UTF-8, which is
what an RTF→DOCX converter or a legacy Central-European court system produces.

```
Failed: writer raised UnicodeDecodeError instead of UnreadableDocumentError:
    'utf-8' codec can't decode byte 0xe1 in position 166: invalid continuation byte
```

Measured mitigation: `_scrub_metadata` runs **before** `doc.save()`, so no output file is left on
disk (asserted in the test). The damage is the message, not a half-redacted file.

**Severity**: FALSE REFUSAL class (a stack trace where a named refusal was promised). Ranked last
because nothing leaks and nothing is written. Related to R4-X3 — same contract clause, different
function, different door — and reported as such rather than as an independent discovery.

**Suggested fix, not implemented.** The R5-05/R5-06 fix subsumes it: parse `app.xml` with
`etree.fromstring(part._blob)`, which honours the XML declaration's encoding, and wrap
`_scrub_metadata` so any decode/parse failure becomes `UnreadableDocumentError`. Do **not** paper
over it with `decode("utf-8", "replace")` — that would silently mojibake the part and write the
result back, which is R4's cp1250 finding in reverse.

---

## 3. WHAT DID NOT REPRODUCE

Recorded so nobody re-runs them. Each is a PASSING test, marked as a control.

| attack | result | why it holds |
|---|---|---|
| `w:del` nested inside `w:ins` | **CLEAN** | `_strip_tracked_changes` removes every `w:del` subtree first, then promotes `w:ins`; the author on both is blanked. |
| legacy VML `v:shape`/`v:textbox` with no DrawingML twin | **CLEAN** | the `.//w:p` walk reaches the `w:txbxContent` paragraph; occurrence recorded as `('textbox', …)`. |
| `w:customXmlElement` splitting a name mid-sentence without splitting the run | **CLEAN** | `_paragraph_runs` collects `.//w:r` and filters by nearest `w:p`; the wrapper is transparent. Round 4 predicted this for `w:smartTag`; `w:customXmlElement` is measured here for the first time. |
| threaded comments (`w15:commentEx` parent/child) + `word/people.xml` | **CLEAN** | a reply is an ordinary `w:comment`. Text redacted, authors blanked, `people.xml` stripped by R4-M3. |
| `w:hyperlink r:id` inside a footnote, target in `word/_rels/footnotes.xml.rels` | **CLEAN** | `_scrub_rel_targets` sweeps **every** `.rels` part in the saved package, not only the document's. (The FIELD-CODE spelling of the same link is R5-04 — **the two spellings get opposite answers**, which is worth noticing.) |
| nested `w15:repeatingSection` content controls | **CLEAN** | the descendant walk reaches each repeated item's paragraph. |
| `w:sdt`/`w:docPartObj` cover page in the BODY | **CLEAN** | redacted normally. R5-03 is about the glossary copy. |
| the main document part at a non-standard name (`word/telo.xml`) | **CLEAN as a leak** | OPC permits it and `python-docx` resolves it through `_rels/.rels`. One line for a future round: `eval/extract.py` hard-codes `word/document.xml`, so such a body is reported on `other_xml_parts` — a surface-naming nuance that still grades as a leak. |

---

## 4. EXPECTATIONS THAT WERE WRONG

* **F2 was right for the wrong reason.** `_TEXT_BEARING` is missing one element (`w:ptab`) *and*
  contains one that does not belong (`w:softHyphen`) — so the set was never checked against the
  library at all; it was written from the docstring's *description* of what `run.text` does. The
  fix has to be derivation, not another hand-edit.
* **The `altChunk` text was expected to land on a surface the gate grades.** It does, for a long
  needle; it does not, for a short one. That distinction only became visible because the fixture
  carried a PSČ and a bank code alongside the name. **A fixture with one long name in it would
  have recorded R5-02 as "the gate catches it"** — wrong, and it would have sent the fix in the
  wrong direction (writer only, no extractor change).
* **N2 was expected to be a second finding.** `_scrub_rel_targets` sweeps the whole package; its
  docstring undersells it. Stated CLEAN in advance and it held.
* **A first-page-header-only document was expected to RAISE.** It does not; `python-docx` returns
  a fresh empty definition. Nothing is redacted and nothing complains, **which is worse than
  raising.**

---

## 5. WHAT THIS ROUND GOT WRONG ABOUT ITSELF — fixture defects, not product defects

* **The header fixture's `[Content_Types].xml` override used `…wordprocessingml.hdr+xml` instead
  of `…wordprocessingml.header+xml`.** `python-docx` mapped the part to a generic `Part` with no
  `.element`, and the writer raised `AttributeError` — which looks exactly like a product defect
  ("the writer crashes on a document with headers"). The re-open check did NOT catch it, because
  the package IS well-formed; only the *contrast control* failed, which is what contrast controls
  exist for. **If this round had shipped only the xfail tests, that content-type typo would have
  been filed as a finding.**
* The first `HYPERLINK \l` reproduction used `_Toc190324500` — nine digits — and survived, so the
  first read of R5-08 was "does not reproduce". The digit sweep is what turned it into a finding,
  and it is in the test file so the next round does not rediscover it.
* `_ATTR_NEEDLES` originally included `"Ján Novák"` on its own, a substring of `"Podpis klienta:
  Ján Novák"`, which would have made the assertion unfalsifiable by the alt text alone.

---

## 6. JUDGEMENT CALLS

* **R5-02b is a sub-finding of R5-02, not its own row** — the same defect *graded*, not a second
  defect. The xfail count is therefore 11 for 10 findings.
* **R5-05 and R5-06 are filed separately** although one fix closes both. Different mechanisms: an
  incomplete tag list (fires on Word's own output) and a regex parsing XML (fires on a foreign
  producer). Merging them would let the first be "fixed" by adding tags to the list, leaving the
  second live.
* **R5-07 is one finding with eight reproductions**, not eight findings: one root cause (there is
  no attribute policy, only a two-attribute patch) and one fix. Splitting them would inflate the
  count.
* **No `xfail(strict=False)` anywhere.** Every finding fails today; if one starts passing the
  suite goes red, which is the point.

---

## 7. SUSPECTED, NOT CONFIRMED

* **`word/embeddings/oleObject*.bin`** — an embedded Word/Excel object (a payment schedule pasted
  as an object, common in Slovak loan agreements) is an OLE compound file holding its own document
  text as UTF-16LE. The extractor reads it (`binary_parts`), nothing scrubs it, and it is subject
  to the same attributability discount as R5-02. No valid OLE storage was built by hand, so this
  is a suspicion. **It is almost certainly R5-02 through a different door and should be tested
  with the same fix.**
* **`word/numbering.xml` `w:lvlText`** — a numbering definition can carry literal text. Low
  realism; not built.
* **`w:sdt` inside a note part** — the note parts get paragraphs only, so anything structural in
  them is as unhandled as the field codes in R5-04. The R5-04 fix should cover it.
* **A `.dotx` carries `word/glossary/_rels/` and its own media.** If the R5-03 fix lands, it needs
  to sweep those too, not just `document.xml`.
* **The corpus still cannot express a single shape attacked in this round.** Every finding needed
  a hand-authored package. Until `corpus/generate.py` can emit a first-page header, a content
  control and a footnote field code, `eval/leak_gate.py`'s green verdict is a statement about
  `python-docx`'s output, not about the office's documents. That is the structural observation
  behind all five rounds, and it is the one thing on this list that is not a bug.

---

## 8. THE ROUND'S HEADLINE

**R5-02 (`w:altChunk`)** — and not because it is the biggest leak. R5-01 fires on more documents.
It is the most dangerous because it is the only one where **the gate and the reviewer fail in the
same direction at the same time.**

R5-01 leaks a letterhead, but the gate would flag it the moment a first-page header entered the
corpus. R5-05 leaks headings, but on a named text surface with no discount. R5-07 leaks
attributes, but the reviewer is at least looking at a document whose visible plane is correct.

With `altChunk`: a paralegal pastes a block of HTML out of Outlook or the cadastre portal into a
draft; Word stores it as a separate part and merges it into the page at open. The tool redacts
the body around it, writes a report listing the occurrences it removed, and ships an output that
**displays the client's full name, rodné číslo and address to the next person who opens it** —
while the report says the document was redacted. The reviewer reads the report, not the ZIP. And
the leak gate's answer depends on how long the needle happens to be: `Mária Kováčová` is caught,
`04001` and `1100` are set aside as noise, because `binary_parts` was classified opaque on the
assumption that binary parts cannot hold document text. **That assumption is exactly what
`altChunk` breaks.**

That is the class the brief asks to hunt — *the gate says CLEAN and it is not* — and it says so
for a structural reason rather than a threshold that can be nudged.

The fix must be BOTH HALVES. If the writer half lands without the extractor half, the writer is
fixed and ungated: short needles stay invisible and nobody would know.
