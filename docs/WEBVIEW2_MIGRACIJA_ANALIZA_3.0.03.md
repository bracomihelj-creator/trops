# Trops Studio — analiza migracije LOOK → WebView2

**Datum:** 19. 11. 2026  
**Master prompt:** `D:\PISARNA\Python\Navodila_PROMPT\MASTER_PROMPT_QUICK_WEBVIEW2.md`  
**Referenca LOOK:** QUICK eDAVKI PRO V1 (`1.0.72`, pywebview + Edge WebView2)  
**Stanje:** **SAMO ANALIZA** — nobena sprememba produkcijske kode še ni izvedena.  
**Zahteva:** izrecna odobritev uporabnika pred kakršnokoli implementacijo.

---

## 1. Verzije (dejansko stanje projekta)

| Vloga | Vrednost | Dokaz |
|---|---|---|
| **Zadnja obstoječa verzija** | **`3.0.03`** | `trops_studio/__init__.py` → `__version__ = "3.0.03"` |
| **Zadnja stabilna (delujoča) verzija** | **`3.0.03`** (Tkinter UI) | Ni ločenega taga/git remote; ni `VERSION.txt` / `RELEASE_NOTES`. Trenutna koda v `D:\PISARNA\Python\Trops` je edini kanonični vir. |
| **Predlagana nova LOOK verzija** | **`3.1.00`** | Glavna UI prenova (WebView2). Izvorna `3.0.03` ostane nedotaknjena (backup + `.pyw` kopija). |
| Git | **ni repozitorija** | `NO_GIT` v mapi Trops |
| Zagonske datoteke danes | `run_trops.py`, `run_studio.py`, `Zaženi_Trops_Studio.bat` | Ni samostojnega `.pyw` / `INSTALL.pyw` (še) |

**Opomba:** V tej seji je bila dodana le manjša UI-opomba za digitalne dobavitelje iz tretjih držav (`vat_accounts.is_third_country_digital_supplier` + opozorilo v `pr_editor`) — poslovna DDV logika ostaja enaka; verzija ni bila dvignjena (po izrecni zahtevi).

---

## 2. Kaj je Trops Studio (poslovni namen)

Namizni Windows program za knjigovodski tok:

**Vir podatkov → SQLite (po podjetju) → urejanje IR/PR/strank/kontov → DDV-O → Minimax / eDavki / e-pošta**

Viri po podjetju (`company_source_kind`):

1. **Projest / Vasco** — Excel (`IF DARILA`, `IF FITNES`, `KPF`) + ACCDB konti  
2. **Integra** — SQL Server baza **TROPS** (ZIP/BAK → RESTORE → UrejanjeKisanal → IR/PR)  
3. **KIR/KPR** — FURS XML/CSV uvoz za ostale firme  

Podatki podjetij: `data/zst-{Zšt}.sqlite3` (npr. `zst-21`, `zst-20`, `zst-41`), seja `data/session.json`, šifranti/cache `vat_api_*.json`, `party_name_aliases.json`.  
Zunanje poti: `D:\Trops\{Zšt}\…`, EvidencaFirm, Minimax API, eDavki MRN, Outlook/SMTP.

---

## 3. Trenutna UI arhitektura (Tkinter)

### 3.1 Glavno okno — `trops_studio/ui/app.py` (~5301 vrstic)

Razred `ProjestStudioApp` (zgodovinsko ime; naslov = **Trops Studio**):

| Območje | Vsebina |
|---|---|
| Meni | Datoteka / Nastavitve / Pomoč |
| Header | koraki 1→5, gumbi Minimax↓, Manjkajoče, Sinhroniziraj, Stranke, **Osveži**, MRN prenesi |
| Vir / poti | Collapsible: Projest / Integra / KIR-KPR |
| Obdobje | mesec/leto, od–do, oznaka revizije, Briši uvoz obdobja |
| Povzetek | 3 kartice IR / PR / Stranke |
| Levi panel | **PODJETJA** (Treeview) + **VSEBINA** (nav Treeview) |
| Desno | `ttk.Notebook` z 8 zavihki (vzporedno z navigacijo) |
| Status | statusna vrstica + bližnjice |

