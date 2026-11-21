# Podagent: Implement Vasco import UI fixes

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `d21c6be7-8c85-4e7b-a748-900bf6a7d365` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-08-15 01:53  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\d21c6be7-8c85-4e7b-a748-900bf6a7d365.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Saturday, Aug 15, 2026, 1:53 AM (UTC+2)

Edit Trops Studio at D:\PISARNA\Python\Trops. Version is already 2.0.28 in trops_studio/__init__.py. vasco_discover.py already has ZIP helpers (resolve_vasco_sources, cleanup_temp_dir, pick_three_vasco_files). excel_map.py already has bulk delete on replace.

## Goals
1) Fix "Uvozi Vasco" so it reads 3 files (Darila/Fitness/PR) from a folder OR ZIP, runs import on a background thread with ProgressDialog (UI must not freeze). Defer/skip blocking AJPES in finish (optional yes/no after import, or skip auto AJPES).
2) Add "Odpri Excel IR" next to IR "Vse odznači" and "Odpri Excel PR" next to PR "Vse odznači".
3) Add "Briši uvoz obdobja" — delete IR/PR rows in the currently selected period (filter_from_date..filter_to_date). Put button on period bar after "Vsa obdobja" AND in menu Datoteka. Confirm with counts before delete.

## Required code changes

### A) trops_studio/db.py
After delete_pr (~675), add:

```python
def delete_ir_pr_for_period(
    self,
    date_from: date,
    date_to: date,
) -> dict[str, int]:
    """Izbriši IR/PR v obdobju (enaka logika datumov kot UI filter)."""
```

Use same date key priority as UI:
- IR: document_date then booking_date
- PR: received_date, document_date, booking_date
Parse with existing iso_date/parse helpers in money.py if available. Collect ids then call delete_ir/delete_pr. Return {"ir": n, "pr": n}.

Import date from datetime if needed.

### B) trops_studio/ui/app.py

1. Change import:
```python
from trops_studio.vasco_discover import (
    classify_selected_files,
    cleanup_temp_dir,
    discover_vasco_files,
    resolve_vasco_sources,
)
```

2. In __init__ add `self._import_running = False` near `_sync_running`.

3. Period bar (~647): after "Vsa obdobja" button add:
```python
btn_del_month = ttk.Button(bar, text="Briši uvoz obdobja", command=self.delete_import_for_period)
btn_del_month.pack(side="left", padx=(0, 10))
ToolTip(btn_del_month, "Izbriši IR in PR v trenutno izbranem obdobju (SQLite).")
```

4. Menu Datoteka: after Uvozi Vasco lines add command "Briši uvoz obdobja…" → delete_import_for_period

5. IR toolbar after "Vse odznači":
```python
btn_ir_xls = ttk.Button(books, text="Odpri Excel IR", command=self.open_excel_ir)
btn_ir_xls.pack(side="left", padx=(8, 4))
ToolTip(btn_ir_xls, "Odpri Excel Darila + Fitness (poti iz glave).")
```

6. PR filters after "Vse odznači":
```python
btn_pr_xls = ttk.Button(filters, text="Odpri Excel PR", command=self.open_excel_pr)
btn_pr_xls.pack(side="right", padx=(0, 8))
```
(Note PR buttons pack side=right — pack Odpri Excel PR before the oznaci buttons or after with side=right so it appears left of them visually... User wanted it near Vse odznači. Pack with side=right after odznači so it appears further left.)

Actually pack order for side=right is reverse: first packed appears rightmost. Current: oznaci then odznači. So pack Odpri Excel PR first (rightmost) OR pack after both. Put after odznači with side=right.

7. Replace import_vasco + _finish_vasco_import + add helpers. Logic for import_vasco:

```
choice = askyesnocancel(
  "DA = mapa (3 datoteke Darila/Fitness/PR)\n"
  "NE = ZIP z istimi datotekami\n"
  "Prekliči = uporabi poti iz glave"
)
if Yes: askdirectory → resolve_vasco_sources(folder=...)
if No: askopenfilename zip → resolve_vasco_sources(zip_path=...)
if Cancel: use ir_darila_var, ir_fitnes_var, pr_var paths if files exist

Then confirm replace DA/NE/Cancel
Then ProgressDialog + threading.Thread worker with separate Database(db_path)
import_vasco_files_to_db with the three paths (skip missing? require at least one)
Update path vars on success
cleanup_temp_dir in finally
_finish without blocking AJPES — just refresh + messagebox. Optionally ask "Dopolni stranke AJPES?" and run that in thread if yes.
```

