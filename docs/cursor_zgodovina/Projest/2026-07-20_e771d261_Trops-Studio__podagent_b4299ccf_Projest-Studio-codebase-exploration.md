# Podagent: Projest Studio codebase exploration

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `b4299ccf-e0a8-4a78-ab3d-f92098a50ce3` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-07-22 10:46  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\b4299ccf-e0a8-4a78-ab3d-f92098a50ce3.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Wednesday, Jul 22, 2026, 10:46 AM (UTC+2)

Explore the Projest Studio codebase at D:\PISARNA\Python\Projest\projest_studio thoroughly (medium) and report:

1. Where Minimax API is called today (file + function names): parties sync, account catalog, create customer, XML export, anything else.
2. Where SQL/SQLite is the source of truth today (IR/PR upsert, parties, account_rules, journals if any).
3. Any existing "confirm then sync" or draft/status workflow (OSNUTEK, Popravi, Shranjeno, etc.).
4. Whether journal/knjiženje is persisted in SQL or only preview.
5. Gaps relative to this desired architecture: "all actions (usklajevanje, knjiženje, dodajanje) happen in SQL; after confirmation, sync to Minimax API".

Return a concise structured report with file paths and concrete recommendations for the smallest useful next step (not a full rewrite).

### 🤖 Asistent

I'll explore the Projest Studio codebase for Minimax API usage, SQL persistence, and confirmation workflows.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/*.{py,sql,md,json,yml,yaml,toml}
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio

- 🔧 `UpdateCurrentStep`
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\minimax_parties.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\row_status.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\journal_preview.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio

- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\minimax_parties.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\account_choices.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\xml_export.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\ui
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\kirkpr_bridge.py

- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\nove_firme_dialog.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `UpdateCurrentStep`

- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\parties_ensure.py
- 🔧 `UpdateCurrentStep`

# Projest Studio — architecture scan

## 1. Where Minimax API is called today

| Concern | File | Function(s) | What it does |
|--------|------|-------------|--------------|
| **Parties sync (pull)** | `D:\PISARNA\Python\Projest\projest_studio\minimax_parties.py` | `open_minimax_client`, `sync_customers_from_minimax` | Auth + `client._all("customers")` → `db.upsert_party` |
| **UI entry** | `...\ui\app.py` | `sync_minimax_parties` | Button/menu “Minimax stranke” / “Iz Minimax API” |
| **Create customer (push)** | `...\minimax_parties.py` | `create_customer_in_minimax`, helpers `find_customer_by_tax`, `find_customer_by_code`, `_lookup_fk_id`, `_build_customer_payload` | Lookup / `addbytaxnumber` / `POST customers` / optional `PUT` |
| **Batch import** | `...\minimax_parties.py` | `import_parties_to_minimax`, `ensure_koncni_kupci_in_sqlite` | Orchestrates AJPES + create/link + SQLite write |
| **UI confirm → API** | `...\ui\nove_firme_dialog.py` | `import_selected` | `askyesno` then immediate `import_parties_to_minimax` |
| **Account catalog** | `...\account_choices.py` | `account_choices_from_minimax`, `warm_account_cache_minimax`, `load_account_choices(..., fetch_minimax=True)` | `client.account_catalog()` — **in-memory cache only**; editors call with `fetch_minimax=False`; `warm_account_cache_minimax` is **unused** by UI |
| **XML export** | `...\xml_export.py` | `export_minimax_xml_for_kirkpr`, `_build_ir_journals`, `_build_pr_journals` | **No API** — builds IR/PR XML from SQLite for KirKpr/Minimax file import |
| **Bridge** | `...\kirkpr_bridge.py` | `ensure_kirkpr_on_path`, `minimax_xsd_path` | Puts `minimax_api_client` / XSD on path |

**Not present:** any Minimax API for invoices / received invoices / journal postings / usklajevanje knjiženja. Sync surface today is **customers (+ optional accounts read) + XML file**.