**Že obstaja levi drevesni panel** (`nav_tree`), vendar **vzporedno** še zgornji/vsebinski `ttk.Notebook`. Cilj migracije: **edina** navigacija = levi drevesni panel (brez vidnih Notebook zavihkov), vsebina v osrednjem HTML področju.

### 3.2 Zavihki / navigacijska vozlišča (100 % ohraniti)

| Nav ID | Zavihek | Modul UI |
|---|---|---|
| `nav:ir` | Izdani računi (IR) | `app._build_ir_tab` |
| `nav:pr` | Prejeti računi (PR) | `app._build_pr_tab` |
| `nav:ddvo` | Obrazec DDV-O | `ui/ddvo_tab.py` |
| `nav:knjige` / `nav:knjiga_ir` / `nav:knjiga_pr` | Knjige IR/PR | `ui/knjige.py` (+ notranji Notebook IR/PR) |
| `nav:konti` | KONTI (pivot) | `ui/konti_tab.py` |
| `nav:parties` | Stranke | `app._build_parties_tab` |
| `nav:analysis` | Analitika | Text v `app.py` |
| `nav:knjizbe` | Vse knjižbe | `ui/vse_knjizbe_tab.py` |

### 3.3 Dialogi / Toplevel (vsi morajo v HTML/modal WebView2)

| Dialog | Datoteka | Namen |
|---|---|---|
| `PrEditorDialog` | `ui/pr_editor.py` (~1992) | Urejanje PR, DDV konti, OS/Minimax, samoobdavčitev |
| `IrEditorDialog` | `ui/ir_editor.py` | Urejanje IR |
| `StrankeDialog` | `ui/stranke_dialog.py` | Nova/uredi stranko, AJPES/VIES/AI/Minimax |
| `IntegraDialog` + `_PickDialog` | `ui/integra_dialog.py` | ZIP/BAK → RESTORE TROPS, Kisanal |
| `Missing*PartiesDialog` | `ui/missing_pr_parties_dialog.py` | Manjkajoče IR/PR/journal stranke |
| `VatApiCheckDialog` | `ui/vat_api_check_dialog.py` | Preverba ID DDV (VIES/AJPES) |
| `NoveFirmeDialog` | `ui/nove_firme_dialog.py` | Nove firme → SQL/Minimax |
| `SmtpComposeDialog` | `ui/smtp_compose_dialog.py` | Gmail SMTP |
| `UiPrefsDialog` | `ui/ui_prefs_dialog.py` | Videz |
| `AccountMapDialog` | `ui/account_map_dialog.py` | Mapiranje kontov Trops→Minimax |
| `PartyWebResultsDialog` | `ui/party_web_results_dialog.py` | AI/spletni zadetki |
| `ProgressDialog` | `ui/progress_dialog.py` | Dolga opravila |

### 3.4 Obseg Tkinter površine (inventarni števci)

| Datoteka | msgbox | filedialog | Toplevel | Treeview | Notebook |
|---|---:|---:|---:|---:|---:|
| `app.py` | 104 | 6 | 0 | 5 | 1 |
| `pr_editor.py` | 13 | 0 | 4 | 1 | 0 |
| `stranke_dialog.py` | 30 | 0 | 2 | 1 | 0 |
| `integra_dialog.py` | 15 | 2 | 2 | 1 | 0 |
| `ddvo_tab.py` | 15 | 0 | 1 | 2 | 0 |
| `vse_knjizbe_tab.py` | 15 | 0 | 1 | 1 | 0 |
| ostali UI | ~40 | 0 | ~8 | ~8 | 2 |
| **Skupaj (red)** | **~230+** | **~8** | **~20** | **~20** | **~3** |

V končnem LOOK **ni dovoljenih** vidnih `messagebox` / `filedialog` / `Toplevel` / `Treeview` / `Notebook` — nadomestilo: HTML modal / sistemski dialog / HTML tabela.

---

## 4. Popis funkcionalnosti (poslovno jedro — OHRANITI 100 %)

### 4.1 Podjetja in seje
- Nalaganje firm iz EvidencaFirm / KIRKPR registra (`companies.py`)
- Izbira podjetja → preklop SQLite `zst-N.sqlite3`
- Seja: podjetje, iskanje, obdobje, Integra SQL pot, auto IR/PR (`session_prefs.py`)
- UI preference (`ui/styles.py`, `ui_prefs`)