8. Add methods:
- open_excel_ir: startfile darila and fitness if files exist
- open_excel_pr: startfile pr_var
- delete_import_for_period: count via _period_rows(), askyesno with counts and dates, call db.delete_ir_pr_for_period, refresh_all

9. Update tooltip on Uvozi Vasco button.

10. Keep import_vasco_fixed_paths but also run it threaded like the new import (optional — at least call shared _run_vasco_import_async).

Implement a shared `_run_vasco_import_async(self, ir_files, pr_files, replace, temp_dir=None)` used by both import_vasco and import_vasco_fixed_paths.

### C) Bump version to 2.0.29 in __init__.py

Do NOT commit. Make the edits directly with the Write/StrReplace tools using absolute paths under D:\PISARNA\Python\Trops.

After edits, verify with a quick python import check:
```
cd D:\PISARNA\Python\Trops
$env:PYTHONPATH='D:\PISARNA\Python\Trops'
python -c "from trops_studio.vasco_discover import resolve_vasco_sources; from trops_studio.db import Database; from trops_studio import __version__; print(__version__)"
```

Return summary of what changed.

### 🤖 Asistent

I'll implement the Vasco import threading, Excel open buttons, period delete, and version bump in Trops Studio.

- 🔧 `UpdateCurrentStep`
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\__init__.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio

Grep is scoped to the wrong workspace — I'll read the Trops files directly.

- 🔧 `Shell` — Search Trops source for edit targets

- 🔧 `Shell` — Find delete_pr location in db.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\vasco_discover.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\vasco_discover.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `CallMcpTool`

- 🔧 `GetMcpTools`
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Shell` — Locate key line numbers in app.py

- 🔧 `CallMcpTool`
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\money.py
- 🔧 `UpdateCurrentStep`

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\money.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\progress_dialog.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\money.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio\ui\progress_dialog.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio\excel_map.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\progress_dialog.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\excel_map.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\excel_map.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `UpdateCurrentStep`

Implementing the db helper and UI changes next.

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\__init__.py

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Shell` — Verify Python imports and version 2.0.29

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Shell` — Python import verification with PowerShell

- 🔧 `Write` — D:\PISARNA\Python\Trops\_verify_import_check.py
- 🔧 `Shell` — Run verification script for Trops

- 🔧 `Shell` — Test shell output

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Delete` — D:\PISARNA\Python\Trops\_verify_import_check.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\__init__.py

- 🔧 `Shell` — Write test file via python
- 🔧 `AwaitShell`

- 🔧 `Read` — D:\PISARNA\Python\Trops\_v.txt

- 🔧 `StrReplace` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `UpdateCurrentStep`

Trops Studio is at **2.0.29**. Changes under `D:\PISARNA\Python\Trops`:

### `trops_studio/db.py`
- Added `delete_ir_pr_for_period(date_from, date_to)` — same date keys as the UI filter (IR: document→booking; PR: received→document→booking), then `delete_ir` / `delete_pr`. Returns `{"ir": n, "pr": n}`.

### `trops_studio/ui/app.py`
1. **Uvozi Vasco** — Yes=folder / No=ZIP / Cancel=header paths via `resolve_vasco_sources`; replace confirm; shared `_run_vasco_import_async` with `ProgressDialog` + background `Database`; ZIP `cleanup_temp_dir` in `finally`.
2. **Finish** — refresh + result dialog only; optional “Dopolni stranke AJPES?” → threaded `_run_ajpes_after_import_async`.
3. **`import_vasco_fixed_paths`** — also uses `_run_vasco_import_async`.
4. **Odpri Excel IR / PR** next to “Vse odznači”.
5. **Briši uvoz obdobja** on period bar (after “Vsa obdobja”) and under Datoteka; confirms with IR/PR counts for the selected period.
6. `_import_running` flag; updated Vasco tooltip.

### `trops_studio/__init__.py`
- Version **2.0.29**.

Shell could not execute in this session. Local check:

```powershell
cd D:\PISARNA\Python\Trops
$env:PYTHONPATH='D:\PISARNA\Python\Trops'
python -c "from trops_studio.vasco_discover import resolve_vasco_sources; from trops_studio.db import Database; from trops_studio import __version__; print(__version__)"
```

No commit made.
