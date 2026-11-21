# Podagent: IR and PR upsert logic

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `bec6ab21-a990-423c-99d0-524e65f34a2b` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-08-15 01:57  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\bec6ab21-a990-423c-99d0-524e65f34a2b.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Saturday, Aug 15, 2026, 1:58 AM (UTC+2)

In D:\PISARNA\Python\Trops\trops_studio examine how IR/PR rows are upserted and what uniqueness exists.

Return:
1. upsert_ir / upsert_pr logic - does it match existing by document_no? Exact code snippets with line numbers from db.py
2. map_ir / map_pr - what fields identify a row (document_no, dates, book)
3. import_vasco_files_to_db replace vs append behavior
4. Any existing find_ir_by_document or similar

Goal: when append import, skip rows that already exist for the same month/document (e.g. June 2026 already in DB). Recommend the best unique key for IR and PR.

Do not modify files.

### 🤖 Asistent

I'll examine how IR/PR upserts and uniqueness work in `trops_studio`, starting with `db.py` and related import paths.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/db.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio
- 🔧 `Glob` — **/*.{py,sql}

The workspace root looks wrong for that path — I'll point tools at the Trops directory directly.

- 🔧 `GetMcpTools`
- 🔧 `Shell` — List trops_studio and find db.py

- 🔧 `CallMcpTool` — Switch workspace to trops_studio
- 🔧 `Shell` — Verify trops_studio path exists

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Shell` — List trops_studio directory contents

- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio\db.py

- 🔧 `Shell` — Search IR/PR upsert and uniqueness
- 🔧 `UpdateCurrentStep`

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\excel_map.py
- 🔧 `Shell` — Find IR/PR lookup helpers

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\vasco_discover.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Shell` — Find replace flag and document lookups

Integra import already has skip-on-existing logic — checking that for comparison.

- 🔧 `Shell` — rg -n "_find_existing_id|existing_ir|existing_pr|def import_" "D:\PISARNA\Python\Trops\trops_studio\integra_irpr.py"
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\integra_irpr.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\integra_irpr.py
- 🔧 `UpdateCurrentStep`

## Verdict

`upsert_ir` / `upsert_pr` do **not** match by `document_no`. With no `row_id` they always **INSERT**. Append Vasco import will create duplicates. No `find_ir_by_document` exists.

---

### 1. `upsert_ir` / `upsert_pr` — match by `document_no`?

**No.** Only `id`-based update; otherwise plain insert. No `ON CONFLICT`, no document lookup.

```717:758:D:\PISARNA\Python\Trops\trops_studio\db.py
    def upsert_ir(self, data: Mapping[str, Any], row_id: int | None = None) -> int:
        payload = {
            "batch_id": data.get("batch_id"),
            "book": normalize_text(data.get("book")),
            "seq": int(data.get("seq") or 0),
            "booking_date": iso_date(data.get("booking_date")),
            "document_date": iso_date(data.get("document_date")),
            "document_no": normalize_text(data.get("document_no")),
            # ... amounts, party, status, sync_status, notes, raw_json ...
            "updated_at": _now(),
        }
        with self.session() as conn:
            if row_id:
                # UPDATE ... WHERE id=?
                ...
                return int(row_id)
            payload["created_at"] = _now()
            # INSERT INTO ir_rows ...
            return int(cur.lastrowid)
```

```760:814:D:\PISARNA\Python\Trops\trops_studio\db.py
    def upsert_pr(self, data: Mapping[str, Any], row_id: int | None = None) -> int:
        payload = {
            # ... includes document_no, internal_no, dates, amounts ...
        }
        with self.session() as conn:
            if row_id:
                # UPDATE ... WHERE id=?
                return int(row_id)
            # INSERT INTO pr_rows ...
            return int(cur.lastrowid)
```

Schema: **no UNIQUE** on `ir_rows` / `pr_rows` (only indexes):

```160:162:D:\PISARNA\Python\Trops\trops_studio\db.py
CREATE INDEX IF NOT EXISTS idx_ir_document ON ir_rows(book, document_no, document_date);
CREATE INDEX IF NOT EXISTS idx_pr_internal ON pr_rows(internal_no);
CREATE INDEX IF NOT EXISTS idx_pr_document ON pr_rows(document_no, document_date, vat_id);
```

---

### 2. `map_ir` / `map_pr` — identifying fields

| Kind | Identity-ish fields mapped | Notes |
|------|---------------------------|--------|
| **IR** | `book`, `document_no`, `document_date`, `booking_date`, `seq` | `book` from `ir_group_from_document` (doc starts with `3`→Darila, `2`→Fitness) else filename fallback |
| **PR** | `document_no`, `document_date`, `booking_date`, `received_date`, `internal_no`, `vat_id`, `seq` | No `book` |

```27:74:D:\PISARNA\Python\Trops\trops_studio\excel_map.py
def map_ir(...):
    document_no = normalize_text(raw.get("Številka listine"))
    group = ir_group_from_document(document_no, fallback=book_name)
    return {
        "book": group,
        "seq": ...,
        "booking_date": ...,
        "document_date": ...,
        "document_no": document_no,
        ...
    }
```

```77:89:D:\PISARNA\Python\Trops\trops_studio\excel_map.py
def map_pr(...):
    payload = {
        "seq": ...,
        "booking_date": ...,
        "received_date": ...,
        "document_date": ...,
        "document_no": normalize_text(raw.get("Številka listine")),
        "internal_no": normalize_text(raw.get("Opombe") or raw.get("Interna št#")),
        ...
    }
```

---

### 3. `import_vasco_files_to_db` — replace vs append

```162:193:D:\PISARNA\Python\Trops\trops_studio\excel_map.py
    if replace_existing:
        # delete ALL ir_rows + pr_rows
        ...
    # then always:
    db.upsert_ir(data)   # no row_id → INSERT
    db.upsert_pr(data)   # no row_id → INSERT
```

| Mode | Behavior |
|------|----------|
| `replace_existing=True` | Wipe **entire** IR + PR tables, then insert |
| `replace_existing=False` (append) | Insert every file row; **no skip**, duplicates allowed |

UI: DA = replace, NE = append (`ui/app.py` ~3610–3621).

---

### 4. `find_ir_by_document` / similar

**None** for Vasco/SQLite document identity.

Existing lookups in `db.py`:
- `get_ir(row_id)` / `get_pr(row_id)` — by PK only
- `list_ir` / `list_pr` — full table

Closest parallel: Integra `integra_irpr._find_existing_id` matches **kisanal `anal_ctrl`** via `notes` / `raw_json`, with a few `document_no` heuristics — not used by Vasco import.

---

### Recommendation — unique key for append-skip

Align with existing indexes (already how the schema thinks about identity):

| | Best key | Why |
|---|----------|-----|
| **IR** | `(book, document_no, document_date)` | Same number can exist in Darila vs Fitness; date disambiguates reissues / years |
| **PR** | `(document_no, document_date, vat_id)` | Supplier invoices reuse numbers; `vat_id` separates suppliers; matches `idx_pr_document` |

If you only care about “June 2026 already imported” (month bucket, not exact day):

- **IR:** `(book, document_no, strftime('%Y-%m', document_date))`
- **PR:** `(document_no, strftime('%Y-%m', document_date), vat_id)`

Prefer **exact `document_date`** unless Vasco re-exports the same invoice with a shifted day. Do **not** use `document_no` alone (books + suppliers collide). `seq` / `ZŠ` is file-local, not a stable key.

For append: before `upsert_*`, look up that key; if found → skip (or optionally update only if you want refresh). Optional later: `UNIQUE` matching those triples so the DB enforces it.