### 4.2 Obdobje
- Mesec/leto, od–do, shift ‹ ›, “Vsa obdobja”
- Revizije obdobja (`-2`, `-3` …) v SQLite
- Briši uvoz obdobja (IR+PR)

### 4.3 Uvoz
- Vasco (mapa/ZIP/3 fiksne poti), Excel IR/PR open
- KIR/KPR datoteka
- Integra: **Obnovi TROPS iz ZIP/BAK**, Preveri TROPS, **UrejanjeKisanal** → SQLite (+ opcijsko IR/PR)
- Konti iz ACCDB / zgodovine SQLite / Minimax kontni plan

### 4.4 IR
- Filtri knjig (Darila, Fitness, Paragoni, Fakture, KIR), status, znesek ≠0, SI/EU/tujina/DDV
- Iskanje, Chk, sortiranje, seštevki
- Konti (privzeto 7620 / EU 76301), shrani pravilo kupca
- Dodaj / Odpri-popravi / Izbriši
- Preveri z API (VAT) + FO način + pošiljanje nepravilnosti
- Potrdi → ready; Sinhroniziraj Minimax (scope IR)

### 4.5 PR
- Filtri: SI/tujina/izključeno/EU10/EU11/oproščeno/76a/multi/SI-DDV/VAT
- Kontrola PR (SI DDV na nedomačem)
- Konti (4190 …), več odhodkov, placilo, journal lines
- Urejevalnik: supplier kind SI/EU/THIRD, samoobdavčitev, AOP logika (25/41 za digitalne tretje države), OS fill
- Potrdi / Sync Minimax

### 4.6 Stranke
- Seznam SQL, združi, nova/uredi/izbriši
- Manjkajoče IR/PR (dialog)
- AJPES / VIES / splet+AI / Minimax pull+push
- Nove firme → SQL

### 4.7 Knjige IR/PR
- Prikaz stolpcev KIR/KPR + DDV-O oznake polj
- Seštevki Σ, iskanje, preklop IR/PR

### 4.8 DDV-O
- Izračun `ddvo_calc.compute_ddvo` (e-DDV_O_11.7)
- Predogled PDF, Izvoz PDF+XML, PDF+virman, e-pošta
- MRN prenesi + primerjava polja 26
- Kartice output/input/result, prevalitev vs SLO DDV, SA 18/19/20
- Seznam prevalitvenih listin → odpri PR

### 4.9 KONTI
- Pivot IR/PR po kontih, odpiranje dokumenta

### 4.10 Vse knjižbe (Integra)
- Pregled journal/kisanal, prenos v Minimax (pravila Integra ≠ Projest — glej `.cursor/rules`)

### 4.11 Analitika
- Besedilni povzetek obdobja / stanj

### 4.12 Minimax / zunanje
- API check, pull strank, sync ready drafts, cleanup drafts
- XML izvoz za KirKpr + odprtje Minimax uvoza
- OS fill (CDP/keyboard/WebView profili — **poslovni motor, ne LOOK**; ohraniti)
- eDavki MRN (Chrome automation / lokalni helper)
- Account map Trops→Minimax

### 4.13 SQLite shema (`db.py`) — NE SPREMINJATI brez ločene odobritve
Tabele: `meta`, `parties`, `account_rules`, `import_batches`, `ir_rows`, `pr_rows`, `journal_lines`, `minimax_accounts`, `account_code_map`  
`Database`: **66** metod (CRUD, sync, journal rebuild, migracije stolpcev …)

### 4.14 Ključni poslovni moduli (brez UI prepisovanja)
`accounts`, `vat_accounts`, `ddvo_calc`, `ddvo_actions`, `excel_map`, `kirkpr_import`, `integra_sql`, `integra_kisanal`, `integra_irpr`, `minimax_*`, `parties_ensure`, `party_web_ai`, `vat_api_check`, `vies_client`, `ajpes_client`, `xml_export`, `vendor_kirkpr/*`, …

---

## 5. Načrt 100-odstotne migracije LOOK (po odobritvi)

