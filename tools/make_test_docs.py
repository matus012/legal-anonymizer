"""Build the owner's 17:00 smoke-test kit: three synthetic Slovak legal .docx files plus a
Slovak README, written into ``test_docs/`` (context.md; brief 2026-09-17).

    .\\.venv\\Scripts\\python.exe -m tools.make_test_docs

Dev-only. Every name, number and address below is INVENTED (context.md §7). Every
checksum-bearing identifier (rodné číslo, IBAN, IČO) is checked against the real
implementation in ``detect/identifiers.py`` before it is written anywhere, and the result is
printed — a smoke test built on a checksum that would not even pass its own detector proves
nothing about the checksum path.

The three files:
  * ``test_doc_1_bezna_zmluva.docx``   — plain python-docx, the "does it work at all" case.
  * ``test_doc_2_word_tvary.docx``     — python-docx base, then RAW OOXML SURGERY (lxml) to
    plant PII in six shapes python-docx cannot itself emit: a hyperlink target, a content
    control, a nested table, a text box, a tracked insertion/deletion, and a custom
    document property.
  * ``test_doc_3_tazke_tvary.docx``    — the three hard shapes fixed on 2026-09-17: the
    caps-surname convention, a declined Slovak street name, and a two-word field label split
    across a line break — plus a non-breaking space and a soft hyphen inside an identifier.

``verify(out_dir)`` runs the REAL GUI pipeline (``gui.model.scan_file`` / ``build_decisions`` /
``export_file``) over the three files and checks every needle below through
``eval/extract.py`` — the same exhaustive, every-OPC-part extractor the leak gate uses — never
by re-reading the file a second, different way. Both the needle and the haystack are flattened
identically (Unicode category Cf stripped, whitespace collapsed) before comparison, and a
POSITIVE CONTROL per document proves the extractor is actually reading something.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import unicodedata
import zipfile
from pathlib import Path

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from lxml import etree

from detect import identifiers as ident
from detect.normalize import strip_format_chars
from eval.extract import extract
from gui.model import build_decisions, export_file, scan_file

TEST_DIR = Path("test_docs")

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
V_NS = "urn:schemas-microsoft-com:vml"

NBSP = " "
SHY = "­"  # soft hyphen — Unicode category Cf, invisible, no glyph


# =========================================================================== checksum values
# Every identifier below is COMPUTED to satisfy its own checksum (or deliberately computed
# and then punctured with an invisible character — see test_doc_3), never typed by hand and
# hoped valid. ``_check`` calls straight into detect/identifiers.py's own (private, but this
# is the same package) checksum functions and PRINTS the verdict, per the brief.

def _check_rc(digits: str) -> str:
    ok = ident._rc_checksum_ok(digits) if len(digits) == 10 else True
    tag = "n/a (9-digit, pre-1954)" if len(digits) == 9 else ("valid" if ok else "INVALID")
    print(f"  RODNE_CISLO  {digits:<12} mod-11 checksum: {tag}")
    assert len(digits) == 9 or ok, f"invented RC {digits} fails mod-11"
    return digits


def _check_ico(digits: str) -> str:
    ok = ident._ico_checksum_ok(digits)
    print(f"  ICO          {digits:<12} weighted mod-11 checksum: {'valid' if ok else 'INVALID'}")
    assert ok, f"invented ICO {digits} fails its checksum"
    return digits


def _check_iban(compact: str) -> str:
    ok = ident._iban_mod97_ok(compact)
    print(f"  IBAN         {compact:<26} mod-97 checksum: {'valid' if ok else 'INVALID'}")
    assert ok, f"invented IBAN {compact} fails mod-97"
    return compact


def _iban_grouped(compact: str) -> str:
    """Standard IBAN display grouping: 4 characters at a time from the very start of the
    string (``SK`` + the 2 check digits count as the first group), matching what a bank
    portal prints and what ``detect/identifiers.py``'s ``_IBAN_RE`` requires (SK + 2 check
    digits, then exactly five 4-digit groups)."""
    return " ".join(compact[i:i + 4] for i in range(0, len(compact), 4))


def _rc_slashed(digits: str) -> str:
    return f"{digits[:6]}/{digits[6:]}"


# Computed once, printed once (see main()), reused everywhere below.
RC1_M = _check_rc("8503150007")   # Ján Novák, 15.3.1985
RC1_F = _check_rc("9061220003")   # Mária Kováčová, 22.11.1990 (month+50 = female)
ICO1 = _check_ico("36500003")     # Stavebniny Tatry, s.r.o.
IBAN1 = _check_iban("SK0011000012000000000001")

RC2_SDT = _check_rc("7201010003")   # Elena Sokolová, content-control witness
RC2_DEL = _check_rc("9004100006")   # tracked-deletion RC
IBAN2 = _check_iban("SK3112000001000000000001")
ICO2 = _check_ico("44000006")       # docProps/custom.xml

RC3_M = _check_rc("8503150007")     # Ján NOVÁK (same person, different document)
ICO3 = _check_ico("44000006")       # punctured with a soft hyphen in the document body


# =========================================================================== doc 1 — ordinary
DOC1_PARAGRAPHS = [
    "Kúpna zmluva o prevode nehnuteľnosti",
    "uzavretá podľa § 588 a nasl. Občianskeho zákonníka",
    "",
    "Článok I — Zmluvné strany",
    "Predávajúci: JUDr. Ján Novák",
    f"Rodné číslo: {_rc_slashed(RC1_M)}",
    "Dátum narodenia: 15.3.1985",
    "Trvale bytom: Štúrova 15, 811 06 Bratislava",
    "Telefón: 0905 123 456",
    "E-mail: jan.novak@pravnik.sk",
    "",
    "Kupujúci: Ing. Mária Kováčová",
    f"Rodné číslo: {_rc_slashed(RC1_F)}",
    "Dátum narodenia: 22.11.1990",
    "Bydlisko: Hlavná 12/A, 040 01 Košice",
    "Telefón: 0911 402 917",
    "E-mail: maria.kovacova@pravnik.sk",
    "",
    "Vedľajší účastník: Stavebniny Tatry, s.r.o.",
    f"IČO: {ICO1}, DIČ: 2020123456, IČ DPH: SK2020123456",
    "",
    "Článok II — Predmet zmluvy",
    "Nehnuteľnosť zapísaná na LV č. 4521, parc. č. 892/3,",
    "v katastrálnom území Košice - Staré Mesto.",
    "Kúpna cena je 158 500,00 EUR.",
    "",
    "Článok III — Platobné údaje",
    f"IBAN: {_iban_grouped(IBAN1)}",
    "",
    "Článok IV — Záverečné ustanovenia",
    "Zmluvné strany vyhlasujú, že si túto zmluvu prečítali a s jej obsahom súhlasia.",
]


def build_doc1(path: Path) -> None:
    doc = Document()
    for line in DOC1_PARAGRAPHS:
        doc.add_paragraph(line)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).paragraphs[0].add_run("Rodné číslo predávajúceho")
    table.cell(0, 1).paragraphs[0].add_run(_rc_slashed(RC1_M))
    table.cell(1, 0).paragraphs[0].add_run("Telefón kupujúcej")
    table.cell(1, 1).paragraphs[0].add_run("0911 402 917")
    section = doc.sections[0]
    section.header.paragraphs[0].add_run("Kúpna zmluva — Ján Novák")
    section.footer.paragraphs[0].add_run("Kontakt: maria.kovacova@pravnik.sk")
    doc.core_properties.author = "JUDr. Ján Novák"
    doc.core_properties.company = "Stavebniny Tatry, s.r.o."
    doc.save(str(path))


NEEDLES_1 = [
    "Ján Novák", "Mária Kováčová",                                    # MENO
    _rc_slashed(RC1_M), _rc_slashed(RC1_F),                           # RODNE_CISLO
    "15.3.1985", "22.11.1990",                                        # DATUM (birth)
    "Štúrova 15", "Hlavná 12/A", "811 06", "040 01",                  # ADRESA + PSC
    "Bratislava", "Košice",                                           # OBEC / KATASTER
    "0905 123 456", "0911 402 917",                                   # TELEFON
    "jan.novak@pravnik.sk", "maria.kovacova@pravnik.sk",              # EMAIL
    "Stavebniny Tatry, s.r.o.",                                       # ORG
    ICO1, "2020123456", "SK2020123456",                               # ICO / DIC / IC_DPH
    _iban_grouped(IBAN1),                                             # IBAN
    "4521", "892/3",                                                  # LV / PARCELA
]
POSITIVE_CONTROL_1 = "Článok I"


# =========================================================================== doc 2 — word tvary
DOC2_PARAGRAPHS = [
    "Kúpna zmluva",
    "uzavretá podľa § 588 a nasl. Občianskeho zákonníka",
    "",
    "Článok I — Zmluvné strany",
    "Predávajúci: Peter Dvorák, Kupujúca: Zuzana Bieliková.",
    "",
    "Nasledujúce údaje sú súčasťou tohto dokumentu vo formátoch, ktoré",
    "bežný textový editor nevytvorí priamo (hypertextový odkaz, formulárové",
    "pole, vnorená tabuľka, textové pole a sledované zmeny):",
]

EMAIL2 = "maria.kovacova@klient.sk"
NAME2_SDT = "Elena Sokolová"
ADDR2 = "Kollárova 9, 917 01 Trnava"
PHONE2 = "0908 555 111"
AUTHOR2 = "Tomáš Zelinka"


def _insert_before_sectpr(body: etree._Element, xml: str) -> None:
    sect_pr = body.find(f"{{{W_NS}}}sectPr")
    el = etree.fromstring(xml)
    if sect_pr is not None:
        sect_pr.addprevious(el)
    else:
        body.append(el)


def _inject_custom_property(path: Path, name: str, value: str) -> None:
    """Add ``docProps/custom.xml`` to an already-saved .docx — python-docx has no API for
    custom document properties at all, so this is genuine OPC package surgery: a new part,
    a Content_Types override and a package-level relationship, none of which python-docx
    will write on its own."""
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}

    ct = parts["[Content_Types].xml"].decode("utf-8")
    if "/docProps/custom.xml" not in ct:
        ct = ct.replace(
            "</Types>",
            '<Override PartName="/docProps/custom.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.custom-properties+xml"/>'
            "</Types>",
        )
    parts["[Content_Types].xml"] = ct.encode("utf-8")

    rels = parts["_rels/.rels"].decode("utf-8")
    if "docProps/custom.xml" not in rels:
        rels = rels.replace(
            "</Relationships>",
            '<Relationship Id="rIdCustomProps" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties" '
            'Target="docProps/custom.xml"/></Relationships>',
        )
    parts["_rels/.rels"] = rels.encode("utf-8")

    parts["docProps/custom.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" '
        f'name="{name}"><vt:lpwstr>{value}</vt:lpwstr></property>'
        "</Properties>"
    ).encode("utf-8")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, blob in parts.items():
            z.writestr(n, blob)


def build_doc2(path: Path) -> None:
    doc = Document()
    for line in DOC2_PARAGRAPHS:
        doc.add_paragraph(line)
    body = doc.element.body

    # 1. a run inside a <w:hyperlink> whose relationship TARGET carries the PII — the display
    # text is deliberately clean, so only the .rels target leaks.
    rid = doc.part.relate_to(f"mailto:{EMAIL2}", RT.HYPERLINK, is_external=True)
    _insert_before_sectpr(
        body,
        f'<w:p xmlns:w="{W_NS}" xmlns:r="{R_NS}">'
        f'<w:hyperlink r:id="{rid}"><w:r><w:t>kontaktný e-mail klientky</w:t></w:r></w:hyperlink>'
        "</w:p>",
    )

    # 2. a paragraph inside a content control (<w:sdt>/<w:sdtContent>) — a Word template
    # fill-in field, which python-docx can read but never write.
    _insert_before_sectpr(
        body,
        f'<w:sdt xmlns:w="{W_NS}"><w:sdtPr><w:alias w:val="Svedok"/><w:id w:val="1001"/></w:sdtPr>'
        f"<w:sdtContent><w:p><w:r><w:t>Rodné číslo svedka {NAME2_SDT}: "
        f"{_rc_slashed(RC2_SDT)}</w:t></w:r></w:p></w:sdtContent></w:sdt>",
    )

    # 3. a paragraph in a NESTED table (a <w:tbl> inside a table cell).
    outer = doc.add_table(rows=1, cols=1)
    outer_tc = outer.cell(0, 0)._tc
    inner_tbl = etree.fromstring(
        f'<w:tbl xmlns:w="{W_NS}"><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
        '<w:tblGrid><w:gridCol w:w="4000"/></w:tblGrid>'
        '<w:tr><w:tc><w:tcPr><w:tcW w:w="4000" w:type="dxa"/></w:tcPr>'
        f"<w:p><w:r><w:t>Trvale bytom: {ADDR2}</w:t></w:r></w:p>"
        "</w:tc></w:tr></w:tbl>"
    )
    outer_tc.append(inner_tbl)

    # 4. a text box (<w:txbxContent>), the legacy VML shape.
    _insert_before_sectpr(
        body,
        f'<w:p xmlns:w="{W_NS}"><w:r><w:pict xmlns:v="{V_NS}">'
        '<v:shape style="width:200pt;height:40pt">'
        f"<v:textbox><w:txbxContent><w:p><w:r><w:t>Telefón: {PHONE2}</w:t></w:r></w:p>"
        "</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>",
    )

    # 5. a tracked insertion (<w:ins>) and a tracked deletion (<w:del>).
    _insert_before_sectpr(
        body,
        f'<w:p xmlns:w="{W_NS}"><w:ins w:id="10" w:author="{AUTHOR2}" '
        f'w:date="2026-09-17T00:00:00Z"><w:r><w:t>Doplnené dodatočne: IBAN '
        f"{_iban_grouped(IBAN2)}</w:t></w:r></w:ins></w:p>",
    )
    _insert_before_sectpr(
        body,
        f'<w:p xmlns:w="{W_NS}"><w:del w:id="11" w:author="{AUTHOR2}" '
        f'w:date="2026-09-17T00:00:00Z"><w:r><w:delText>Vymazané: RČ '
        f"{_rc_slashed(RC2_DEL)}</w:delText></w:r></w:del></w:p>",
    )

    doc.save(str(path))

    # 6. a document property in docProps/custom.xml — needs real OPC surgery (see above),
    # done AFTER save because python-docx cannot write this part through any public API.
    _inject_custom_property(path, "ICOKlienta", ICO2)


NEEDLES_2 = [
    EMAIL2,                              # hyperlink relationship target (mailto:)
    _rc_slashed(RC2_SDT), NAME2_SDT,     # content control (w:sdt)
    "Kollárova 9", "917 01", "Trnava",   # nested table
    PHONE2,                              # text box (VML)
    _iban_grouped(IBAN2),                # tracked insertion (w:ins)
    _rc_slashed(RC2_DEL),                # tracked deletion (w:del)
    ICO2,                                # docProps/custom.xml property
]
POSITIVE_CONTROL_2 = "Kúpna zmluva"


def assert_package_intact(path: Path) -> int:
    """Re-open the finished package and prove every XML/rels part still parses and the part
    list is intact. A file the surgery has corrupted proves nothing about the writer's
    behaviour on it — Word would refuse to open it, and so would python-docx on the next scan.
    Returns the part count; raises on the first malformed part."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert "docProps/custom.xml" in names, "custom.xml surgery did not land"
        assert "word/document.xml" in names, "part list lost the main document part"
        for name in names:
            if name.endswith(".xml") or name.endswith(".rels"):
                etree.fromstring(z.read(name))  # raises lxml.etree.XMLSyntaxError if broken
    return len(names)


