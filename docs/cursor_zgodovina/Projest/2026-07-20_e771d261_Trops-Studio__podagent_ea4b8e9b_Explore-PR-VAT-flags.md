# Podagent: Explore PR VAT flags

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `ea4b8e9b-b4c7-43bd-9f8c-56f96baa718b` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-07-24 18:35  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\ea4b8e9b-b4c7-43bd-9f8c-56f96baa718b.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Friday, Jul 24, 2026, 6:35 PM (UTC+2)

In D:\PISARNA\Python\Projest and related KirKpr code under D:\PISARNA\Python\KirKpr_convert_cursor (and maybe EvidencaFirm if needed), find how "samoobdavčitev" (self-taxation / reverse charge) and "DDV se odbija" (VAT deductible) work for PR (prejeti računi). Look for:
- UI checkboxes like in Access/KIRKPR
- Fields P9, P10, P11 in KPR
- Accounts 1600/2600 or 16000/26000
- How journal preview / Minimax posting uses these flags
- account_rules remembering supplier settings

Return: file paths, key function names, DB columns if any, and what needs to be added to Projest Studio PR editor based on existing KirKpr patterns. Be thorough but concise.

### 🤖 Asistent

I'll search Projest, KirKpr_convert_cursor, and EvidencaFirm for samoobdavčitev / DDV odbija patterns on PR.

- 🔧 `UpdateCurrentStep`
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Glob` — **/EvidencaFirm*/**/*.{py,md}

- 🔧 `UpdateCurrentStep`
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Grep` — D:\PISARNA\Python\EvidencaFirm
- 🔧 `Glob` — **/*pr*

- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\pr_editor.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\ui\pr_editor.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\journal_preview.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\NAVODILA_convert_KIrKpr_to_minimax.txt

- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\journal_preview.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\db.py

- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\vendor_kirkpr\minimax_api_client.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\pr_editor.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\pr_editor.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_dataset.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py

- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `UpdateCurrentStep`

## How it works in KirKpr (source of truth)

**UI (Access/KIRKPR-style checkboxes)**  
`D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py` — PR detail form (~9500–9633):
- `Samoobdavčitev` / `DDV se odbija` checkboxes
- `Zapomni si konto, samoobdavčitev in DDV se odbija za dobavitelja`
- Bulk: `set_selected_vat_deductible`, list columns `self_tax` / `vat_deductible`

**Core flag logic**  
`D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py` (vendored copy in Projest: `projest_studio\vendor_kirkpr\kirkpr_minimax_core.py`):

| Function | Role |
|---|---|
| `source_self_assessment` | True if **KPR P9/P10/P11** ≠ 0 |
| `is_self_assessment` | Manual `__samoobdavcitev__` / `MINIMAX_SAMOOBDAVCITEV` else source |
| `vat_is_deductible` | Manual `__ddv_se_odbija__` / `MINIMAX_DDV_SE_ODBIJA` (default **True**) |
| `apply_saved_accounts` | Merge doc/supplier rules; P9–P11 → offer self-tax + default deductible |
| `remember_self_assessment` / `remember_vat_deductible` / `remember_account` | Persist |
| `pr_metrics` | Gross/payable/expense from flags |

**KPR field meaning (DDV-O)** — same file, `DDVO_FIELDS`:
- **P9** → field 31a (76.a / reverse charge SI)
- **P10** → 32 (EU goods)
- **P11** → 32a (EU services)

**Config “DB” (not SQL)** — `convert_KIrKpr_to_minimax_config.json` / per-company `company_profiles`:
- `document_self_assessment`, `document_vat_deductible`
- `supplier_self_assessment`, `supplier_vat_deductible`
- `document_accounts`, `supplier_accounts`  
Keys: `row_key("PR", …)`, `supplier_key(…)` (tax/name).

**Journal / Minimax posting**  
`convert_ddv_json_to_minimax.py` — `RATE_INFO`:
- Input: **16000 / 16001 / 16002** (legacy catalog also has 1600)
- Output (self-tax credit): **26000 / 26001 / 26002**

When `self_assessment`:
1. XML header `Samoobdavcitev=D`
2. Supplier credit = net only (VAT not on payable)
3. Credit VAT → 260xx
4. If `vat_deductible`: debit VAT → 160xx; else VAT into expense (`NeodbitiDDV*`)

API notes: `minimax_api_client.prepare_received_invoice_payload` uses `pr_metrics` flags. Minimax journals read `SelfTaxing` → flags in `kirkpr_minimax_dataset.py`.

Docs: `NAVODILA_convert_KIrKpr_to_minimax.txt` §718–793.

---

## Projest Studio today

| Area | Path | Behavior |
|---|---|---|
| PR editor | `projest_studio\ui\pr_editor.py` | Edits **f76a / eu_goods / eu_services** (= P9–P11 amounts). Only checkbox: **Zapomni konto**. No Samoobdavčitev / DDV se odbija. |
| Journal preview | `projest_studio\journal_preview.py` | Always debits 160xx for VAT; **never** 260xx; ignores non-deductible → expense. |
| DDV-O bridge | `projest_studio\ddvo_calc.py` → `pr_row_to_kpr` | Hardcodes `__ddv_se_odbija__=True`, `__samoobdavcitev__=bool(f76a\|eu_goods\|eu_services)`; synthesizes KIR via `pr_row_to_synthetic_kir`. |
| SQLite | `projest_studio\db.py` | `pr_rows`: amount cols + `odhodek01/07`, `placilo` — **no** flag columns. `account_rules`: accounts only — **no** self-tax / deductible. |
| Remember | `ui\app.py` + `db.upsert_account_rule` | Remembers expense/payment accounts only. |

**EvidencaFirm**: not involved in this VAT logic.

---

## What to add to Projest Studio PR editor

1. **UI** (mirror KirKpr): checkboxes `Samoobdavčitev`, `DDV se odbija`; expand remember to “konto + samoobdavčitev + DDV se odbija”; show offer source (P9–P11 / dobavitelj).
2. **Defaults**: `source = f76a\|eu_goods\|eu_services`; if self-tax and no saved rule → deductible True; allow override.
3. **Persistence**: `pr_rows.self_assessment`, `pr_rows.vat_deductible` (or `raw_json`); `account_rules.self_assessment`, `account_rules.vat_deductible` (or equivalent).
4. **`journal_preview.preview_pr_journals`**: match KirKpr — self-tax → credit 260xx; deductible → debit 160xx; else VAT on expense; payable without VAT when self-tax.
5. **`pr_row_to_kpr` / sync**: use stored flags, not hardcoded True/auto.
6. Reuse vendored `kirkpr_minimax_core` helpers rather than reimplementing.