### 5.1 Temeljno pravilo
**100 % funkcionalnosti – 100 % podatkov – SAMO NOVI LOOK.**  
Python jedro ostane lastnik SQL/API/izračunov. HTML/CSS/JS + WebView2 = prikaz in interakcija.

### 5.2 Ciljna tehnična zasnova (po QUICK eDAVKI PRO)
1. Novo samostojno **`Trops_Studio_V3.1.00.pyw`** (+ symlink/alias `Trops_Studio.pyw`)
2. Motor: **pywebview** + `gui='edgechromium'` (WebView2)
3. Lokalni HTML/CSS/JS (pregledne datoteke, ne nujno B85; lahko kasneje pakiranje)
4. **Bridge** Python ↔ JS: dovoljen seznam akcij (tipizirani argumenti), brez poljubnega `eval` / surovega SQL iz JS
5. Dolga opravila: background thread + progress events (nadomestilo `ProgressDialog` + `root.after`)
6. Levi drevesni panel = edina navigacija (PODJETJA + VSEBINA + morebitne podskupine Datoteka/Nastavitve)
7. Modalni HTML dialogi namesto vseh `Toplevel`
8. HTML tabele z CHK/sort/filter namesto `Treeview`
9. Sistemski `filedialog`/`askdirectory` dovoljeni, kjer OS dialog ostane potreben (enako kot v master promptu)
10. Tkinter sme ostati **samo** kot nevidna tehnična odvisnost, če nujno — **ne** kot viden UI

### 5.3 Predlagana struktura novih datotek (brez brisanja `3.0.03`)
```
Trops/
  backups/pred_webview2_3_0_03_<stamp>/   # varnostna kopija
  Trops_Studio_V3.1.00.pyw
  INSTALL.pyw
  trops_studio/           # obstoječe poslovno jedro (večinoma nedotaknjeno)
  trops_studio_web/       # NOV LOOK sloj
    ui/
      index.html
      css/app.css
      js/app.js
      js/bridge.js
      js/views/*.js
    api_bridge.py         # dovoljene akcije → klici obstoječih modulov
    host.py               # pywebview window + start
  docs/
    WEBVIEW2_MIGRACIJA_ANALIZA_3.0.03.md   # to poročilo
    WEBVIEW2_IZVEDBA_3.1.00.md             # po implementaciji
```

### 5.4 Faze izvedbe (po odobritvi)
| Faza | Vsebina | Merilo uspeha |
|---|---|---|
| **0** | Backup `3.0.03`, bump verzije na `3.1.00` (nova veja datotek), `INSTALL.pyw` ogrodje | Stara verzija se še zažene |
| **A** | Host + lupina LOOK + levi tree + status + obdobje + podjetja | Navigacija deluje, podatki se berejo |
| **B** | IR + PR seznami + filtri + Chk + konti + potrdi/sync gumbi | Enaki filtri/rezultati kot 3.0.03 |
| **C** | Editorja IR/PR + Stranke + manjkajoče | Shramba v SQLite enaka |
| **D** | DDV-O + Knjige + KONTI + Analitika | AOP/zneski identični `compute_ddvo` |
| **E** | Integra dialog + Vse knjižbe | ZIP/BAK/Kisanal nespremenjen |
| **F** | Meni akcije, SMTP, UI prefs, VAT API, XML, MRN | Vsi gumbi povezani |
| **G** | QA checklist, poročilo izvedbe, namestilnik | Enakovrednost ali izrecno “ni preverjeno” |

### 5.5 Predlagani seznam sprememb (za odobritev)
1. Ustvariti backup mape `3.0.03`.
2. Dodati `trops_studio_web/` (HTML/CSS/JS + bridge + host).
3. Dodati `Trops_Studio_V3.1.00.pyw` in `INSTALL.pyw` (Python 3.10, pywebview, WebView2 Runtime).
4. `__version__` v novi veji → `3.1.00` (izvorna kopija v backup ostane `3.0.03`).
5. **Ne** spreminjati sheme SQLite, Minimax payloadov, DDV formul, Integra RESTORE logike.
6. Posodobiti `.cursor/rules/webview2-migration.mdc` (že pripravljeno).
7. Po fazah A–G: QA + `docs/WEBVIEW2_IZVEDBA_3.1.00.md`.