# =========================================================================== doc 3 — hard shapes
DOC3_PARAGRAPHS = [
    "Notárska zápisnica o osvedčení podpisu",
    "Notár osvedčuje podpisy nasledujúcich osôb na tejto listine:",
    "",
    "Článok I — Účastníci konania",
    "Predávajúci: Ján NOVÁK, bytom na Hlavnej ulici 5, Košice.",
    f"Rodné číslo: {RC3_M[:6]}{NBSP}{RC3_M[6:]}",  # NBSP group separator inside an identifier
    "Narodený: 15.3.1985.",
    "",
    "Splnomocnenec predávajúceho: NOVÁK Ján, narodený 15.3.1985.",
    "",
    "Overila: JUDr. Mária KOVÁČOVÁ, notárka so sídlom na Krátkej ulici 8, Bratislava.",
    "",
    f"IČO klienta: {ICO3[:4]}{SHY}{ICO3[4:]}",     # soft hyphen inside an identifier
]


def build_doc3(path: Path) -> None:
    doc = Document()
    for line in DOC3_PARAGRAPHS:
        doc.add_paragraph(line)
    # The two-word field label split across a line break, value on the next line — the exact
    # shape that leaked a client number once (detect/office_refs.py).
    p = doc.add_paragraph()
    r1 = p.add_run("Číslo")
    r1.add_break()
    p.add_run("klienta: 2019-7785")
    doc.save(str(path))


