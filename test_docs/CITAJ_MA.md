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

## Priečinok `ocakavany_vystup/`

Obsahuje správu (`*_report.txt`), ktorú pre každý z troch dokumentov vytvoril tento zdrojový
strom. Slúži na POROVNANIE: po exporte si otvorte svoju správu a porovnajte ju s tou v tomto
priečinku. Ak vaša správa obsahuje MENEJ riadkov alebo iné riadky, niečo je inak — najčastejšie
to znamená, že zabudnuté súbory s údajmi (gazetteer) nie sú v zostavenej aplikácii.

POZOR: tieto správy vytvoril ten istý program, takže NIE SÚ nezávislým dôkazom správnosti.
Nezávislou kontrolou je ručne napísaný zoznam reťazcov vyššie.

## Čo sa NEMÁ odstrániť (a je to správne, nie chyba)

Všetky ostatné dátumy (napríklad dátum podpisu zmluvy, dnešný dátum) idú do zoznamu "na
posúdenie", nie do automatického zoznamu — program ich nemaže sám, lebo nevie, či ide o citlivý
údaj alebo o bežný dátum v texte. To je zámer, nie chyba.
