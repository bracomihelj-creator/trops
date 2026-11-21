# Podagent: Find month delete hooks

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `218e2dd1-4326-4462-9b59-5ae985fd411a` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-08-15 01:51  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\218e2dd1-4326-4462-9b59-5ae985fd411a.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Saturday, Aug 15, 2026, 1:51 AM (UTC+2)

In D:\PISARNA\Python\Trops\trops_studio explore how IR/PR dates are stored and if any month-delete already exists.

Return:
1. Column names for dates on ir_rows and pr_rows (from db.py schema)
2. Any existing delete-by-period or clear month functions
3. Line numbers of import_vasco and _finish_vasco_import in ui/app.py
4. Where period filter UI is (filter_from_date) and a good place for "Briši uvoz meseca" button (source panel near Uvozi Vasco or period bar)
5. How list_ir/list_pr filter by date if at all

Do not modify files.

### 🤖 Asistent

I'll explore the Trops Studio codebase for IR/PR date storage, any month-delete helpers, and the related UI/import entry points.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/db.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio

The workspace root differs from Trops Studio — searching that path directly via the shell.

- 🔧 `UpdateCurrentStep`
- 🔧 `Shell` — List trops_studio and find key files
- 🔧 `GetMcpTools`

- 🔧 `CallMcpTool` — Switch workspace root to trops_studio
- 🔧 `Shell` — Verify path and locate db.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Shell` — List trops_studio directory contents

- 🔧 `Shell` — Search date/delete/import patterns
- 🔧 `Shell` — Locate schema and UI symbols

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Shell` — Find delete helpers and UI period widgets
- 🔧 `Read` — C:\Users\braco\.cursor\projects\d-PISARNA-Python-Projest\agent-tools\65e7835a-6adb-4ca8-b127-9c54f24ac14a.txt

Checking UI date filtering and whether any period-scoped local deletes exist beyond row-id deletes.

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\excel_map.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\integra_irpr.py
- 🔧 `Shell` — Find period-delete and date column uses

- 🔧 `Shell` — Confirm period bar call sites and deletes
- 🔧 `UpdateCurrentStep`

## 1. Date columns (`db.py` schema)

**`ir_rows`** (lines 85–113):
- `booking_date`
- `document_date`
- Also timestamps: `created_at`, `updated_at`

**`pr_rows`** (lines 115–157):
- `booking_date`
- `received_date`
- `document_date`
- Also timestamps: `created_at`, `updated_at`

## 2. Delete-by-period / clear-month?

**No dedicated local “delete month / clear period” for `ir_rows`/`pr_rows`.**

Closest existing behavior:

| What | Where | Scope |
|------|--------|--------|
| `delete_ir` / `delete_pr` | `db.py` 659–675 | By row id only |
| UI `Izbriši` | IR/PR toolbars ~946 / ~1089 → `delete_selected` ~3657 | Selected rows |
| Vasco `replace_existing=True` | `excel_map.py` 162–169 | Deletes **all** IR + PR, not one month |
| Integra `replace_existing` | `integra_irpr.py` 875–881 | Deletes rows whose `notes` start with kisanal prefix |
| `delete_draft_journals_for_period` | `minimax_draft_cleanup.py` | **Minimax** draft journals for a date range (remote), not SQLite IR/PR |

Menu “Briši Minimax osnutke obdobja…” (~377 / ~2874) is Minimax-only.

## 3. Line numbers in `ui/app.py`

- `_finish_vasco_import` — **3393**
- `import_vasco` — **3419**
- (`import_vasco_fixed_paths` — ~3477, also calls `_finish_vasco_import`)

## 4. Period filter UI + button placement

**Period bar:** `_build_period_filter_bar` at **599–648**, called from layout ~**484**.

- State: `self.filter_from_date` / `filter_to_date` (~141)
- Vars: `filter_from_var` (~162), month/year combos (~160–161)
- Controls: Mesec ‹›, Datum od/do, **Uporabi**, **Vsa obdobja**

**Source panel (Projest):** `_build_source_section` ~**221**; **Uvozi Vasco** in `proj_btns` **293–300**.

**Good places for “Briši uvoz meseca”:**
1. **Preferred:** next to **Uvozi Vasco** in `proj_btns` (~295–300) — same “uvoz” surface.
2. **Also strong:** end of period bar after **Uporabi** / **Vsa obdobja** (~646–648) — period is already selected there.

## 5. How `list_ir` / `list_pr` filter by date

**They don’t.** In `db.py`:

- `list_ir` (501–504): `SELECT * … ORDER BY document_date, seq, id`
- `list_pr` (506–509): `SELECT * … ORDER BY received_date, seq, id`

No `WHERE` on dates. Sync variants filter only `sync_status`.

**Date filtering is UI-side** after caching:
- `_period_rows` / `_row_in_period` (~1478–1550): IR uses `document_date` then `booking_date`; PR uses `received_date` → `document_date` → `booking_date`
- Tree visibility `_ir_row_visible` / `_pr_row_visible` (~3361–3390): same key priority vs `filter_from_date`…`filter_to_date`