NEEDLES_3 = [
    "Ján NOVÁK", "NOVÁK Ján", "Mária KOVÁČOVÁ",   # caps-surname convention
    "Hlavnej", "Krátkej",                         # declined street name
    "2019-7785",                                  # split field label -> value
    "15.3.1985",                                  # DOB (auto-redacted)
    _rc_slashed(RC3_M),                           # RC with an NBSP group separator
    ICO3,                                         # ICO with a soft hyphen punched into it
]
POSITIVE_CONTROL_3 = "Notár osvedčuje"


# =========================================================================== verification
def _flatten(s: str) -> str:
    """Strip every Unicode format character (Cf — the soft hyphen among them) and collapse
    all whitespace (the NBSP among it) to a single space, on BOTH the needle and the
    haystack. See tools/make_demo.py's ``_flatten`` for why: a plain ``needle in haystack``
    is silently blind to exactly the two invisible characters this document plants on
    purpose."""
    return re.sub(r"\s+", " ", strip_format_chars(unicodedata.normalize("NFC", s))).strip()


def _leaked(out_path: str, needles: list[str]) -> list[str]:
    result = extract(Path(out_path))
    hay = _flatten(result.full_text)
    return [n for n in needles if _flatten(n) in hay]


def _positive_control_ok(out_path: str, control: str) -> bool:
    result = extract(Path(out_path))
    return _flatten(control) in _flatten(result.full_text)


