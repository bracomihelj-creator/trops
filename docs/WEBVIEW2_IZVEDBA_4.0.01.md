# Trops Studio 4.0.01 — izvedba (popravljeno po Evidence 8)

**Datum:** 19. 11. 2026  
**Odobritev:** DA — verzija `4.0.01`, mapa `Trops_v4`, migracija A–G.  
**Popravek:** prejšnji hibrid (podvojen `ui/`, js_api skropucalo) zamenjan z **istim vzorcem kot Evidence 8 / Pooblastila**.

---

## Vzorec (referenca)

| Aplikacija | Kaj smo vzeli |
|---|---|
| **EvidencaFirm 8** | `Evidence_8.pyw` → `host.desktop()`, HTTP `/api/*` + ticket, `ui/index.html|app.css|app.js`, `Bridge` samo za datoteke, QUICK paleta |
| **Pooblastila v5** | WebView2 + Edge, trajni profil, poslovno jedro ločeno od LOOK |
| **Fakturiranje v7** | QUICK accent `#5968e8`, levi meni / navigacija, samo LOOK |

## Struktura zdaj

```
Trops_v4/
  Trops_Studio_V4.0.01.pyw
  Trops_Studio.pyw
  host.py                 # HTTP AppServer (kot Evidence)
  motor.py                # Motor → AppService
  ui/index.html
  ui/app.css
  ui/app.js
  INSTALL.pyw
  Zaženi_Trops_Studio.bat
  trops_studio/           # poslovno jedro
  trops_studio_web/service.py
```

Odstranjeno: podvojen `trops_studio_web/ui/`, `ui/css|js` razdrobljenost, host na SimpleHTTP+js_api za poslovne akcije.

## Chrome CDP

**Ne za LOOK.** Ostane samo za opcijski vpis OS v Minimax (`minimax_os_fill`).

## Smoke test (19. 11. 2026)

Seja `zst-21` / oktober 2026:

| Preverba | Rezultat |
|---|---|
| `Motor.boot()` | OK, verzija 4.0.01, Zšt 21 |
| IR / PR | 186 / 56 |
| DDV-O polja | 32 |
| HTTP `GET /api/boot` | OK |
| HTTP `GET /api/ir` | 186 |
| `py_compile` host/motor | OK |

## Še ročno v GUI (izrecno)

| Funkcija | Status |
|---|---|
| Levi panel + vsi pogledi | **Pripravljeno** — preveri v WebView2 oknu |
| Bogati PR/IR HTML urejevalnik (vsa polja 3.0.03) | **Delno** — dvoklik odpre JSON; polni obrazec še |
| Integra RESTORE / Kisanal | **API + modal** — ročno potrdi na ZIP/BAK |
| VAT API tabela | **Jedro ohranjeno** — UI tabela še |
| OS fill | **Modul ohranjen** (ni LOOK) |
| SMTP / virman / PDF gumbi DDV-O | **Jedro ohranjeno** — gumbe še povezati |

## Zagon

1. `INSTALL.pyw` (pywebview)  
2. `Trops_Studio_V4.0.01.pyw` ali `Zaženi_Trops_Studio.bat`  
3. Izvorna Tk **3.0.03** ostane v `D:\PISARNA\Python\Trops`
