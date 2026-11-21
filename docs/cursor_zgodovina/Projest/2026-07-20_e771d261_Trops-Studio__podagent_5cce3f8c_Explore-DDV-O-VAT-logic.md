# Podagent: Explore DDV-O VAT logic

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `5cce3f8c-2fb9-4120-8c2a-00d384bf7306` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-07-22 02:13  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\5cce3f8c-2fb9-4120-8c2a-00d384bf7306.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Wednesday, Jul 22, 2026, 2:13 AM (UTC+2)

Explore VAT/DDV-O calculation logic for reverse charge (prevalitev) vs domestic SLO DDV in these codebases. Return concrete findings with file paths and key function names.

1. D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py - full logic of how fields 41, 42, input/output VAT, obligation are computed. Note mapping from IR/PR rows.

2. D:\PISARNA\Python\KirKpr_convert_cursor\ - search for prevalitev, samoobdavčitev, field 41, 31, 32, reverse charge, DDV-O summary. How does KirKpr distinguish domestic input VAT vs reverse charge?

3. D:\PISARNA\Python\Projest\ - any Access-related, projest.py, or comments about prevalitev / SLO DDV / field 41.

4. Look at PR row fields in projest_studio/db.py and excel mapping - fields like vat_22, eu_goods, eu_services, f76a, exempt, etc.

5. Check agent transcript C:\Users\braco\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\e771d261-8f34-4c57-91b0-480a379ad85e\e771d261-8f34-4c57-91b0-480a379ad85e.jsonl for any prior notes about prevalitev or Access DDV calculation if searchable.

Return:
- Exact formulas Access/KirKpr use for: DDV skupaj PR (domestic), prevalitev, DDV za plačilo
- What Projest currently does wrong
- Which PR/IR fields map to prevalitev vs SLO DDV
- Suggested fix approach for ddvo_calc.py and ddvo_tab.py UI (show prevalitev + domači DDV)

### 🤖 Asistent

Searching the codebase for DDV-O, reverse charge, and prevalitev logic across the listed paths.

[REDACTED]

- 🔧 `UpdateCurrentStep`
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Grep` — C:\Users\braco\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\e771d261-8f34-4c57-91b0-480a379ad85e\e771d261-8f34-4c57-91b0-480a379ad85e.jsonl

[REDACTED]

- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\ddvo_tab.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\excel_map.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest.py

[REDACTED]

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — C:\Users\braco\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\e771d261-8f34-4c57-91b0-480a379ad85e\e771d261-8f34-4c57-91b0-480a379ad85e.jsonl

[REDACTED]

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\db.py

[REDACTED]

- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\NAVODILA_convert_KIrKpr_to_minimax.txt
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py

[REDACTED]

- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py

[REDACTED]

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\NAVODILA_convert_KIrKpr_to_minimax.txt
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest.py

[REDACTED]

- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\knjige.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\NAVODILA_convert_KIrKpr_to_minimax.txt
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py

[REDACTED]

- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\knjige.py

[REDACTED]

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\knjige.py

[REDACTED]

- 🔧 `UpdateCurrentStep`

## Executive summary

Projest Studio’s DDV-O path (`ddvo_calc.py` → KirKpr `ddvo_summary`) correctly maps **PR input VAT to fields 41/42/42a**, but it **does not supply matching KIR output VAT (P17–P26 → fields 23–26/25)** for reverse-charge/prevalitev rows. That makes **ODBITNI DDV too high** and **OBRAČUNANI DDV too low**, so field **51 (DDV za plačilo)** is wrong for periods with EU/76.a purchases.

---

## 1. `ddvo_calc.py` — current logic

**File:** `D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py`

| Function | Role |
|---|---|
| `ir_row_to_kir()` | Maps SQLite IR → KIR P7–P27 |
| `pr_row_to_kpr()` | Maps SQLite PR → KPR P8–P21 + flags |
| `build_dataset()` | Builds `KirkprDataset` |
| `compute_ddvo()` | Calls KirKpr `ddvo_summary()` |

### IR → KIR mapping

```14:46:D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py
def ir_row_to_kir(row: Mapping[str, Any]) -> dict[str, Any]:
    ...
        "P7": decimal_value(row.get("net")),
        "P8": decimal_value(row.get("reverse_charge")),   # → DDV-O 11a
        "P9": decimal_value(row.get("exempt")),
        "P10": decimal_value(row.get("eu_goods")),        # → DDV-O 12
        "P11": decimal_value(row.get("eu_services")),
        "P14": decimal_value(row.get("vat_22")),          # → DDV-O 21
        "P15": decimal_value(row.get("vat_95")),          # → DDV-O 22
        "P17".."P26": Decimal("0.00")                     # ← always zero