def _run_one(src: Path, needles: list[str], control: str, known_entities: list[str]) -> list[str]:
    print(f"\n{'=' * 78}\n  {src.name}\n{'=' * 78}")
    scan = scan_file(str(src), known_entities)
    if scan.error:
        print(f"  REFUSED: {scan.error}")
        return needles  # every needle counts as "not verified clean"

    checked = {r.group: (r.bucket == "auto") for r in scan.rows}
    decisions = build_decisions(scan.rows, checked, known_entities)
    out, report = export_file(str(src), known_entities, decisions)
    print(f"  exported: {Path(out).name}")
    print(f"  report:   {Path(report).name}")

    ok = _positive_control_ok(out, control)
    print(f"  positive control {control!r}: {'FOUND' if ok else 'MISSING'}")
    assert ok, (
        f"positive control {control!r} not found in {out} via eval.extract — "
        "the extractor read nothing, so a clean leak result here would mean nothing"
    )

    leaked = _leaked(out, needles)
    if leaked:
        print(f"  *** LEAK: {len(leaked)}/{len(needles)} needle(s) survive in {Path(out).name} ***")
        for needle in leaked:
            print(f"        {needle!r}")
    else:
        print(f"  verified: 0 of {len(needles)} needles survive in {Path(out).name}")
    return leaked


