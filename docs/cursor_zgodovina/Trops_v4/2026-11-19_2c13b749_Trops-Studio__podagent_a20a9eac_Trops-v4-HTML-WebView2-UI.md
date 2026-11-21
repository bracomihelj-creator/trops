# Podagent: Trops_v4 HTML WebView2 UI

- **Projekt (Cursor):** `D:/PISARNA/Python/Trops_v4`
- **ID pogovora:** `a20a9eac-d949-41e3-a0f4-bf1795bcb227` (podagent pogovora `2c13b749-d604-4633-b119-2502b00db6d8`)
- **Ustvarjen:** 2026-11-19 01:52  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Trops-v4\agent-transcripts\…\a20a9eac-d949-41e3-a0f4-bf1795bcb227.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Thursday, Nov 19, 2026, 1:52 AM (UTC+1)

Create the WebView2 LOOK UI for Trops Studio 4.0.01 in D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\

Create these files:
1. index.html
2. css/app.css
3. js/bridge.js
4. js/app.js
5. js/views.js (optional if large — can merge into app.js)

DESIGN (QUICK eDAVKI PRO style, NOT purple AI-default):
- Left collapsible tree navigation panel (resizable): sections PODJETJA (search + company list) and VSEBINA (tree nodes)
- Main content area switches views without top Notebook tabs
- Header with brand "Trops Studio", version 4.0.01, workflow hint, action buttons
- Period bar, source/summary collapsible panels
- Status bar at bottom
- CSS variables for theme; light professional teal/slate look (avoid purple gradients, cream+terracotta, Inter/Roboto)
- Use fonts like "Segoe UI", "IBM Plex Sans" or "Source Sans 3" via system/stack — expressive but Windows-friendly
- Subtle gradients/atmosphere OK

NAV TREE NODES (must match):
- ir, pr, ddvo, knjige (children knjiga_ir, knjiga_pr), konti, parties, analysis, knjizbe
Also include group "Orodja" for: integra, import, settings if space

VIEWS to implement in JS (call window.pywebview.api.* or bridge helpers):
- IR table with filters, search, chk, toolbar (Potrdi, Sync, accounts, Dodaj, Odpri, Izbriši, Preveri API)
- PR table similarly
- DDV-O summary cards + fields table + action buttons
- Knjige IR/PR
- KONTI
- Stranke
- Analitika (pre text)
- Vse knjižbe
- Modal system for alerts/confirm/forms (replace messagebox)
- Company select from left list

bridge.js:
- async api(method, ...args) wrapping pywebview.api
- toast/modal helpers
- safe JSON

app.js:
- boot on DOMContentLoaded; wait for pywebviewready
- load bootstrap state
- wire nav, period, buttons
- render tables from API data
- keyboard F5 refresh, Escape close modal

IMPORTANT:
- Slovenian UI labels matching Trops Studio 3.0.03
- No Tk references
- All user-visible dialogs = HTML modals
- File pick may call Python bridge which uses system dialog

Also create host.py at D:\PISARNA\Python\Trops_v4\trops_studio_web\host.py that:
- starts pywebview with gui='edgechromium'
- loads index.html via file URL or http.server localhost
- js_api from api_bridge.TropsJsApi (import; if missing create a thin stub that imports AppService)
- window title Trops Studio 4.0.01
- storage_path under data/webview_profile

Write complete files. Return summary of created paths.

### 🤖 Asistent

Ustvarjam WebView2 LOOK UI za Trops Studio 4.0.01 — najprej pregledam obstoječo strukturo in API most.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/*
- 🔧 `Grep` — D:\PISARNA\Python\Trops_v4
- 🔧 `Grep` — D:\PISARNA\Python\Trops_v4

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\docs\WEBVIEW2_MIGRACIJA_ANALIZA_3.0.03.md
- 🔧 `Grep` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Glob` — **/AppService*

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops_v4\trops_studio

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py

- 🔧 `Grep` — D:\PISARNA\Python\Trops_v4
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\__init__.py

Ustvarjam popolne datoteke UI in host modul.

- 🔧 `UpdateCurrentStep`
- 🔧 `Shell` — Create trops_studio_web directory structure

- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\api_bridge.py
- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\host.py

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\api_bridge.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\host.py

- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html

- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\css\app.css
- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\js\bridge.js

- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\js\views.js

- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\js\app.js

- 🔧 `Shell` — Verify Python syntax of bridge and host
- 🔧 `Glob` — **/*

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\__init__.py

- 🔧 `UpdateCurrentStep`

Ustvarjen je WebView2 LOOK sloj **Trops Studio 4.0.01**. Poleg zahtevanih UI datotek je dodan še `api_bridge.py`, ker ga `host.py` uvozi kot `TropsJsApi`.

### Ustvarjene poti

| Datoteka | Vloga |
|---------|--------|
| `D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\index.html` | Lupina: header (workflow, gumbi), obdobje, collapsible vir/povzetek, levi panel (PODJETJA + VSEBINA + Orodja), main, status, modal |
| `D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\css\app.css` | Teal/slate tema (CSS variables), tabele, modal, toast — brez purple AI looka |
| `D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\js\bridge.js` | `api(method, …)`, toast, HTML modal (alert/confirm) |
| `D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\js\views.js` | Predloge pogledov IR/PR/DDV-O/knjige/KONTI/Stranke/Analitika/Vse knjižbe |
| `D:\PISARNA\Python\Trops_v4\trops_studio_web\ui\js\app.js` | Boot (`DOMContentLoaded` + `pywebviewready`), navigacija, F5 osveži, Esc zapre modal |
| `D:\PISARNA\Python\Trops_v4\trops_studio_web\host.py` | `webview.start(gui='edgechromium')`, profil `data/webview_profile`, UI prek `http://127.0.0.1:18765/` ali `file://` |
| `D:\PISARNA\Python\Trops_v4\trops_studio_web\api_bridge.py` | `TropsJsApi` + `AppService` (stub: vzorčna podjetja, prazne tabele, akcije z `noop_action`) |

### Navigacijsko drevo (kot 3.0.03)

IR, PR, DDV-O, Knjige IR/PR (podvozlišča), KONTI (pivot), Stranke, Analitika, Vse knjižbe; skupina **Orodja**: Integra SQL, Uvoz, Nastavitve.

### Zagon

```text
python D:\PISARNA\Python\Trops_v4\trops_studio_web\host.py
```

Potrebno: `pywebview` in Edge WebView2 Runtime.

### Opomba

To je **faza A LOOK** — UI in bridge so pripravljeni; jedro še ni vezano na `trops_studio.ui.app` (tabele so prazne, akcije vračajo stub). Enakovrednost s 3.0.03 **ni preverjena**. Naslednji korak: vezava metod v `AppService` na obstoječe module.
