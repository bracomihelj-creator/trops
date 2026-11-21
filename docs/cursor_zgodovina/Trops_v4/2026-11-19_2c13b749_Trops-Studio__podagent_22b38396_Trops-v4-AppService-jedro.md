# Podagent: Trops_v4 AppService jedro

- **Projekt (Cursor):** `D:/PISARNA/Python/Trops_v4`
- **ID pogovora:** `22b38396-690a-41be-af3e-d689110b678c` (podagent pogovora `2c13b749-d604-4633-b119-2502b00db6d8`)
- **Ustvarjen:** 2026-11-19 01:52  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Trops-v4\agent-transcripts\…\22b38396-690a-41be-af3e-d689110b678c.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Thursday, Nov 19, 2026, 1:52 AM (UTC+1)

You are implementing the Python service layer for Trops Studio WebView2 migration in D:\PISARNA\Python\Trops_v4.

GOAL: Create `trops_studio_web/service.py` — a headless AppService that preserves 100% business behavior of Trops Studio 3.0.03 without any Tkinter UI widgets.

CONTEXT:
- Source Tk app: `trops_studio/ui/app.py` class `ProjestStudioApp` (~5300 lines)
- Business modules stay in `trops_studio/*` (db, companies, accounts, ddvo_calc, minimax_*, integra_*, etc.)
- Version will be 4.0.01
- Data: per-company SQLite via `company_db_path`, session via `session_prefs`

REQUIREMENTS for AppService:
1. Hold state: active company, period from/to, filters (IR/PR/party search, book checkboxes, status/amount/region filters), caches for ir/pr/parties lists, integra_sql_dir, ui prefs paths.
2. Methods must return JSON-serializable dicts/lists (str/int/float/bool/None/list/dict). Convert dates to ISO or SI text, Decimals to money strings using existing `trops_studio.money` helpers.
3. Implement at minimum these API groups (call existing modules, do NOT reimplement DDV math):
   - bootstrap(), get_status()
   - list_companies(search), select_company(key), get_company()
   - get_period(), set_period(...), shift_period(delta), reset_period()
   - refresh_all()
   - list_ir(filters), list_pr(filters), list_parties(search)
   - get_ir(id), get_pr(id), save_ir(payload), save_pr(payload), delete_rows(kind, ids)
   - apply_ir_account(ids, account, remember), apply_pr_account(ids, account, remember)
   - confirm_selected(kind, ids), sync_ready_minimax(scope)
   - sync_minimax_parties(), check_minimax_api()
   - compute_ddvo(), knjige_data(book), konti_data(), analysis_text()
   - import stubs that call existing import_vasco/kirkpr/integra functions where possible with progress callbacks returning messages
   - open paths helpers returning path strings (Excel open via os.startfile)
4. Use `trops_studio.config`, `Database`, `load_companies`, period helpers from `trops_studio.ui.period` (period.py has no Tk widgets — OK to import).
5. Do NOT import tkinter anywhere in service.py.
6. Also create `trops_studio_web/__init__.py` with `__version__ = "4.0.01"`.
7. Also create `trops_studio_web/api_bridge.py` with a class `TropsJsApi` that wraps AppService methods for pywebview js_api (each public method catches exceptions and returns `{ok:false, error:str}` or `{ok:true, ...}`).

Read existing modules as needed before writing. Prefer calling existing functions from app.py logic (copy orchestration carefully).

For list_ir/list_pr: reuse filtering concepts from app.py `_populate_ir_tree` / `_populate_pr_tree` / pr_list_view / ir_list_view — read those methods.

Write complete working files. Keep code concise but complete enough for UI to function.

Return a short summary of files created and method list.

### 🤖 Asistent

Za migracijo WebView2 najprej pregledam obstoječo strukturo in logiko v `app.py`.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/trops_studio_web/**
- 🔧 `Grep` — def _populate_ir_tree|def _populate_pr_tree|class ProjestStudioApp
- 🔧 `Glob` — **/trops_studio/ui/period.py

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Grep` — ^\s+def 
- 🔧 `Glob` — **/ir_list_view*
- 🔧 `Glob` — **/pr_list_view*

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Grep` — AppService|trops_studio_web

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\docs\WEBVIEW2_MIGRACIJA_ANALIZA_3.0.03.md
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py

- 🔧 `Grep` — def (import_vasco|import_kirkpr|delete_|get_ir|get_pr|compute_ddvo|open_|learn_accounts)
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\knjige.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\konti_tab.py

- 🔧 `Grep` — def refresh|def export|def data
- 🔧 `Grep` — def refresh
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\knjige.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\ddvo_tab.py
- 🔧 `Grep` — def serialize|to_json|_row_dict
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\__init__.py