def verify(out_dir: Path) -> int:
    """Run the real pipeline over the three generated documents and check every needle
    through eval/extract.py. Returns 0 if every document is clean, else the number of
    surviving needles (also printed, per document, above).

    Runs against COPIES in a scratch directory, not the files in ``out_dir`` directly:
    ``export_file`` writes ``<stem>_anon.<ext>`` next to its source, and the owner's actual
    17:00 test is to drag the three original files onto the app — that folder should hold
    exactly the three source .docx files plus the README, not this script's own leftovers.
    """
    cases = [
        ("test_doc_1_bezna_zmluva.docx", NEEDLES_1, POSITIVE_CONTROL_1,
         ["Ján Novák", "Mária Kováčová"]),
        ("test_doc_2_word_tvary.docx", NEEDLES_2, POSITIVE_CONTROL_2,
         ["Peter Dvorák", "Zuzana Bieliková", NAME2_SDT]),
        ("test_doc_3_tazke_tvary.docx", NEEDLES_3, POSITIVE_CONTROL_3,
         ["Ján Novák", "Mária Kováčová"]),
    ]
    total = 0
    with tempfile.TemporaryDirectory(prefix="anon_verify_") as tmp:
        tmp_dir = Path(tmp)
        for name, needles, control, known in cases:
            src = tmp_dir / name
            shutil.copyfile(out_dir / name, src)
            leaked = _run_one(src, needles, control, known)
            total += len(leaked)
    return total