---

## 6. Analiza regresijskih tveganj

| Tveganje | Nivo | Zakaj | Blažitev |
|---|---|---|---|
| Izguba akcij v `app.py` (104+ messagebox poti) | **KRITIČNO** | Vsaka potrditev/opozorilo je del toka | Inventar akcij → bridge whitelist; QA checklist gumb za gumbom |
| PR editor (kompleksna DDV/OS logika) | **KRITIČNO** | Napaka = napačni AOP / Minimax | UI samo prikaz; shrani kliče obstoječi `PrEditor` model / `db.upsert_pr` |
| Integra RESTORE + Kisanal | **VISOKO** | SQL Server destruktivne operacije | Ne prepisovati `integra_sql.py`; UI samo kliče obstoječe funkcije; potrditveni modal |
| Threading (`root.after` → JS events) | **VISOKO** | Race / zamrznjen UI / dvojni sync | En job manager z ID, disable gumbi med tekom |
| Minimax OS fill / CDP / Chrome | **SREDNJE** | Ločen motor od LOOK | Ne migrirati v WebView2 UI; ohraniti obstoječe module |
| Filtri IR/PR (veliko BooleanVar) | **SREDNJE** | Napačen filter = napačen sync nabor | Primerjava števcev vrstic 3.0.03 vs 3.1.00 |
| DDV-O polja / MRN 26 | **VISOKO** | Davčna napaka | Side-by-side zneski za isto obdobje (npr. zst-21 oktober 2026) |
| Seja / poti / per-company DB | **SREDNJE** | Napačna baza | Enaki `session.json` + `company_db_path` |
| DPI / tipkovnica / fokus | **SREDNJE** | WebView2 tipkovnica ≠ Tk | Test Tab/Enter/Esc/F5/Ctrl+O |
| Datotečni dialogi | **NIZKO** | Sistemski OK | pywebview/OS dialog |
| Obseg dela (16 UI modulov) | **VISOKO** | Nedokončana migracija | Faze; dokler funkcija ni preverjena = ni “uspešno” |

**Uspešna migracija** = enaki rezultati kot `3.0.03` za isto podjetje/obdobje (IR/PR števci, DDV-O AOP, Minimax sync status, SQLite vsebina).  
Vse nepreverjeno izrecno označiti.

---

## 7. Referenca QUICK eDAVKI PRO (vzorec)

- Verzija reference: **1.0.72**
- `pywebview` + `edgechromium` + lokalni API server / HTML lupina
- Levi navigacijski panel, modalni HTML, brez vidnega Tk LOOK
- Namestilnik `NAMESTI_…pyw`
- Trops bo sledil **istemu LOOK standardu**, vendar z lastnim bridge na Trops module (ne kopirati eDAVKI poslovne logike).

---

## 8. Omejitve okolja / odprta vprašanja za odobritev

1. **Ciljna verzija:** predlagam `3.1.00` (alternativa: `3.0.04`). Potrdi.
2. **Obseg v enem koraku:** polna A–G migracija (velik projekt) ali najprej faza A (lupina) z vmesno odobritvijo?
3. **OS fill / Chrome CDP:** ohranimo kot zunanji motor (priporočeno) — potrdi.
4. **Workspace:** koda je v `D:\PISARNA\Python\Trops` (ne v `Projest`). Potrdi, da delamo tam.
5. **Python:** 3.10 + `INSTALL.pyw` z `pywebview` — potrdi.

---

## 9. Sklep

| Postavka | Status |
|---|---|
| Analiza kode / UI / podatkov | **OPRAVLJENO** |
| Popis funkcionalnosti | **OPRAVLJENO** |
| Načrt migracije | **OPRAVLJENO** |
| Regresijska tveganja | **OPRAVLJENO** |
| Spremembe kode | **NI ZAČETO — čakam odobritev** |
| Nova `.pyw` / `INSTALL.pyw` | **NI ZAČETO** |

**Prosim za izrecno odobritev** (npr. »ODOBRIM migracijo Trops 3.1.00 WebView2«) z odgovori na točke v §8.  
Brez te odobritve **ne bom spreminjal** kode, baz, konfiguracije ali obstoječih programskih datotek.
