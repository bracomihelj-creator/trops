# Trops Studio 5.1.00 — spremembe (v delu)

Izhodišče: `Trops_v5` 5.0.00 (commit `cb28ab7`). `Trops_v4` se ne spreminja. Poslovna logika in izračuni (DDV-O, knjige, kisanal, sinhronizacija) niso spremenjeni.
Vsak korak je svoj git commit; zgodovina se ne prepisuje.

## Baze
- Baze ostanejo v `Trops_v5\data` (privzeti `data_dir`). Ni sklicev na `Trops_v4\data`; `INSTALL.pyw` ne ponuja več kopije iz v4.

## Brez Microsoft Accessa
- Odstranjen ukaz **Konti iz ACCDB** (Projest.accdb) in branje zgodovine prek ACE.
- Odstranjene poti do Access baz (Projest.accdb, INTEGRA_za_MINIMAX.accdb, Minimax.accdb) in PowerShell 32-bit.
- Odstranjen enkratni prenos `projest.sqlite3 → zst-21` (datoteka ni izbrisana) in rezervna pot `KirKpr_convert` (`kirkpr_legacy_root`).
- **Vasco Excel uvoz**: namesto PowerShell + Microsoft.ACE.OLEDB bere `openpyxl` (.xlsx/.xlsm) in `xlrd` (.xls). Izhod je enak kot pri ACE (imena stolpcev `F{n}`, `#` namesto pike, 64 znakov, izbira lista, filter vrstic) — preverjeno s testi na pravih zapisih iz baze.
- Ostaja: Integra SQL Server (`pyodbc`, `sqlcmd`) in `KONT*.DBF` (`dbfread`).

## Videz Trops 4 / Trops 5
- Gumb **Videz** v zgornji vrstici (in *Nastavitve → Videz*). Trops 4 = znamka + menijska vrstica zgoraj, svetlo drevo levo, goste tabele, barve v4. Trops 5 = nov videz.
- Samo CSS na istem vmesniku v5 — stari vmesnik v4 se ne nalaga; vsi gumbi, potrditve in funkcije v5 ostanejo.
- Izbira in tema se shranita v `settings.local.json` (`ui_videz`, `ui_tema`) in veljata ob naslednjem zagonu.
- Posnetki: `t4_IR.png`, `t5_IR.png`, `t4_meni_minimax.png`, `t4_stranke_temna.png`.

## Iz Tk urejevalnika v spletni vmesnik
- **Minimax → 2 · Konti Trops → Minimax…**: konti, ki jih v Minimaxu ni, izbira zamenjave, shranjene preslikave; prepis obstoječih vrstic samo po potrditvi.
- **Minimax → Kontni plan iz Minimax**: prenos kontnega plana v bazo (po potrditvi; Minimax se ne spremeni).
- **Stranke → Nova stranka** in dvoklik za urejanje; **Poišči v AJPES** in **Preveri VIES** samo izpolnita obrazec, shrani se šele s *Shrani*.

## Zanesljivost
- Tihe napake v kritičnih poteh (Minimax temeljnice/stranke, stranke, Integra knjižbe, odpiranje datotek) se zapišejo v `trops.log`.
- Pokvarjen `settings.json` ne ustavi zagona; opozorilo se pokaže v vmesniku.

## Bližnjice
- `F5` osveži, `Ctrl+F` iskanje, `Alt+1…9` pogledi, `Alt+←/→` obdobje, `Ctrl+Enter` potrdi okno, `Esc` zapre, `?` seznam bližnjic.

## Še odprto (čaka odobritev)
- Namigi (tooltipi) in razdelitev navodil; indeksi in filter obdobja v SQL; prenos preostalih Tk funkcij in odstranitev Tk; »zgodovina«; čiščenje Integre; oznaka verzije 5.1.00 v imenih datotek.