# =========================================================================== README (Slovak)
README = """\
# Testovacie dokumenty — návod na rýchly test

Tento priečinok obsahuje TRI vzorové dokumenty (.docx) s vymyslenými, ale realisticky
vyzerajúcimi osobnými údajmi. Slúžia na rýchle overenie, že program funguje skôr, než ho
použijete na skutočný dokument klienta.

## Ako to spustiť

1. Otvorte aplikáciu (spustite .exe).
2. Potiahnite (drag & drop) jeden z troch súborov nižšie na okno aplikácie, alebo ho vyberte
   cez tlačidlo na otvorenie súboru.
3. Stlačte "Skenovať" — program ukáže zoznam nájdených údajov (niektoré predvolene zaškrtnuté,
   niektoré na ručné posúdenie).
4. Stlačte "Exportovať" — program vytvorí nový súbor s príponou `_anon.docx` vedľa pôvodného.
5. Otvorte vyexportovaný súbor a porovnajte ho so zoznamom nižšie — všetko, čo je v zozname,
   MUSÍ v exportovanom súbore zmiznúť (nahradené značkou ako `[MENO_1]`, `[RODNE_CISLO_1]` a
   podobne).

## 1. test_doc_1_bezna_zmluva.docx — bežný prípad

Obyčajná kúpna zmluva o prevode nehnuteľnosti medzi dvoma fyzickými osobami, s jednou
právnickou osobou ako vedľajším účastníkom. Údaje sú v bežnom texte, v tabuľke, v hlavičke aj
v päte strany. Toto je základný test — ak program nezvládne toto, nezvládne nič.

**Po exporte NESMÚ v súbore ostať tieto reťazce:**
- `Ján Novák`, `Mária Kováčová`
- `850315/0007`, `906122/0003` (rodné čísla)
- `15.3.1985`, `22.11.1990` (dátumy narodenia)
- `Štúrova 15`, `Hlavná 12/A`, `811 06`, `040 01`, `Bratislava`, `Košice` (adresy)
- `0905 123 456`, `0911 402 917` (telefóny)
- `jan.novak@pravnik.sk`, `maria.kovacova@pravnik.sk` (e-maily)
- `Stavebniny Tatry, s.r.o.` (obchodné meno)
- `36500003`, `2020123456`, `SK2020123456` (IČO, DIČ, IČ DPH)
- `SK00 1100 0120 0000 0000 0001` (IBAN)
- `4521`, `892/3` (číslo listu vlastníctva a parcely)

## 2. test_doc_2_word_tvary.docx — netradičné umiestnenia vo Worde

Tento súbor obsahuje osobné údaje na miestach, ktoré bežný textový editor priamo nevytvorí —
boli vložené priamo do vnútornej štruktúry súboru, presne tak, ako to vie urobiť len samotný
Word (formulárové pole, textové pole, vnorená tabuľka, sledované zmeny, odkaz a vlastnosť
dokumentu). Tento test overuje, že program nekontroluje len viditeľný text na stránke, ale
CELÝ súbor.

**Po exporte NESMÚ v súbore ostať tieto reťazce (ani v skrytých častiach súboru):**
- `maria.kovacova@klient.sk` (cieľ hypertextového odkazu — text odkazu samotný je čistý)
- `720101/0003`, `Elena Sokolová` (formulárové pole / obsahová ovládacia prvok)
- `Kollárova 9`, `917 01`, `Trnava` (vnorená tabuľka)
- `0908 555 111` (textové pole)
- `SK31 1200 0001 0000 0000 0001` (vložený text — sledovaná zmena)
- `900410/0006` (vymazaný text — sledovaná zmena; vymazaný text sa vo Worde stále dá zobraziť!)
- `44000006` (vlastná vlastnosť dokumentu — nie je vidno v texte, len vo vlastnostiach súboru)

POZNÁMKA: všetkých sedem miest vyššie bolo overených 17.9.2026 — pri automatickej kontrole
neostal v exportovanom súbore ani jeden z nich. Ak niektorý z nich po vašom exporte v súbore
nájdete, je to NOVÁ chyba a treba ju nahlásiť.

## 3. test_doc_3_tazke_tvary.docx — zložité jazykové tvary

Notárska zápisnica, ktorá obsahuje tri konkrétne tvary, na ktorých program v minulosti
zlyhával a ktoré boli opravené 17.9.2026:
- meno s priezviskom VEĽKÝMI PÍSMENAMI (bežný štýl v právnych dokumentoch): `Ján NOVÁK`,
  `NOVÁK Ján`, `Mária KOVÁČOVÁ`;
- skloňovaný názov ulice v adrese: `na Hlavnej ulici`, `na Krátkej ulici` (nie `Hlavná ulica`,
  ale tvar, ktorý sa reálne píše v adrese);
- dvojslovná menovka rozdelená zalomením riadka, s hodnotou na ďalšom riadku ("Číslo" / nový
  riadok / "klienta: 2019-7785") — presne tento tvar raz spôsobil únik čísla klienta.

Navyše obsahuje jedno rodné číslo s medzerou, ktorá sa v súbore ukladá ako "nezalomiteľná
medzera" (na pohľad nerozoznateľná od obyčajnej), a jedno IČO s "mäkkým delením" (znak bez
vlastného tvaru, tiež na pohľad neviditeľný) — obe sú bežným spôsobom, akým textové editory
a systémy kancelárií neúmyselne "rozbijú" číslo, hoci ho na obrazovke vidno ako celé.

**Po exporte NESMÚ v súbore ostať tieto reťazce:**
- `Ján NOVÁK`, `NOVÁK Ján`, `Mária KOVÁČOVÁ`
- `Hlavnej`, `Krátkej` (súčasť skloňovaného názvu ulice v adrese)
- `2019-7785` (číslo klienta za zalomeným riadkom)
- `15.3.1985` (dátum narodenia)
- rodné číslo `850315` + medzera + `0007` (s nezalomiteľnou medzerou)
- `44000006` (IČO s neviditeľným mäkkým delením uprostred)

POZNÁMKA: IČO `44000006` je v tomto dokumente zapísané s neviditeľným "mäkkým delením"
uprostred — medzi štvrtou a piatou číslicou je znak, ktorý sa nedá vidieť ani vytlačiť. Toto
číslo program NÁJDE a odstráni; overené meraním 17.9.2026. Patrí teda do zoznamu vyššie: ak po
exporte v súbore ostane, je to chyba.

## Čo sa NEMÁ odstrániť (a je to správne, nie chyba)

Všetky ostatné dátumy (napríklad dátum podpisu zmluvy, dnešný dátum) idú do zoznamu "na
posúdenie", nie do automatického zoznamu — program ich nemaže sám, lebo nevie, či ide o citlivý
údaj alebo o bežný dátum v texte. To je zámer, nie chyba.
"""


