# Trops Studio 5.0.00: spremembe glede na 4.0.01

Izvor je `Trops_v4`, ki je ostal **nespremenjen**. Vse delo je bilo opravljeno na kopiji `Trops_v5` z git zgodovino (14 commitov, en commit na korak).

## 1. Namestitev na Windows

1. Razpakiraj `Trops_v5.zip` v `D:\PISARNA\Python\`. Nastane mapa `D:\PISARNA\Python\Trops_v5`.
2. Odpri ukazni poziv v tej mapi in zaženi:
   `py -3.10 -m pip install -r requirements.txt`
   Lahko pa dvoklikneš `INSTALL.pyw`. Ta preveri pakete in **ponudi kopijo** baz iz `..\Trops_v4\data`.
3. Zaženi `Zazeni_Trops_Studio_V5.bat` ali `Trops_Studio_V5.0.00.pyw`.
4. Preveri, da so v `settings.json` prave D:\ poti. Privzeto so enake kot v v4.

### Odločitev: kje so podatki

Baze `zst-XX.sqlite3` so v mapi aplikacije `data\`. V zipu jih **ni**.

* **A) Ločene baze (privzeto):** v5 uporablja `Trops_v5\data`. Ob prvem zagonu `INSTALL.pyw` ponudi kopijo iz v4. Kopija je ločena: kar spremeniš v v5, se v v4 ne vidi, in obratno.
* **B) Skupne baze z v4:** v `settings.json` nastavi
  `"data_dir": "D:\\PISARNA\\Python\\Trops_v4\\data"`.
  Obe verziji takrat delata na istih bazah. Ne poganjaj ju hkrati.

## 2. Popravki napak (kritično in pomembno)

| Področje | Prej (4.0.01) | Zdaj (5.0.00) |
|---|---|---|
| DDV-O kartice / Analitika | napačni ključi, obveznost se ni prikazala | `output_vat`, `input_vat`, `obligation`/`excess`, `control_ok`. Analitika prikaže 6.828,00 |
| Shranjevanje vrstice | ustvarjalo dvojnike (brez `row_id`) | posodobi obstoječo vrstico po `id`. Shranjevanje brez sprememb ohrani status »v Minimaxu« |
| Brisanje obdobja | brisalo tudi vrstice brez datuma, brez potrditve | vrstice brez datuma ostanejo. Pred brisanjem je predogled števila in potrditveno okno s kljukico. Strežnik zahteva `confirm:true` |
| Integra RESTORE | vzel prvo kopijo brez vprašanja | seznam ZIP/BAK, izbira, dvojna potrditev. Kopija mora biti na seznamu najdenih |
| Sinhronizacija Minimax | brez potrditve, gumb ni bil zaklenjen | predogled (IR/PR/stranke/že poslane), potrditev, ozadna naloga z napredkom, gumb zaklenjen. `ok` je pravilen, napake se izpišejo |
| `minimax_journals` | označil »poslano« tudi ob napaki | »poslano« samo ob uspehu, sicer »napaka« |
| Odznači | delalo samo v brskalniku | počisti izbor tudi v ozadju (`set_chk_all` brez `ids` pomeni vse filtrirane) |
| Format napak | mešano (`msg`/`error`/`message`) | vedno `{"ok":false,"error":"…","msg":"…"}`. 400 napačen vnos, 404 ne obstaja, 409 zasedeno, 500 notranja napaka |
| Neveljaven ID | 500 s sledjo | 400 ali 404 JSON |
| Iskalna polja | večina ni bila povezana | IR/PR (strežniški filtri), Stranke, Knjižbe (strežnik), Knjige, Konti, DDV-O (lokalno) |
| Vasco uvoz | ena datoteka, napačen izbirnik | več datotek (`pick_excel_multi`), samodejna razvrstitev IF*→IR in kp*→PR |
| Fiksno leto 2026 | Kisanal in Tk Integra | privzeto leto obdobja ali tekoče leto |
| Urejanje | samo nekaj polj | pravi obrazec IR (25 polj) / PR (40 polj) z validacijo (obvezna polja, zneski, kontrola Skupaj = osnova + DDV) |
| DDV-O gumbi | manjkali v spletnem UI | Predogled PDF, XML+PDF za eDavke, PDF+virman (UPN QR), E-pošta stranki, eDavki MRN |
| E-pošta | — | osnutek, urejanje Za/Kp/Zadeva, predogled v peskovniku, izbira priponk, kljukica »Pregledal sem«, potrditev. **Nikoli samodejno.** Priponke samo iz zadnjega paketa virmana |
| Dolge akcije | blokirale UI | ozadne naloge (`/api/job`) z oknom napredka, ena hkrati (409) |
| Seznam podjetij | tiho prazen | vidno opozorilo (EvidencaFirm/KirKpr ni dosegljiv) |
| Logiranje | `except: pass` | rotirajoči dnevnik `data\logs\trops.log` (2 MB × 5) na poteh sync/db/service/minimax |
| D:\ poti | raztresene po kodi | `trops_studio/config.py` + `settings.json` (+ `settings.local.json`, okolje `TROPS_<KLJUČ>`) |
| `kirkpr_company_registry` | — | popravljena sintaksna napaka iz zgodnjega koraka v5. Odkrita z ruff in popravljena pred paketom |
| Piškotek seje | `trops4` | `trops5`, da se v4 in v5 ne motita |
| Tvegane naloge | — | `integra_restore`, `delete_import_period` in `ddvo_email_send` se brez `confirm:true` ne začnejo niti kot ozadna naloga |

## 3. Odstranjeno

* `projest.py`. `projest_analiza.txt` je premaknjen v `docs/PROJEST_ANALIZA_LEGACY.txt`.
* `trops_studio_web/api_bridge.py`: star most, ki ga ni nihče uporabljal.
* `trops_studio/os_fill_bridge.py`: neuporabljen lokalni HTTP most na vratih 18765.
* `trops_studio/ui/row_editor.py`: neuporabljen. Tk uporablja `ir_editor`/`pr_editor`.
* `Zaženi_Projest_Studio.bat` in pokvarjeno ime `Za+�eni_Trops_Studio.bat`. Novi zaganjalnik je `Zazeni_Trops_Studio_V5.bat` (ASCII ime, CRLF, fallback na `py -3`).
* `/api/meta`, neuporabljene akcije gostitelja, debug datoteke `data/_*` in `*.bak`.
* Neuporabljeni uvozi in spremenljivke (ruff, samo varni popravki). Dodan `ruff.toml`.

**Tk urejevalnik ostane.** Dosegljiv je iz *Nastavitve → Klasični urejevalnik (Tk)*, ker ima funkcije, ki jih spletni UI še nima:

* preslikava kontov Trops→Minimax, kontni plan Minimax→SQL, konti iz ACCDB;
* VAT API preverba (zadnja preverba IR/PR/FO);
* brisanje Minimax osnutkov obdobja;
* urejanje in nove stranke (AJPES/VIES/AI iskanje);
* kontrola PR SI DDV, odpri Excel IR/PR, vpis OS v Minimax, SMTP test, nastavitve videza, urejanje Kisanal, nove firme.

## 4. Nov videz (spletni UI)

* Temna stranska vrstica z ikonami in števci:
  * IR, PR, DDV-O;
  * Knjiga IR/PR, Konti, Vse knjižbe;
  * Stranke, Analitika;
  * meniji Uvoz, Minimax in Nastavitve.
* Zgornja vrstica:
  * izbirnik podjetja z iskanjem;
  * izbirnik obdobja (mesec, četrtletje, polletje, leto ali datumi po meri) s puščicami ‹ ›;
  * Osveži (F5), tema, Sinhroniziraj.
* KPI kartice na vsakem pogledu. DDV-O ima poudarjeno kartico »Obveznost (51)« ali »Presežek (52)« in kartico kontrole usklajenosti.
* Tabele:
  * lepljiva glava in noga z vsotami, zebra vrstice, razvrščanje s klikom na stolpec;
  * značke statusov (Shranjeno, Osnutek, v Minimaxu, napaka …);
  * izbor s kljukicami, dvoklik odpre urejanje, prikaz po 400 vrstic z gumbom »Prikaži vse«.
* Modalna okna, obvestila (toasti), vrtavke, okno napredka za ozadne naloge.
* Svetla in temna tema (zapomni si izbiro). Vse oznake so slovenske. Bližnjice: Esc, F5, Ctrl+F.
* Brez CDN in zunanjih virov. Ikone so inline SVG.
* Posnetki so v `/workspace/trops_v5_screens/`:
  * `prej_*.png` (v4) in `potem_*.png` (v5) za IR, PR, DDV-O, Stranke in Analitiko;
  * `potem_IR_temna.png` in `potem_DDV-O_temna.png` (temna tema).

## 5. Testi (Linux, brez omrežja)

* `pytest`: **40/40 uspešnih**. Na čisti razpakirani kopiji brez baz je rezultat 35 uspešnih in 5 preskočenih (testi z realnimi zneski).
  * DDV-O Zšt 21, oktober 2026:
    * izstopni DDV 19.983,00, vstopni 13.155,00, obveznost 6.828,00;
    * **XML f51 = 6828**;
    * 186 IR, 56 PR.
  * Brisanje obdobja ohrani vrstice brez datuma in vrstice drugih obdobij. Strežnik zahteva potrditev.
  * Shranjevanje brez dvojnikov. Nespremenjena vrstica ohrani sync status.
  * Odznači v ozadju, prazna potrditev vrne 400, napačen ID vrne 400, e-pošta brez potrditve vrne 400.
  * Strežnik:
    * seja 403 in tuj Host 403, piškotek;
    * 400/404 JSON z `error` = `msg`;
    * ozadna naloga in zavrnitev druge naloge;
    * 404 za neznano nalogo, opozorilo pri praznem seznamu podjetij.
  * Povezave JS↔Python:
    * vsaka akcija v `app.js` obstaja v `host.py` in vsak endpoint obstaja;
    * metode Bridge, id-ji HTML, menijske akcije in pogledi so povezani;
    * ni CDN.
  * Dimni test v brskalniku (Chrome/Playwright): 186 vrstic, urejevalnik, DDV-O 6.828,00, vsi pogledi, brez JS napak.
* `ruff check .`: brez napak. `compileall` za vse `.py` in `.pyw` datoteke: OK. `node --check ui/app.js`: OK.
* Testi blokirajo vse zunanje povezave. Minimax, eDavki, AJPES in SMTP niso bili klicani, poverilnice niso bile uporabljene.

## 6. Ni preizkušeno na Linuxu: preveri na Windows

1. Zagon okna WebView2 (`pywebview`) in sistemski izbirniki datotek: Vasco (več datotek), KIR/KPR, SQL mapa.
2. Klasični Tk urejevalnik (na Linuxu ni tkinterja). Odpri ga iz menija Nastavitve.
3. Minimax:
   * *Preveri API*;
   * *1 · Stranke iz Minimax*;
   * na enem testnem računu: *4 · Potrdi* → *Sinhroniziraj*. Preveri osnutek temeljnice in da ni dvojnika.
4. DDV-O:
   * Predogled PDF in XML+PDF za eDavke (mapa `D:\Trops\{Zšt}\DDV`);
   * PDF+virman (UPN QR, IBAN iz AJPES);
   * E-pošta stranki: najprej pošlji **sebi**.
5. eDavki MRN (digitalno potrdilo).
6. Integra: seznam ZIP/BAK v `D:\Trops\20\SQL`, RESTORE na testni kopiji, UrejanjeKisanal (KONT*.DBF).
7. Izvoz XML za KirKpr (`D:\Trops\{Zšt}\MiniMax`).
8. `INSTALL.pyw`: ponudba kopije podatkov iz v4.
9. Dnevnik `data\logs\trops.log` se ustvari in ne raste čez 10 MB.

## 7. Za razvijalca

* `py -3.10 -m pip install -r requirements-dev.txt`, nato `py -3.10 -m pytest -q tests` in `py -3.10 -m ruff check .`
* Struktura, nastavitve in zunanji D:\ moduli so opisani v `README.md`:
  * KirKpr: `kirkpr_upn_qr`, `kirkpr_ajpes_iban`, `kirkpr_ddvo_placeholder_texts`;
  * EvidencaFirm: `firme_evidenca.json`, AJPES moduli;
  * Chrome_add: `smtp_secret.bin`.
* Skrivnosti: v izvorni kodi ni gesel ali žetonov. SMTP geslo se bere iz zunanje datoteke `smtp_secret.bin` (DPAPI). Nastavitve z gesli in ključi (`ai_settings.json`, `minimax_api_settings.json`) so v `.gitignore` in niso v zipu. Kontaktni e-naslovi so v `kirkpr_ddvo_smtp.py:18` in `ddvo_actions.py:196-220`.
