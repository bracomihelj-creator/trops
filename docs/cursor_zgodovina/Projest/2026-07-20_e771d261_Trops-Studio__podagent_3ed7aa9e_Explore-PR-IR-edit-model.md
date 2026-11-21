# Podagent: Explore PR/IR edit model

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `3ed7aa9e-c03e-4c84-aef9-da42c56a2c12` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-07-22 09:03  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\3ed7aa9e-c03e-4c84-aef9-da42c56a2c12.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Wednesday, Jul 22, 2026, 9:03 AM (UTC+2)

Explore D:\PISARNA\Python\Projest\projest_studio for PR/IR row editing, status fields, accounts, and DB schema.

Return:
1. pr_rows / ir_rows columns from db.py (schema)
2. How status is used in UI filters (app.py) - current status values
3. Current RowEditorDialog usage and open/edit flows
4. Account fields on PR (odhodek01, odhodek07, placilo) and IR (account) - how resolve_pr_accounts / account templates work
5. Whether any journal/knjižba table already exists
6. parties list for combo (db.list_parties)

Be concise with file paths and key snippets. Thoroughness: medium.

### 🤖 Asistent

I'll explore `projest_studio` for PR/IR schema, status filters, RowEditorDialog, accounts, and parties.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/*.{py,sql,md}
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio

- 🔧 `UpdateCurrentStep`
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\row_editor.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\accounts.py

- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py

- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\excel_map.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\config.py
- 🔧 `UpdateCurrentStep`

## 1. Schema (`D:\PISARNA\Python\Projest\projest_studio\db.py`)

**`ir_rows`:** `id`, `batch_id`, `book`, `seq`, `booking_date`, `document_date`, `document_no`, `party_name`, `vat_id`, money fields (`net`, `base_22`/`vat_22`, `base_95`/`vat_95`, `eu_goods`, `eu_services`, `reverse_charge`, `excluded`, `exempt`, `total`), **`account`**, `party_id`, **`status` DEFAULT `'OSNUTEK'`**, `notes`, `raw_json`, `created_at`, `updated_at`

**`pr_rows`:** `id`, `batch_id`, `seq`, `booking_date`, `received_date`, `document_date`, `document_no`, `internal_no`, `supplier_name`, `vat_id`, `tax_number`, money fields (`net_taxable`, `f76a`, EU/exempt/nondeduct/base/vat…, `excluded`), **`odhodek01`**, **`odhodek07`**, **`placilo`**, `party_id`, **`status` DEFAULT `'OSNUTEK'`**, `notes`, `raw_json`, `created_at`, `updated_at`

Other tables: `meta`, `parties`, `account_rules`, `import_batches` — no journal table.

---

## 2. Status filters (`ui\app.py`)

| Kind | Radio values |
|------|----------------|
| IR | `VSI`, `OSNUTEK`, `PRIPRAVLJEN`, `CHK` |
| PR | same + `NO_ACCOUNT` |

- DB stored values used: **`OSNUTEK`**, **`PRIPRAVLJEN`** (default on insert/import: `OSNUTEK`)
- `CHK` = UI checkbox state, not DB status
- `NO_ACCOUNT` (PR only) = empty `odhodek01`
- Tree filter compares `row.status.upper()` to the selected value

---

## 3. `RowEditorDialog` (`ui\row_editor.py` + `app.py`)

- Generic scrollable form: plain `ttk.Entry` per field; kinds `text` / `money` / `date` / `int`
- **IR_FIELDS** / **PR_FIELDS** include status + accounts as free text
- Open flows in `app.py`:
  - **Dodaj** → `add_row("IR"|"PR")` → defaults + `RowEditorDialog` → `upsert_ir` / `upsert_pr`
  - **Odpri / popravi**, **Double-1**, **Return** → `edit_selected` → load `get_ir`/`get_pr`, merge payload, upsert
  - Optional “Zapomni si …” → `upsert_account_rule` on save

No party Combobox in the dialog.

---

## 4. Accounts

**PR:** `odhodek01`, `odhodek07`, `placilo`  
**IR:** `account` (maps to `account_rules.prihodek`)

**`resolve_pr_accounts`** (`accounts.py`):  
`find_account_rule(supplier)` → else `last_pr_account` (and promote to rule) → else `{odhodek01: 4190, odhodek07: "", placilo: "2200"}`

**`resolve_ir_account`:** rule `prihodek` → `last_ir_account` → `7620`

**Templates:** `import_account_templates_from_accdb` reads Access history/rules into `account_rules`; then `learn_account_rules_from_rows()`. Used on Excel import via `excel_map.map_pr` / IR mapping.

---

## 5. Journal / knjižba table

**None in SQLite.** “Knjige” UI is a view over `ir_rows`/`pr_rows`. XML journals are built at export time in `xml_export.py` (`_build_ir_journals` / `_build_pr_journals`) — not persisted as a table.

---

## 6. Parties (`db.list_parties`)

```python
SELECT * FROM parties ORDER BY name COLLATE NOCASE, id
```

Loaded in `refresh_all` → `self._party_cache`; used for the **Stranke** tree, not as RowEditor combos.