```

**Gap:** KIR P17–P26 (output side of prevalitev) are never populated from SQLite IR.

### PR → KPR mapping

```50:78:D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py
def pr_row_to_kpr(row: Mapping[str, Any]) -> dict[str, Any]:
    ...
        "P8": decimal_value(row.get("net_taxable")),      # → DDV-O 31 (domestic base)
        "P9": decimal_value(row.get("f76a")),             # → DDV-O 31a
        "P10": decimal_value(row.get("eu_goods")),       # → DDV-O 32
        "P11": decimal_value(row.get("eu_services")),    # → DDV-O 32a
        "P18": decimal_value(row.get("vat_22")),         # → DDV-O 41
        "P19": decimal_value(row.get("vat_95")),         # → DDV-O 42
        "P20": decimal_value(row.get("vat_5")),          # → DDV-O 42a
        "__ddv_se_odbija__": True,                       # ← always True (hardcoded)
        "__samoobdavcitev__": bool(f76a or eu_goods or eu_services)
```

---

## 2. KirKpr / Access formulas (reference)

**Core:** `D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py`

### DDV-O field definitions (FURS e-DDV_O_11.7)

| DDV-O | Meaning | Source |
|---|---|---|
| **31** | Domestic purchases base | KPR **P8** |
| **31a** | Domestic reverse-charge base (76.a) | KPR **P9** |
| **32** | EU goods acquisition base | KPR **P10** |
| **32a** | EU services base | KPR **P11** |
| **21–22a** | Output VAT domestic | KIR **P14–P16** |
| **23–24c** | Output VAT EU acquisition | KIR **P17–P22** |
| **25–25b** | Output VAT recipient self-assessment (76.a) | KIR **P23–P25** |
| **41–42a** | Input deductible VAT | KPR **P18–P20** (only if `vat_is_deductible`) |
| **43** | Flat-rate 8% | KPR **P21** |

From NAVODILA (v3.0.24): *“samoobdavčitev EU → **23/23a + 32/32a**”* — bases on PR, output VAT on KIR.

### `ddvo_summary()` formulas

```1562:1647:D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
# Per field: exact = sum(KIR/KPR source columns), rounded to whole EUR
output_vat = Σ fields {21,22,22a,23,23a,24,24a,24b,24c,25,25a,25b,26}
input_vat  = Σ fields {41,42,42a,43}   # P18–P21 skipped if NOT vat_is_deductible
balance    = output_vat − input_vat
field 51 (obveznost) = max(balance, 0)   # DDV za plačilo
field 52 (presežek)   = max(−balance, 0)
control: output − input − 51 + 52 = 0
```

**Virman:** `ddvo_virman_payment(obligation, konto62)` → `payment = max(51 − |konto62 credit|, 0)`

### PR metrics (KirKpr “DDV skupaj PR”)

```1510:1543:D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
reported_vat = P18 + P19 + P20 + P21          # all VAT on invoice
deductible   = reported_vat if vat_is_deductible else 0
self_assessment = P9≠0 OR P10≠0 OR P11≠0 (or flag)
payable = net + nondeduct + (0 if self_assessment else reported_vat)
```

**Domestic vs prevalitev distinction in KirKpr:**

| Type | Detection | DDV-O bases | DDV-O VAT |
|---|---|---|---|
| **Domestic PR** | P8 > 0, P9/P10/P11 = 0 | Field **31** | Input **41/42** only; no extra output |
| **Prevalitev / samoobdavčitev** | P9/P10/P11 > 0 | **31a / 32 / 32a** | Input **41/42** **and** output **23–26** from matching KIR P17–P25 |

**KIR self-assessment link** (`convert_ddv_json_to_minimax.py`):

```295:297:D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
def is_kir_self_assessment(row, kpr_invoice_numbers):
    reverse_vat = sum(P17..P26)
    return invoice in kpr_self_assessment_invoices AND reverse_vat ≠ 0
