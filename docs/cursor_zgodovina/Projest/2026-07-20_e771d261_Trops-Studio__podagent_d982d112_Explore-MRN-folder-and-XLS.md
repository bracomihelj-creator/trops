# Podagent: Explore MRN folder and XLS

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `d982d112-549d-4aea-a060-6190d885cb87` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-08-15 09:41  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\d982d112-549d-4aea-a060-6190d885cb87.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Saturday, Aug 15, 2026, 9:41 AM (UTC+2)

Explore these paths and return a detailed report:

1. List ALL files in D:\Trops\21\DDV\MRN (and D:\Trops\21\DDV if MRN doesn't exist). Include names, sizes, dates.

2. Find DDV_Deklaracija_14446669.xls anywhere under D:\Trops and D:\PISARNA. Describe path.

3. Search D:\PISARNA\Python\Trops and D:\PISARNA\Python\KirKpr_convert_cursor and D:\PISARNA\Python\Chrome_add for:
   - DDV_Deklaracija
   - Seznam carinskih
   - field 26 / polje 26 / info_ddvo_26 / info_mrn
   How is DDV-O field 26 calculated vs MRN CSV?

4. If you can, use Python (xlrd/openpyxl/olefile) to inspect DDV_Deklaracija_14446669.xls: sheet names, first 20 rows, any macros/formulas that load CSV, named ranges.

5. Look at trops_studio/ddvo_calc.py for field 26 / MRN amount.

Return file listing, XLS structure, and how field 26 is computed. Do not modify files.

### 🤖 Asistent

Exploring the requested paths and searching the codebase for DDV field 26 and MRN logic.

[REDACTED]

- 🔧 `UpdateCurrentStep`
- 🔧 `Shell` — List files in DDV/MRN or DDV folder
- 🔧 `Glob` — **/DDV_Deklaracija_14446669.xls
- 🔧 `Glob` — **/DDV_Deklaracija_14446669.xls
- 🔧 `Grep` — D:\PISARNA\Python\Trops
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\Chrome_add
- 🔧 `Glob` — **/ddvo_calc.py

Retrying with direct shell access to the absolute paths.

[REDACTED]

- 🔧 `Shell` — Check paths and list all files with metadata
- 🔧 `Shell` — Find DDV_Deklaracija_14446669.xls under Trops and PISARNA
- 🔧 `Shell` — Search Python dirs for DDV field 26 patterns
- 🔧 `Shell` — Find ddvo_calc.py under PISARNA Python

[REDACTED]

- 🔧 `Shell` — List MRN directory via cmd dir
- 🔧 `Shell` — Search Trops for target XLS file
- 🔧 `Shell` — Check if ddvo_calc.py exists

[REDACTED]

- 🔧 `Glob` — **/DDV_Deklaracija_14446669.xls
- 🔧 `Glob` — **/ddvo_calc.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ddvo_calc.py
- 🔧 `Glob` — **/*

[REDACTED]

- 🔧 `UpdateCurrentStep`
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\vat_accounts.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\Chrome_add
- 🔧 `Shell` — Python list dirs and find XLS file

[REDACTED]

- 🔧 `Write` — D:\PISARNA\Python\Projest\_explore_ddv_report.py
- 🔧 `Shell` — Run exploration script, write output file

[REDACTED]

- 🔧 `Read` — D:\PISARNA\Python\Projest\_explore_ddv_report_output.txt
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\Trops

[REDACTED]

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\edavki_mrn.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\Trops\21\DDV\MRN\202512 - DDV-Deklaracija - Seznam carinskih deklaracij.csv
- 🔧 `Read` — D:\Trops\21\DDV\MRN\202606 - DDV-Deklaracija - Seznam carinskih deklaracij.csv

[REDACTED]

- 🔧 `Read` — D:\Trops\21\DDV\MRN\202504 - DDV-Deklaracija - Seznam carinskih deklaracij.csv
- 🔧 `Read` — D:\Trops\21\DDV\MRN\202506 - DDV-Deklaracija - Seznam carinskih deklaracij.csv
- 🔧 `Grep` — D:\PISARNA\Python\Chrome_add
- 🔧 `Shell` — Deep inspect XLS streams, formulas, totals

[REDACTED]

- 🔧 `Shell` — Sum XLS DDV column and check formulas
- 🔧 `Read` — D:\PISARNA\Python\Chrome_add\Minimax_Odpiranje_Podjetij\background.js
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\edavki_links.py
- 🔧 `Delete` — D:\PISARNA\Python\Projest\_explore_ddv_report.py
- 🔧 `Delete` — D:\PISARNA\Python\Projest\_explore_ddv_report_output.txt

[REDACTED]

- 🔧 `UpdateCurrentStep`

[REDACTED]

- 🔧 `Shell` — Analyze XLS header total vs row sums

# DDV / MRN exploration report

## 1. File listing — `D:\Trops\21\DDV\MRN`

Path `D:\Trops\21\DDV\MRN` exists. All files:

| File | Size | Last modified |
|------|------|---------------|
| `D:\Trops\21\DDV\MRN\202504 - DDV-Deklaracija - Seznam carinskih deklaracij.csv` | 420 B | 2025-05-19 15:32:36 |
| `D:\Trops\21\DDV\MRN\202506 - DDV-Deklaracija - Seznam carinskih deklaracij.csv` | 444 B | 2025-07-16 17:16:10 |
| `D:\Trops\21\DDV\MRN\202512 - DDV-Deklaracija - Seznam carinskih deklaracij.csv` | 530 B | 2026-01-19 14:27:25 |
| `D:\Trops\21\DDV\MRN\202606 - DDV-Deklaracija - Seznam carinskih deklaracij.csv` | 439 B | 2026-07-24 20:57:50 |
| `D:\Trops\21\DDV\MRN\DDV_Deklaracija_14446669.xls` | 50,176 B | 2026-08-15 09:38:57 |

**CSV contents (eDavki export format):** semicolon-delimited, columns  
`Številka MRN; Tip deklaracije; Verzija MRN; Kontrolni rezultat; Datum priprave; Datum sprejema; Datum sprostitve; Znesek DDV po deklaraciji; Opombe`

Examples:
- **202606** (Jun 2026): 2 unique MRNs — `26SI00112340108193` (761,55) and `26SI00191340248558` (1.602,64, listed twice as O-Original + P-Popravek)
- **202512** (Dec 2025): includes `25SI00706740197155` (3.435,39)
- **202504/202506**: earlier 2025 declarations (2.503,94 + 1.800,89 etc.)

---

## 2. Location of `DDV_Deklaracija_14446669.xls`

**Single copy found** under both search roots:

`D:\Trops\21\DDV\MRN\DDV_Deklaracija_14446669.xls`  
(50,176 B, modified 2026-08-15 09:38:57)

Not found elsewhere under `D:\Trops` or `D:\PISARNA`.

Filename `14446669` matches Projest tax ID (`PROJEST_TAX_ID = "14446669"` in `edavki_links.py`).

---

## 3. Code search results

### `D:\PISARNA\Python\Trops` (32 hits)

Main logic lives in:

| File | Role |
|------|------|
| `trops_studio\ddvo_calc.py` | DDV-O computation, `info_ddvo_26`, `info_mrn_amount` |
| `trops_studio\edavki_mrn.py` | Online MRN fetch, CSV save, PR tagging |
| `trops_studio\vat_accounts.py` | `is_mrn_row()`, MRN vs UVOZ distinction |
| `trops_studio\edavki_links.py` | eDavki URL for “Seznam carinskih deklaracij” |
| `trops_studio\ui\ddvo_tab.py` | UI for MRN INFO panel and field 26 |
| `trops_studio\ui\knjige.py`, `pr_editor.py` | Display / editor hints |

### `D:\PISARNA\Python\KirKpr_convert_cursor` (0 direct hits)

No matches for those exact strings, but field 26 is defined in `kirkpr_minimax_core.py`:

```54:54:D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
    ("II. Obračunani DDV", "26", "samoobdavčitev od uvoza", "KIR", ("P26",)),
```

`ddvo_summary()` sums KIR `P26` into DDV-O field 26.

### `D:\PISARNA\Python\Chrome_add` (13 hits)

Chrome extensions scrape eDavki MRN grid and POST to localhost:
- `Minimax_Odpiranje_Podjetij\background.js` — `extractEdavkiMrnGrid()`, dedup logic
- `AktivniZavihek_WebApp\background.js` — same pattern
- `content_automation.js` — triggers fetch via `kirkpr_edavki_mrn` URL param

---

## 4. XLS structure — `DDV_Deklaracija_14446669.xls`

Inspected with **olefile** + **xlrd** (openpyxl cannot read `.xls`).

| Property | Value |
|----------|-------|
| Format | OLE compound document (classic `.xls`) |
| VBA macros | **No** (`_VBA_PROJECT_CUR` absent) |
| OLE streams | `DocumentSummaryInformation`, `SummaryInformation`, `Workbook` |
| Named ranges | `_filterdatabase` only (Excel auto-filter) |
| Formulas loading CSV | **None found** — appears to be pasted/exported data, not macro-driven |

### Sheets

**`DDV_Deklaracija_57550441`** — 144 rows × 15 cols  
Main MRN table (same columns as eDavki CSV). First 20 rows:

- **R1:** header totals in cols H–I: **3.205,28** (DDV) and **14.569,45** (osnova)
- **R2:** column headers (`Številka MRN`, `Znesek DDV po deklaraciji`, `OSNOVA ZA DDV`, …)
- **R3–R20:** MRN rows starting `20SI00191340508053` … `24SI00191340413862`

Data summary:
- 25 data rows with DDV amounts
- 24 unique MRN codes (one duplicate: `26SI00191340248558` appears twice — O-Original + P-Popravek)
- Sum of all DDV rows: **54.182,57 EUR**
- **R1 total 3.205,28 = exactly the sum of the last 2 rows** (both 1.602,64 duplicates) — so the header **double-counts** the popravek duplicate instead of deduplicating

**`List1`** — empty (0×0)

**`ODDANO`** — 15×8 reconciliation sheet  
Compares submitted DDV (“oddano DDV”) vs MRN totals by month:

| Month | oddano DDV | MRN | Diff |
|-------|-----------|-----|------|
| 5 | 3.870,00 | 3.870,31 | −0,31 |
| 6 | 5.596,00 | 5.596,27 | −0,27 |
| 7 | 4.490,00 | 4.490,37 | −0,37 |
| 8 | 9.106,00 | 9.106,40 | −0,40 |
| 9 | — | 1.634,64 | −1.634,64 |
| Year total (R1) | 23.062,00 | 24.697,99 | −1.635,99 |

This sheet is a manual/control reconciliation, not an automated import.

---

## 5. How DDV-O field 26 is computed vs MRN CSV

### Two different sources

| Metric | Source | Calculation |
|--------|--------|-------------|
| **`info_ddvo_26`** | Accounting (KIR/KPR) | Sum of DDV-O field **26** from `ddvo_summary()` = sum of KIR **P26** |
| **`info_mrn_amount`** | PR book INFO | Sum of `vat_22 + vat_95 + vat_5` on PR rows flagged as MRN |
| **MRN CSV / eDavki** | Customs declarations | Sum of column **“Znesek DDV po deklaraciji”**, with MRN deduplication |

### Field 26 from books (`ddvo_calc.py` + KirKpr core)

**Step 1 — Synthetic KIR row for MRN PR invoices:**

```175:180:D:\PISARNA\Python\Trops\trops_studio\ddvo_calc.py
    if is_mrn_row(row):
        kir["P26"] = vat_22 + vat_95 + vat_5
        kir["__source__"] = "projest-mrn-26"
        return kir
```

Only PR rows explicitly identified as MRN (via `supplier_kind == "MRN"` or MRN code in notes/document) get P26.

**Step 2 — `ddvo_summary()` aggregates:**

```1580:1602:D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
    for section, code, label, book, source_fields in DDVO_FIELD_DEFINITIONS:
        ...
        exact = sum(... decimal_value(row.get(source_field)) ... for source_field in source_fields ...)
        rounded = exact.quantize(EURO, rounding=ROUND_HALF_UP)
```

Field **26** = Σ KIR **P26** (exact + rounded to whole EUR).

**Step 3 — exposed in summary:**

```478:478:D:\PISARNA\Python\Trops\trops_studio\ddvo_calc.py
    summary["info_ddvo_26"] = _field_exact_sum(fields, {"26"})
```

### MRN amount from PR INFO (`pr_access_info`)

```396:420:D:\PISARNA\Python\Trops\trops_studio\ddvo_calc.py
        if is_mrn_row(row) or row_supplier_kind(row) == "MRN":
            mrn_vat += row_vat
        ...
        "info_mrn_amount": mrn_vat,
```

Also collects MRN codes from notes/raw_json via `extract_mrn_codes()`.

### MRN CSV / eDavki online (`edavki_mrn.py` + Chrome)

**Chrome extension** reads eDavki grid `#gridDeclaration`, parses column 8 as DDV, then:

1. **Deduplicates by MRN** — if both O-Original and P-Popravek exist, keeps **P-Popravek**
2. **`totalVat`** = sum of unique rows’ VAT

**`edavki_mrn.py`** sets both:

```340:341:D:\PISARNA\Python\Trops\trops_studio\edavki_mrn.py
        "info_mrn_amount": lookup.total_vat,
        "info_ddvo_26": lookup.total_vat,
```

When fetched online, `info_ddvo_26` is temporarily set to the eDavki total (for comparison), not from KIR.

**Saved CSV format** (`save_mrn_csv`): `MRN; Tip; Verzija; Datum sprejema; Datum sprostitve; DDV; Opombe` — simpler than the eDavki export filenames in the MRN folder.

### Key differences / reconciliation points

| Aspect | DDV-O field 26 (books) | MRN CSV (eDavki) |
|--------|------------------------|------------------|
| **Data source** | PR invoices tagged MRN in Projest/Minimax | FURS customs declarations |
| **Amount** | VAT on matched PR rows (22% + 9,5% + 5%) | “Znesek DDV po deklaraciji” per MRN |
| **Dedup** | One PR row per invoice; MRN matched by code in notes | One row per MRN; P-Popravek over O-Original |
| **Matching** | Requires PR row with MRN code in document/notes (`apply_mrn_to_pr_rows`) | No PR needed — direct from eDavki |
| **UVOZ vs MRN** | Regular import (`UVOZ`) → field 21/22, **not** 26 | All customs declarations in this list feed field 26 |
| **Rounding** | Field 26 rounded to whole EUR in DDV-O | CSV uses decimal amounts (e.g. 761,55) |

The `ODDANO` sheet in the XLS shows the intended control loop: monthly “oddano DDV” (what was filed) vs “MRN” (what eDavki says). Small cent differences (0,27–0,40) suggest rounding; month 9 shows a larger gap (−1.634,64) where MRN exists but no DDV was filed.

### MRN identification rules (`vat_accounts.py`)

- **MRN** = explicit `supplier_kind == "MRN"` OR MRN code pattern in notes (`26SI00112340108193`)
- **NOT inferred from VAT amount alone** (comment: “Foshan ≠ MRN”)
- **UVOZ** = deductible import VAT, no self-assessment, **not field 26**

---

## Summary

1. **MRN folder** has 4 period CSV exports + 1 Excel workbook for Projest (tax ID 14446669).
2. **XLS** is a manual reconciliation workbook: main MRN list (25 rows, 24 unique), no macros, `ODDANO` sheet compares filed DDV vs MRN by month. Header total 3.205,28 double-counts duplicate popravek row.
3. **Field 26** in Trops = Σ KIR P26 from MRN-tagged PR invoices (synthetic self-assessment VAT). **MRN CSV** = Σ eDavki customs DDV with popravek dedup. They should align when PR rows are correctly tagged with matching MRN codes and amounts; the Chrome extension + `edavki_mrn.py` bridge eDavki → PR tagging for that purpose.

[REDACTED]