---

## 2. SQL/SQLite as source of truth

DB: `D:\PISARNA\Python\Projest\projest_studio\db.py` → default `data/projest.sqlite3`.

| Table | Role | Key writers |
|-------|------|-------------|
| `ir_rows` / `pr_rows` | Working IR/PR | `Database.upsert_ir` / `upsert_pr`; Vasco import `excel_map.py`; editors via `app.py` save callbacks |
| `parties` | Party master + `minimax_code` | `upsert_party`; Minimax sync/import; AJPES ensure (`parties_ensure.py`) |
| `account_rules` | Learned account mapping | `upsert_account_rule`, `learn_account_rules_from_rows`; UI “Zapomni”; `accounts.py` |
| `import_batches` | Import metadata | Vasco open flow |
| `meta` | Key/value | misc |

**There is no `journals` / knjižbe table.**

---

## 3. Existing draft / status / “confirm then sync”

**Row status (local only)** — `row_status.py`:

- `OSNUTEK` (default on import), `Popravi`, `Popravljeno`, `Shranjeno`, `Manjka konto`, `Poglej`, legacy `PRIPRAVLJEN`
- Stored on `ir_rows.status` / `pr_rows.status`; filters in `app.py`; editable in `ir_editor.py` / `pr_editor.py`
- **Does not trigger Minimax sync** when set to `Shranjeno`

**Closest “confirm then sync”:**

- `nove_firme_dialog.import_selected` — confirm dialog → **immediate** customers API (not SQL-first staging of pending creates)
- Destructive confirms elsewhere (`askyesno` delete/repair/import paths) — not a sync workflow

**Save flow:** editor “Shrani” → SQLite only (+ optional `account_rules`). No outbound API.

---

## 4. Journal / knjiženje persistence

**Preview only.**

- Compute: `journal_preview.py` → `preview_ir_journals` / `preview_pr_journals`
- UI: IR/PR editors “Predogled knjižb”; tooltips say next phase / no SQLite journal table
- Export: XML rebuilds journals from IR/PR amounts + accounts at export time (`xml_export.py`), not from stored lines

Accounts on the row (`account`, `odhodek01`, `placilo`, …) are in SQL; generated journal lines are not.

---

## 5. Gaps vs desired architecture

Desired: *all actions (usklajevanje, knjiženje, dodajanje) in SQL → after confirmation, sync to Minimax API.*

| Area | Today | Gap |
|------|-------|-----|
| IR/PR edit | SQL ✅ | OK foundation |
| Parties add | Often **API first**, then SQLite | Invert: stage in SQL, confirm → API, write back `minimax_code` |
| Parties pull | API → SQL | Fine as refresh; not “confirm sync” |
| Knjiženje | Preview / XML only | Need SQL journal lines + confirm → API (or keep XML as interim sync channel) |
| Status `Shranjeno` | Label/filter | No meaning as “ready to push” |
| Account catalog | Ephemeral API cache | Not SQL catalog; rarely fetched |
| Usklajevanje | Local rules + party codes | No sync-status / remote IDs for postings |

---

## Smallest useful next step (not a rewrite)

**Persist journal lines in SQLite and treat `Shranjeno` as “ready to export/sync”.**

1. Add `journal_lines` (or `ir_journals` / `pr_journals`) keyed by `ir_rows.id` / `pr_rows.id`.
2. On editor save (or “Osveži knjižbe” + save), write lines from existing `preview_*_journals` into SQL.
3. Gate XML export (and later API) on `status = Shranjeno` (or an explicit “Potrdi” that sets that status).

Why this first: reuses current preview math, matches UI copy (“naslednja faza”), unlocks confirm-then-push without inventing Minimax invoice APIs yet. **Second** small step: stage new parties in SQL (`source=pending`, empty `minimax_code`) and only call `create_customer_in_minimax` after the same confirm pattern as `nove_firme_dialog`.