```

---

## 3. Access / `projest.py` logic

**File:** `D:\PISARNA\Python\Projest\projest.py` — function `build_pr()`

### Excel/Access column → PR book

| Vasco/Excel | Access PR column | SQLite (`excel_map.py`) | KPR | DDV-O |
|---|---|---|---|---|
| Vrednost obdavčenih nabav | `8-Vred brez DDV` | `net_taxable` | P8 | 31 |
| F11 | `9a 76ačlen` | `f76a` | P9 | 31a |
| F12 | `10-Vred PRID BLA` | `eu_goods` | P10 | 32 |
| F13 | `11-Vred PREJ STOR` | `eu_services` | P11 | 32a |
| F24/F26/F28 | `18/19/20-VST … DDV` | `vat_22/95/5` | P18–P20 | 41–42a |

### Access accounting split (output side of prevalitev)

```623:628:D:\PISARNA\Python\Projest\projest.py
ddv_sp_out = "2600-8" if vat_22 and f10 else "2600-4" if vat_22 and f11 else ""
ddv_zn_out = "2600-9" if vat_95 and f10 else "2600-5" if vat_95 and f11 else ""
vat_22_out = -vat_22 if ddv_sp_out else ZERO   # output VAT booked on 2600-xx
```

Access **does not store KIR P17–P26 in `tblDDV_KnjigaIR_21`** — those come from FURS KIR export in KirKpr. Projest Studio only has Excel IR/PR, so **synthetic KIR rows must be generated** for DDV-O.

### PR totals in Access

```447:453:D:\PISARNA\Python\Projest\projest.py
PR vat = Neodbitni 22% + Neodbitni 9,5% + 18-VST + 19-VST   # excludes 5% (known bug)
```

---

## 4. PR/IR SQLite schema & Excel mapping

**Schema:** `D:\PISARNA\Python\Projest\projest_studio\db.py` — tables `ir_rows`, `pr_rows` (fields listed in search results above).

**Excel import:** `D:\PISARNA\Python\Projest\projest_studio\excel_map.py` — `map_ir()`, `map_pr()`.

---

## 5. Agent transcript prior notes

**File:** `C:\Users\braco\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\e771d261-8f34-4c57-91b0-480a379ad85e\e771d261-8f34-4c57-91b0-480a379ad85e.jsonl`

Latest user message (2:12 AM): *“DDV ni pravilno izračunan, verjetno tujina, DDV je input/output … dodaj v DDV-O info glede koliko je prevalitev in koliko domačega DDV”* — matches the missing KIR output-side + UI breakdown gap. No prior fix was implemented in that transcript.

---

## 6. What Projest currently does wrong

| Issue | Effect |
|---|---|
| **No synthetic KIR P17–P26** for PR rows with P9/P10/P11 | Field **41** counted, fields **23–26** = 0 → wrong balance |
| **`ir_row_to_kir` zeroes P17–P26** | Even if FURS KIR existed, it would be dropped |
| **`__ddv_se_odbija__` always True** | Non-deductible PR VAT still flows to 41/42 |
| **PR summary sums all `vat_22+95+5`** without domestic/prevalitev split | Misleading “DDV” chip in IR/PR tabs |
| **No `pr_metrics()` in Projest UI** | KirKpr uses `reported_vat` / `self_assessment`; Projest uses raw column sums |
| **`projest.py` PR `.vat` ignores 5%** | Access import totals understated (separate bug) |

**Typical prevalitev scenario:** EU service PR with P11=100, P18=22 → input field 41=22, but output field 23a=0 → shows **presežek 22** instead of **obveznost ≈ IR output − domestic input**.

---

## 7. Exact split formulas (for UI + fix)

Use KirKpr `pr_metrics()` on mapped KPR rows:

```
DDV skupaj PR     = Σ (P18 + P19 + P20 + P21)           # all invoices
Domači DDV (PR)   = Σ reported_vat where NOT self_assessment
Prevalitev DDV    = Σ reported_vat where self_assessment
Odbitni domači    = Σ (P18+P19+P20) where NOT self_assessment AND vat_is_deductible
Odbitni prevalitev= Σ (P18+P19+P20) where self_assessment AND vat_is_deductible
Output prevalitev = Σ KIR P17..P25 (synthetic)           # must match odbitni prevalitev
DDV za plačilo    = field 51 = max(Σ output(21–26) − Σ input(41–43), 0)
```

---

## 8. Suggested fix approach

### A. `ddvo_calc.py`

1. Add `pr_row_to_synthetic_kir(row)` — for each PR with `f76a|eu_goods|eu_services`:
   - Match invoice no (`document_no`) to KIR `P3`
   - Allocate `vat_22/95/5` to KIR output columns mirroring Access 2600 logic:

   | PR source | KIR column | DDV-O output |
   |---|---|---|
   | `eu_goods` + vat_22 | P17 | 23 |
   | `eu_services` + vat_22 | P18 | 23a |
   | `eu_goods` + vat_95 | P19 | 24 |
   | `eu_services` + vat_95 | P20 | 24a |
   | `f76a` + vat_22 | P23 | 25 |
   | `f76a` + vat_95 | P24 | 25a |
   | `f76a` + vat_5 | P25 | 25b |

2. In `build_dataset()`, append synthetic KIR rows (skip if real KIR row with same P3 + P17–P26 already exists).

3. Import `pr_metrics` / `vat_is_deductible` from KirKpr; stop hardcoding `__ddv_se_odbija__: True` (store flag in SQLite later).

4. Extend `compute_ddvo()` return with breakdown:

   ```python
   domestic_input_vat, reverse_input_vat,
   domestic_output_vat, reverse_output_vat,
   self_assessment_count
   ```

### B. `ddvo_tab.py`

Add 2 summary cards or extend `flags_var`:

- **Domači odbitni DDV** — sum of fields 41–43 from non–self-assessment PR
- **Prevalitev (samoobdavčitev)** — input 41–43 from self-assessment PR + output 23–26/25 (should net ~0 per invoice)

Show control line like KirKpr:

```
Obračunani X − Odbitni Y − 51 + 52 = 0
Prevalitev: input A / output B | Domači: input C
```

### C. PR/IR list totals (`app.py`)

Replace raw VAT sum with `pr_metrics()` split; tag self-assessment rows (purple, like KirKpr `self_assessment` tag).

---

## Key file index

| Path | Key symbols |
|---|---|
| `D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py` | `ir_row_to_kir`, `pr_row_to_kpr`, `compute_ddvo` |
| `D:\PISARNA\Python\Projest\projest_studio\ui\ddvo_tab.py` | `DdvoTab.refresh` |
| `D:\PISARNA\Python\Projest\projest_studio\excel_map.py` | `map_pr`, `map_ir` |
| `D:\PISARNA\Python\Projest\projest_studio\db.py` | `pr_rows`, `ir_rows` schema |
| `D:\PISARNA\Python\Projest\projest.py` | `build_pr`, `ImportRow.vat/net` |
| `D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py` | `DDVO_FIELD_DEFINITIONS`, `ddvo_summary`, `pr_metrics`, `source_self_assessment` |
| `D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py` | `is_kir_self_assessment`, `build_received` |
| `D:\PISARNA\Python\KirKpr_convert_cursor\NAVODILA_convert_KIrKpr_to_minimax.txt` | DDV-O rules §715–739 |

[REDACTED]
