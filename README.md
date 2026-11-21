# Trops Studio 5.0.00

Namizna aplikacija za knjigovodstvo DDV: uvoz IR/PR (Vasco, FURS KIR/KPR, Integra SQL), pregled in urejanje,
obrazec **DDV-O** (XML za eDavke, PDF, virman UPN QR, e-pošta stranki) in sinhronizacija temeljnic v **Minimax**.

* **Okolje:** Windows 10/11, Python 3.10+, Microsoft Edge WebView2 Runtime.
* **Vmesnik:** spletni UI (`ui/`) v oknu WebView2. Lokalni strežnik na `127.0.0.1` z žetonom seje (`host.py`).
* **Klasični Tk urejevalnik** (`run_trops.py`) ostaja. Odpre se iz *Nastavitve → Klasični urejevalnik (Tk)*.

## Namestitev

1. Razpakiraj v `D:\PISARNA\Python\Trops_v5`.
2. `py -3.10 -m pip install -r requirements.txt` (ali dvoklik `INSTALL.pyw`).
3. Zagon: `Zazeni_Trops_Studio_V5.bat` ali `Trops_Studio_V5.0.00.pyw`.

## Struktura

| Pot | Vsebina |
|---|---|
| `Trops_Studio_V5.0.00.pyw`, `Trops_Studio.pyw`, `Zazeni_Trops_Studio_V5.bat` | zagon spletnega UI (`host.desktop()`) |
| `INSTALL.pyw` | preveri predpogoje, namesti pakete in ponudi kopijo podatkov v4 |
| `host.py` | HTTP strežnik, API (`/api/*`), ozadne naloge (`/api/job`), Bridge (izbirnik datotek) |
| `motor.py` | sloj med API in poslovno logiko: validacija, potrditve, DDV-O akcije |
| `trops_studio_web/service.py`, `jobs.py` | stanje aplikacije (podjetje, obdobje, filtri), ozadne naloge |
| `trops_studio/` | poslovno jedro: SQLite (`db.py`), DDV (`ddvo_calc.py`), Minimax, Integra, Vasco, eDavki |
| `trops_studio/config.py` + `settings.json` | **vse poti na D:\\** in mapa podatkov |
| `trops_studio/ui/` | klasični Tk urejevalnik |
| `trops_studio/vendor_kirkpr/` | prevzeti moduli KirKpr (DDV-O XML/PDF, virman, Minimax API) |
| `ui/` | spletni vmesnik (`index.html`, `app.css`, `app.js`): brez CDN, ikone so inline SVG |
| `tests/` | pytest testi |
| `data/` | lokalne baze `zst-XX.sqlite3`, seja, dnevnik `data/logs/trops.log` (ni v gitu ali zipu) |

## Nastavitve (`settings.json` / `settings.local.json`)

Prazna vrednost pomeni privzeto vrednost. `settings.local.json` ima prednost in je primeren za osebne poti.
Vsako vrednost lahko prepiše tudi okoljska spremenljivka `TROPS_<KLJUČ>`, npr. `TROPS_DATA_DIR`.

| Ključ | Privzeto | Pomen |
|---|---|---|
| `data_dir` | `Trops_v5\data` | mapa SQLite baz. Pusti prazno — baze so v `Trops_v5\data`. |
| `trops_root` | `D:\Trops` | podatki TROPS po Zšt (`{Zšt}\DDV`, `{Zšt}\MiniMax`, `dat\KONT*.DBF`) |
| `integra_sql_dir` | `D:\Trops\20\SQL` | ZIP/BAK kopije Integra SQL |
| `evidenca_firm_root` | `D:\PISARNA\Python\EvidencaFirm` | evidenca firm (`firme_evidenca.json`, AJPES moduli) |
| `kirkpr_cursor_root` / `kirkpr_legacy_root` | `D:\PISARNA\Python\KirKpr_convert_cursor` / `…\KirKpr_convert` | zunanji KirKpr moduli |

## Zunanji moduli na D:\ (niso v paketu)

Te module aplikacija naloži prek `sys.path`. Brez njih ustrezna funkcija javi napako, ostalo deluje.

* **KirKpr_convert(_cursor)**
  * `kirkpr_upn_qr`: UPN QR na virmanu in v e-pošti.
  * `kirkpr_ajpes_iban`: IBAN iz AJPES za virman.
  * `kirkpr_ddvo_placeholder_texts`: besedila predlog e-pošte.
  * `kirkpr_company_registry`: register podjetij, s fallbackom na vgrajeno kopijo.
* **EvidencaFirm**
  * `firme_evidenca.json`: seznam podjetij, e-pošte strank, Org_ID za Minimax.
  * `minimax_ajpes`, `ajpes_prs_lookup`, `ajpes_company_service`: AJPES iskanje v Tk urejevalniku strank.
* **Chrome_add**
  * `smtp_secret.bin`: geslo za Gmail SMTP (DPAPI).
  * Pot je v `config.SMTP_SECRET_CANDIDATES`, vrednost se nikoli ne bere v UI.
* **Integra:** SQL Server `TROPS` (pyodbc, `sqlcmd`) in `KONT*.DBF` (dbfread).

## Varnost

* Strežnik posluša samo na `127.0.0.1` in preverja `Host` ter žeton seje (piškotek `trops5`).
* Tvegane akcije (brisanje obdobja, RESTORE TROPS, pošiljanje e-pošte) zahtevajo `confirm: true` in potrditveno okno.
* E-pošta se **nikoli ne pošlje samodejno**. Najprej se pokaže osnutek s predogledom, prejemnikom in priponkami, šele nato potrditev.
* Napake API so enotne: `{"ok": false, "error": "…", "msg": "…"}`. Statusi: 400 napačen vnos, 403 seja, 404 ne obstaja, 409 zasedeno, 500 notranja napaka (zapisana v `data/logs/trops.log`).

## Razvoj in testi

```
py -3.10 -m pip install -r requirements-dev.txt
py -3.10 -m pytest -q tests
py -3.10 -m ruff check .
```

Testi delajo na kopiji baz v začasni mapi in blokirajo vse zunanje omrežne klice.
Testi z realnimi zneski (DDV-O Zšt 21, oktober 2026) potrebujejo `data/zst-21.sqlite3`
(ali `TROPS_TEST_FIXTURES=<mapa>`), sicer se preskočijo.