def write_readme(out_dir: Path) -> None:
    (out_dir / "CITAJ_MA.md").write_text(README, encoding="utf-8")


# =========================================================================== main
def main() -> int:
    TEST_DIR.mkdir(parents=True, exist_ok=True)

    doc1 = TEST_DIR / "test_doc_1_bezna_zmluva.docx"
    doc2 = TEST_DIR / "test_doc_2_word_tvary.docx"
    doc3 = TEST_DIR / "test_doc_3_tazke_tvary.docx"

    build_doc1(doc1)
    print(f"built {doc1}  ({doc1.stat().st_size:,} B)")
    build_doc2(doc2)
    print(f"built {doc2}  ({doc2.stat().st_size:,} B)")
    n_parts = assert_package_intact(doc2)
    print(f"  package re-open assertion: {n_parts} parts, all XML/rels parts well-formed")
    build_doc3(doc3)
    print(f"built {doc3}  ({doc3.stat().st_size:,} B)")

    write_readme(TEST_DIR)
    print(f"wrote {TEST_DIR / 'CITAJ_MA.md'}")

    total = verify(TEST_DIR)
    print(f"\n{'=' * 78}")
    if total:
        print(f"  {total} needle(s) survived across the three documents (see above for which).")
    else:
        print("  0 needles survive across all three documents.")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
