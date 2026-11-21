# Trops Studio 5.0.00 — pregled (stanje v `D:\PISARNA\Python\Trops_v5`, 21. 11. 2026)

Pregled opisuje verzijo **5.0.00**, kot je bila v mapi `Trops_v5` pred namestitvijo 5.1 (git `e62438a`, koda enaka izhodišču `97291db`).

## 1. Kaj je Trops Studio
Večpodjetniški program za vodenje knjig IR/PR in obračun DDV:
- uvoz računov (Vasco Excel, FURS KIR/KPR, Integra SQL),
- pregled in urejanje IR/PR po obdobjih,
- obrazec **DDV-O** (XML za eDavke, PDF, virman UPN QR, e-pošta stranki),
- sinhronizacija temeljnic in strank z **Minimaxom**.

Teče kot namizno okno (pywebview + **Edge WebView2**). Python (`host.py`, `motor.py`) zažene lokalni strežnik na `127.0.0.1`, vmesnik je HTML/JS v mapi `ui\`.

## 2. Zagon
- `Zazeni_Trops_Studio_V5.bat` (dvoklik) → `py -3.10 Trops_Studio_V5.0.00.pyw` → `host.desktop()`.
- Namestitev paketov: `py -3.10 -m pip install -r requirements.txt` ali `INSTALL.pyw`.
- Potrebno: Python 3.10+, Edge WebView2 Runtime, paketi pywebview, lxml, pywin32, pyodbc, dbfread, tkcalendar.

## 3. Struktura mape
| Pot | Vsebina |
|---|---|
| `Trops_Studio_V5.0.00.pyw`, `Trops_Studio.pyw`, `Zazeni_Trops_Studio_V5.bat` | zagon |
| `host.py` | okno WebView2, lokalni HTTP strežnik, `/api/*`, ozadne naloge, potrditve tveganih akcij |
| `motor.py` | akcije za spletni vmesnik (shranjevanje, brisanje obdobja, DDV-O, Integra …) |
| `trops_studio_web\service.py` | storitev nad bazo: seznami IR/PR, knjige, konti, stranke, povzetki |
| `trops_studio\` (≈54 modulov) | jedro: `db.py` (SQLite), `ddvo_calc.py` (DDV-O), `minimax_*` (Minimax API), `integra_*` (Integra), `excel_bridge.py`/`excel_map.py` (Vasco), `kirkpr_*`, `ajpes_client.py`, `vies_client.py`, `config.py` (poti) |
| `trops_studio\ui\` | stari Tk urejevalnik (»Klasični urejevalnik«) |
| `trops_studio\vendor_kirkpr\` | vgrajeni KirKpr moduli (DDV-O XML/PDF/virman/e-pošta, Minimax odjemalec) |
| `ui\index.html`, `ui\app.js`, `ui\app.css` | spletni vmesnik |
| `tests\` | pytest testi (baza, DDV-O, strežnik, povezave JS↔Python, UI) |
| `data\` | **baze** in delovne datoteke (niso v gitu) |
| `docs\` | SPREMEMBE_5.0.00, PRENOS_IZ_V4, analize |
| `settings.json` | nastavitve poti |
| `PROMPT.md`, `POGOVOR_20261121.md` | pravila dela in zapis pogovora |

## 4. Baze
- Edina mapa baz: `D:\PISARNA\Python\Trops_v5\data` (`data_dir` = prazno = privzeto).
- Ena baza na podjetje: `zst-21.sqlite3`, `zst-20.sqlite3`, `zst-41.sqlite3`, `zst-10.sqlite3`. Ob tem `trops_idle.sqlite3` (brez izbranega podjetja) in stara `projest.sqlite3`.
- Dnevnik: `data\logs\trops.log`. Profil WebView2: `data\webview2_profile`.

## 5. Zasloni (spletni vmesnik)
Levo je temna stranska vrstica, zgoraj izbira podjetja in obdobja (◀ ▶), Osveži (F5), tema in **Sinhroniziraj**. Pod tem so KPI kartice, orodna vrstica in tabela, spodaj statusna vrstica s potjo do baze.

**Evidence**
- **Izdani računi (IR)**:
  - Filtri: iskanje, status, Darila/Fitness/Paragoni/Fakture/KIR.
  - Ukazi: Vse označi / Odznači, Dodaj, Uredi (tudi dvoklik), Konto…, Izbriši, **4 · Potrdi**, Sync IR.
  - Seštevki: osnova, DDV, skupaj.
- **Prejeti računi (PR)**: enako za prejete račune (PR kontrola, regija dobavitelja).
- **Obrazec DDV-O**:
  - Polja obrazca z virom, natančno in razliko.
  - Ukazi: Predogled PDF, XML + PDF za eDavke, PDF + virman (UPN QR), E-pošta stranki (najprej predogled, nikoli samodejno), eDavki MRN.

**Knjige in konti**
- **Knjiga IR / Knjiga PR**: polja P2–P27 po pravilniku.
- **Konti**: pivot knjižb po kontih.
- **Vse knjižbe**: temeljnične vrstice (debet/kredit).

**Ostalo**
- **Stranke**: šifrant strank; ukaza Manjkajoče stranke in Stranke iz Minimax.
- **Analitika**: promet IR/PR, izstopni/vstopni DDV, obveznost ali presežek.

**Orodja (meniji)**
- **Uvoz**: Vasco Excel…, FURS KIR/KPR…, Integra SQL TROPS…, Konti iz zgodovine, Briši uvoz obdobja… (s potrditvijo).
- **Minimax**: 1 · Stranke iz Minimax, 3 · Manjkajoče stranke…, 5 · Sinhroniziraj… (s potrditvijo), Izvozi XML za KirKpr, Preveri Minimax API, eDavki MRN prenesi.
- **Nastavitve**: Integra SQL mapa…, Klasični urejevalnik (Tk)…, Svetla/temna tema, O programu, Izhod.

## 6. Povezave
- **Minimax** (API): stranke, kontni plan, temeljnice IR/PR.
- **eDavki**: XML DDV-O, prenos MRN.
- **Integra**: SQL Server (pyodbc, obnova iz ZIP/BAK prek sqlcmd s potrditvijo) in `KONT*.DBF` (dbfread).
- **Vasco**: Excel prek PowerShell + Microsoft ACE.OLEDB (v 5.0 še potreben Access gonilnik).
- **AJPES / VIES**: v 5.0 samo v Tk urejevalniku.
- **E-pošta**: DDV-O stranki, samo ročno po predogledu.

## 7. Nastavitve (`settings.json`, prednost ima `settings.local.json`, nato okolje `TROPS_<KLJUČ>`)
`data_dir` (prazno = `Trops_v5\data`), `trops_root` (`D:\Trops`), `integra_sql_dir` (`D:\Trops\20\SQL`), `evidenca_firm_root`, `kirkpr_cursor_root`, `kirkpr_legacy_root`, `webview_profile_dir`.

## 8. Kje je oznaka verzije »5.0.00«
- Ime datoteke `Trops_Studio_V5.0.00.pyw` (in sklici v `.bat` ter `INSTALL.pyw`).
- `trops_studio\__init__.py` in `trops_studio_web\__init__.py` (`__version__`), ki se prikaže v vmesniku kot »Verzija 5.0.00«.
- `ui\index.html` (naslov okna, znamka), `ui\app.js` (privzeta vrednost), glave `host.py` in `motor.py`, sporočila v `Trops_Studio*.pyw`, `tests\test_server.py`.

## 9. Posnetki zaslona 5.0 (na boxu, ista koda, testna kopija baze zst-21)
`/workspace/trops_v5_screens/`: `potem_IR.png`, `potem_PR.png`, `potem_DDV-O.png`, `potem_Stranke.png`, `potem_Analitika.png`, `potem_IR_temna.png`, `potem_DDV-O_temna.png`.
