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

## Popravki po testu 5.1 (21.11.2026)
- **Zagon brez konzole**: `Zazeni_Trops_Studio_V5.bat` zažene `pyw` (brez črnega okna); za diagnostiko `Zazeni_Trops_Studio_V5_konzola.bat` (`py` + pause).
- **DDV-O pot**: izvoz gre v `<trops_root>\<ZST>\DDV` (npr. `D:\Trops\21\DDV`), ne več `D:\Trops\21\21\DDV`. Test.
- **Stranke**: pri *Nova stranka* z obstoječo davčno / ID za DDV / Minimax šifro opozorilo »Stranka že obstaja« (Odpri / Posodobi / Prekliči); obstoječa stranka se ne prepiše tiho. Po shranjevanju se osveži števec strank. Pravila ujemanja za uvoze in sinhronizacijo nespremenjena.
- **Konti Trops → Minimax**: okno pokaže tudi skupne preslikave (brez Org_ID, »skupno (vsa podjetja)«); privzete preslikave se ne zapišejo več v bazo, ko Org_ID podjetja ni znan.

## Čiščenje baz 2C (21.11.2026 18:04, odobreno; ni v gitu)
Varnostna kopija pred spremembo (zst-21, zst-20 z -wal/-shm, MD5 preverjen): `data\backups\zst-21_zst-20_pred_ciscenjem_preslikav_2C_20261121_180357.zip`.
Povrnitev: zapri Trops, razpakiraj zip v `data\` čez obstoječe datoteke.

- **zst-21**: `DELETE FROM minimax_accounts WHERE org_id='179531'` — 1120 vrstic (kontni plan Integre, prenesen 26.7.; zst-21 = PROJEST, Org_ID 179535). Ostane 1120 vrstic 179535.
- **zst-21**: `UPDATE account_code_map SET org_id='179535' WHERE org_id='' AND source='default'` — 29 vrstic (privzete preslikave s 15.8.2026 brez Org_ID). Veljavne preslikave enake.
- **zst-20**: `DELETE FROM account_code_map WHERE org_id='179535' AND source='default'` — 29 vrstic (preslikave PROJEST po pomoti v zst-20, 29.10.). Ostanejo preslikave 179531 (29 default + 1 test).
- Vse v transakciji (BEGIN IMMEDIATE … COMMIT), štetje pred/po se ujema. `PRAGMA integrity_check` = ok (obe bazi).
- Preverjeno na kopiji pred in po: DDV-O 10/2026 zst-21 obveznost **6.828,00 €** (f51 = 6828), DDV-O XML in KIR/KPR XML bajtno enaka; DDV-O 7/2026 zst-20 710,00 € enako. Okno preslikav: zst-21 29 shranjenih (179535), 0 nepreslikanih; zst-20 30. Nič ni bilo poslano.
- MD5 po spremembi: zst-21 `50EC20EE355EE606E14CD8C2F7F9B978`, zst-20 `A79DB0BF7A64BE6BA989ADCE0808CFCE`.

## Še odprto (čaka odobritev)
- Namigi (tooltipi) in razdelitev navodil; indeksi in filter obdobja v SQL; prenos preostalih Tk funkcij in odstranitev Tk; »zgodovina«; čiščenje Integre; oznaka verzije 5.1.00 v imenih datotek.
