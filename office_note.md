# Oznámenie pre kanceláriu — Anonymizer v1.1

*Návrh na odoslanie. Skontrolujte a upravte oslovenie podľa zvyklostí kancelárie; obsah
odsekov „Čo nástroj nerobí“ a „Postup“ nechajte bez zmeny — ide o vymedzenie zodpovednosti,
nie o formuláciu.*

---

Dobrý deň,

od zajtra máte k dispozícii novú verziu nástroja na anonymizáciu dokumentov (v1.1).
Rozpoznáva podstatne viac typov údajov než predchádzajúca verzia — okrem rodného čísla, IČO,
DIČ, IBAN a mien aj adresy, PSČ, čísla dokladov, EČV, VIN, telefón a fax, bankové údaje,
čísla klienta, spisové značky, názvy spoločností a obce.

Rozsah typov vychádza z **vyhlášky MS SR č. 482/2011 Z. z.** o zverejňovaní súdnych
rozhodnutí, ktorá je pre Slovensko autoritatívnym zoznamom údajov podliehajúcich
anonymizácii.

## Čo nástroj NEROBÍ — prosím, čítajte

Tieto obmedzenia nie sú dočasné nedostatky. Vyplývajú z toho, ako nástroj funguje, a je
potrebné s nimi počítať pri každom dokumente.

**1. Skeny a fotografie sa nespracúvajú.**
Nástroj pracuje s textovou vrstvou dokumentu. Ak je PDF iba obrázkom naskenovanej strany
(nedá sa v ňom označiť ani vyhľadať text), nástroj ho odmietne spracovať — a odmietne ho
úmyselne. Vrátiť zdanlivo anonymizovanú kópiu skenu, v ktorej sa v skutočnosti nič
neodstránilo, by bolo nebezpečnejšie než nespracovať ho vôbec. Takýto dokument je potrebné
najprv previesť na text (OCR) alebo anonymizovať ručne.

**2. Podpisy a pečiatky sa neodstraňujú.**
Podpis ani okrúhla pečiatka nie sú text — sú to obrázky. Nástroj ich nevidí a nechá ich v
dokumente. Ak dokument obsahuje podpis alebo pečiatku, ktoré sa nemajú zverejniť, musíte ich
odstrániť sami.

**3. Obchodné tajomstvo a utajované skutočnosti sa nerozpoznávajú.**
Písmeno (i) citovanej vyhlášky — utajované informácie a obchodné tajomstvo — je **mimo
rozsahu nástroja**. Tento údaj nie je definovaný tvarom, ale významom: či je konkrétna veta
obchodným tajomstvom, sa nedá rozhodnúť žiadnym vzorom ani zoznamom. Uvádzame to výslovne,
pretože nástroj sa opiera o zoznam z vyhlášky a bolo by zavádzajúce tvrdiť, že ho napĺňa
celý. **Túto kategóriu musí v každom dokumente posúdiť advokát.**

**4. Vo výstupnom PDF ostávajú čierne polia, text sa nepreleje.**
Odstránený údaj je v PDF nahradený štítkom (napr. `[MENO_1]`) v presne takom mieste a
veľkosti, akú zaberal pôvodný text. Strana sa nepreformátuje a riadky sa neposunú. Vyzerá to
menej elegantne než pôvodný dokument — je to však jediný spôsob, ako zaručiť, že pôvodné
znaky sú z dokumentu naozaj **odstránené**, a nie len prekryté. Čierny obdĺžnik nakreslený
cez text nie je anonymizácia: znaky pod ním sa dajú z PDF bez problémov prečítať.

**5. Ten istý údaj má v celom dokumente to isté číslo.**
Ak sa v dokumente vyskytujú dve osoby, budú označené `[MENO_1]` a `[MENO_2]`, a to rovnako na
každej strane. Dokument tak ostáva čitateľný a dá sa v ňom sledovať, kto je kto.

## Postup — prosím dodržiavajte

**Každý výstup pred odoslaním skontrolujte.** Nástroj vytvára ku každému dokumentu protokol
(`..._report.txt`), v ktorom je uvedené, čo bolo odstránené, akého typu to bolo a v ktorej
časti dokumentu sa to nachádzalo. Prejdite ho oproti dokumentu.

Nástroj je nastavený tak, aby radšej odstránil viac než menej. Ak si nie je istý, údaj
odstráni alebo ho zaradí do zoznamu na ručné potvrdenie — nikdy ho nenechá ticho v texte.
To znamená, že občas odstráni aj niečo, čo odstrániť nemuselo. **Tento smer je zvolený
zámerne:** zbytočne odstránený údaj je nepohodlie, prehliadnutý osobný údaj je únik.

V okne kontroly pred exportom vidíte dva zoznamy: **automaticky odstránené** (zaškrtnuté) a
**na posúdenie** (nezaškrtnuté). Druhý zoznam je ten, kde nástroj niečo našiel, ale nie je si
istý — prejdite ho vždy.

**Dátumy:** štandardne sa odstraňuje iba dátum narodenia. Ostatné dátumy (podpis, účinnosť,
splatnosť) ostávajú, inak by dokument stratil zmysel. Ak potrebujete odstrániť všetky dátumy,
zapnite to v rozšírených nastaveniach.

**Názov súboru:** ak názov súboru sám obsahuje meno klienta (`Novak_kupna_zmluva.docx`),
nástroj vás na to upozorní. Premenujte súbor pred odoslaním — inak odošlete meno klienta v
názve prílohy bez ohľadu na to, ako dôkladne je vyčistený jej obsah.

V prípade akýchkoľvek pochybností o konkrétnom dokumente ma kontaktujte.

S pozdravom