- 🔧 `Grep` — integra
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\konti_pivot.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\session_prefs.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\styles.py

- 🔧 `Grep` — def load_ui_prefs
- 🔧 `Grep` — def collect_pivot_lines
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\row_status.py

- 🔧 `Glob` — **/integra*.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\money.py

- 🔧 `Grep` — def date_text
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py

- 🔧 `Grep` — ^def 
- 🔧 `Grep` — ^def 
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\config.py

- 🔧 `Grep` — def (import_|sync_|run_|uvoz)
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ddvo_calc.py

- 🔧 `Grep` — def compute_ddvo
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\integra_irpr.py

- 🔧 `Grep` — class.*Result|NamedTuple
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\konti_pivot.py

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\minimax_runtime.py

- 🔧 `Grep` — def import_vasco_files_to_db

Implementiram tri datoteke servisnega sloja.

- 🔧 `UpdateCurrentStep`
- 🔧 `Shell` — Create trops_studio_web package directory

- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\__init__.py

- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `Grep` — def delete_parties
- 🔧 `Shell` — Syntax-check service.py

- 🔧 `Grep` — delete_.*part
- 🔧 `Grep` — def compute_ddvo

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `Grep` — ^class 

- 🔧 `Glob` — **/trops_studio_web/*
- 🔧 `Grep` — def 
- 🔧 `Glob` — **/trops_studio_web/api_bridge.py

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\__init__.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\api_bridge.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `Grep` — import tkinter|from tkinter

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\api_bridge.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `Grep` — build_konti_pivot

- 🔧 `Grep` — def get_period|def get_company
- 🔧 `Grep` — def build_konti_pivot
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `Grep` — def sync_ready_to_minimax|def confirm_documents|def remember_customer_rule
- 🔧 `Grep` — def import_vasco_files_to_db

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\minimax_sync.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\accounts.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

Popravljam kritične napake v `service.py` in prepisujem `api_bridge.py`, da uporablja pravi `AppService`.

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `Grep` — build_konti|compute_ddvo\(
- 🔧 `Grep` — remember_customer_rule|remember_supplier_rule|confirm_documents|sync_ready_to_minimax

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio\konti_pivot.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `Grep` — remember_customer_rule|pick_file|import_vasco_paths|konti_data
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `Read` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops_v4\trops_studio_web\service.py
- 🔧 `Write` — D:\PISARNA\Python\Trops_v4\trops_studio_web\api_bridge.py

- 🔧 `Grep` — tkinter
- 🔧 `Shell` — Syntax-check service and api_bridge
- 🔧 `Shell` — Smoke-test TropsJsApi bootstrap

- 🔧 `UpdateCurrentStep`

## Datoteke

| Datoteka | Vloga |
|---------|--------|
| `trops_studio_web/__init__.py` | `__version__ = "4.0.01"` |
| `trops_studio_web/service.py` | `AppService` — headless orkestracija (logika kot `ui/app.py`, **brez tkinter**) |
| `trops_studio_web/api_bridge.py` | `TropsJsApi` — pywebview `js_api`, ovija `AppService`, JSON parametri, `pick_file`/`pick_directory` (tkinter samo tukaj) |

Smoke test: `bootstrap()` → verzija `4.0.01`, `list_companies` → `ok: true`.

## `AppService` — javne metode

**Jedro:** `bootstrap`, `get_status`, `get_company`, `get_period`  
**Podjetja:** `list_companies`, `select_company`  
**Obdobje:** `set_period`, `shift_period`, `reset_period`, `set_filters`  
**Podatki:** `refresh_all`, `list_ir`, `list_pr`, `list_parties`, `set_chk`, `set_chk_all`  
**CRUD:** `get_ir`, `get_pr`, `save_ir`, `save_pr`, `delete_rows`  
**Konti / sync:** `apply_ir_account`, `apply_pr_account`, `confirm_selected`, `sync_ready_minimax`, `sync_minimax_parties`, `check_minimax_api`  
**DDV / poročila:** `compute_ddvo`, `knjige_data`, `konti_data`, `analysis_text`, `knjizbe_data`  
**Uvozi / Integra:** `import_kirkpr_path`, `import_vasco_paths`, `integra_info`, `integra_set_sql_dir`, `integra_restore`, `integra_kisanal`, `missing_parties`, `delete_import_for_period`, `default_accounts`  
**Poti:** `open_path`, `pick_file` / `pick_directory` (stub → kliči bridge)

## `TropsJsApi`

Isti API z odzivom `{ok: true, …}` / `{ok: false, error: str}`; seznam metod ustreza zgornjemu (JSON: `filters_json`, `ids_json`, `payload_json`, `paths_json`).
