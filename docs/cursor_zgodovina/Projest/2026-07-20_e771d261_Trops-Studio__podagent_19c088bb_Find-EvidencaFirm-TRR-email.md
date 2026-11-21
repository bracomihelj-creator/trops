# Podagent: Find EvidencaFirm TRR/email

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `19c088bb-344c-4269-b1b0-d6f0106d8fb4` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-07-24 17:14  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\19c088bb-344c-4269-b1b0-d6f0106d8fb4.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Friday, Jul 24, 2026, 5:14 PM (UTC+2)

In D:\PISARNA\Python\Projest and related KirKpr paths (D:\PISARNA\Python\KirKpr_convert, vendor_kirkpr), find how EvidencaFirm / AJPES lookup extracts TRR (IBAN/bank account), email, phone, and other contact fields.

Search for: EvidencaFirm, podjetje.asp, TRR, IBAN, telefon, Email, ajpes_client, lookup_si_company.

Return:
1. Exact file paths and functions that parse these fields
2. Field names used in the API/HTML response
3. How Projest's ajpes_client.py currently maps (or misses) TRR/email/phone
4. DB schema: does parties table have TRR/iban column?
5. Concrete recommendation of what to copy into projest_studio to match EvidencaFirm behavior

Be thorough - read the actual parsing code.

### 🤖 Asistent

I'll search Projest and related KirKpr paths for EvidencaFirm/AJPES parsing of TRR, email, and phone.

- 🔧 `UpdateCurrentStep`
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Glob` — **/ajpes_client.py
- 🔧 `Glob` — **/vendor_kirkpr/**/*.{py,cs,vb,asp}
- 🔧 `GetDynamicTools`

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/*ajpes*
- 🔧 `Grep` — D:\PISARNA\Python\EvidencaFirm
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ajpes_client.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Shell` — List Python dirs and Kir/EvidencaFirm

- 🔧 `Read` — D:\PISARNA\Python\EvidencaFirm\ajpes_prs_lookup.py
- 🔧 `Read` — D:\PISARNA\Python\EvidencaFirm\ajpes_company_service.py
- 🔧 `Glob` — **/minimax_ajpes*.py
- 🔧 `Grep` — D:\PISARNA\Python\EvidencaFirm
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Shell` — List Python and EvidencaFirm AJPES files

Next I'll read the UPN/`minimax_ajpes` parsers that actually scrape podjetje.asp for IBAN and contacts.

- 🔧 `Grep` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Grep` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Glob` — **/*ajpes*
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\vendor_kirkpr
- 🔧 `Glob` — **/*ajpes*

- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Glob` — **/kirkpr_ajpes*

The key gap is key naming and missing TRR mapping — digging into the UPN HTML parsers next.

- 🔧 `UpdateCurrentStep`
- 🔧 `Grep` — D:\PISARNA\Python\Podatki\minimax_tools
- 🔧 `Grep` — D:\PISARNA\Python\Podatki
- 🔧 `Glob` — **/*ajpes*
- 🔧 `Shell` — Locate UPN ajpes modules and paths

- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Grep` — D:\PISARNA\Python\UPN_nalog
- 🔧 `Glob` — **/*ajpes*
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_ajpes_iban.py
- 🔧 `Grep` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py

- 🔧 `Read` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py
- 🔧 `Read` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py
- 🔧 `Read` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py
- 🔧 `Grep` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py
- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py

- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `Grep` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_ajpes_iban.py
- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\stranke_dialog.py
- 🔧 `Grep` — D:\PISARNA\Python\EvidencaFirm\trr_store.py

- 🔧 `Read` — D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py
- 🔧 `Grep` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py
- 🔧 `Read` — D:\PISARNA\Python\EvidencaFirm\trr_store.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\db.py
- 🔧 `UpdateCurrentStep`

- 🔧 `Read` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py
- 🔧 `Grep` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py
- 🔧 `Read` — D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py

## Verdict

EvidencaFirm’s full AJPES path fills **TRR from eRTR** (`iban`), and **email/phone from `podjetje.asp?p=1`** (lowercase detail keys). Projest already calls a lighter enrich that can populate those keys, but **`AjpesResult` never maps IBAN**, phone merge is incomplete vs EvidencaFirm, and **`parties` has no TRR/iban column**.

---

### 1. Exact paths & functions that parse the fields

| Layer | Path | Functions |
|--------|------|-----------|
| Projest entry | `D:\PISARNA\Python\Projest\projest_studio\ajpes_client.py` | `lookup_si_company`, `_enrich_pick` → `enrich_ajpes_candidate_detail` |
| EvidencaFirm search | `D:\PISARNA\Python\EvidencaFirm\ajpes_prs_lookup.py` | `lookup_ajpes`, `lookup_ajpes_by_davcna_eprs`, `_lookup_eprs_url` |
| EvidencaFirm form mapping | `D:\PISARNA\Python\EvidencaFirm\ajpes_company_service.py` | `fetch_full_ajpes_detail`, **`company_record_from_candidate`**, `_merge_ajpes_phones` |
| Orchestration / p=1 / eRTR | `D:\PISARNA\Python\Podatki\minimax_tools\minimax_ajpes.py` | `enrich_ajpes_candidate_detail`, `fetch_ajpes_eprs_chain`, **`parse_podjetje_p1_html`**, `_parse_contact_combined_block`, `_merge_ertr_into_candidate` |
| Raw HTML PRS parser | `D:\PISARNA\Python\UPN_nalog\generate_upn_gui_v11.py` | **`_ajpes_parse_podjetje_detail`**, `ajpes_fetch_podjetje_detail`, `ajpes_lookup_ertr_party`, `_ajpes_ertr_fetch_via_results` |
| TRR storage / normalize | `D:\PISARNA\Python\EvidencaFirm\trr_store.py` | `normalize_iban`, `split_iban_list`, `upsert_trr_accounts` |
| KirKpr IBAN reuse | `D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_ajpes_iban.py` | `fetch_payer_ibans_from_ajpes` → `company_record_from_candidate` |

**Fetch chain (EvidencaFirm / minimax):**  
ePRS `rezultati.asp` → `podjetjeSRG.asp` → **`podjetje.asp?p=1`** → **eRTR** (IBAN if missing).

Note: `D:\PISARNA\Python\KirKpr_convert` does not exist; related code is under `KirKpr_convert_cursor` and `Projest\projest_studio\vendor_kirkpr`.

---

### 2. Field names in HTML / API / detail dict

**AJPES HTML labels (podjetje.asp):**

| UI label | Parsed detail key |
|----------|-------------------|
| `Telefon`, `Telefonska številka`, `Tel.` | `telefon` |
| `Telefaks`, `Faks`, `Fax` | `telefaks` |
| `GSM`, `Mobilni telefon`, … | `gsm` |
| Combined `telefon/telefaks/e-pošta` | split → `telefon` / `telefaks` / `gsm` / `email` |
| `E-pošta`, `Epošta`, `Elektronska pošta`, `Email` | `email` (+ mirror `eposta`) |
| `Transakcijski računi` / `Transakcijski račun` / `TRR` | → SI IBAN → `iban` (p=1 fallback only) |
| `Firma`, `Skrajšana firma` | `company_name`, `short_name` |
| `Matična številka` | `maticna` |
| `Ident. št. za DDV in davčna številka` | `davcna` |
| `Poslovni naslov` / `Sedež` | `address`, `city` |

**eRTR / REST:**

- eRTR result attribute / row: `iban`, status → `iban_status` (`SI56…=odprt`)
- REST PRS: `racun[].stTrr` → joined into `iban`

**EvidencaFirm form record keys** (`company_record_from_candidate`):

- `Transakcijski račun` ← `detail["iban"]` / `["trr"]`
- `Email` ← `email` / `eposta`
- `Telefon` ← merged `telefon` + `telefaks` + `gsm`
- Also: `NASLOV`, `DAVČNA`, `MATIČNA`, `AJPES sifra`, …

---

### 3. How Projest `ajpes_client.py` maps / misses fields

```213:230:D:\PISARNA\Python\Projest\projest_studio\ajpes_client.py
    return AjpesResult(
        ok=True,
        ...
        email=_detail_get(detail, "Email", "E-pošta", "E-posta"),
        phone=_detail_get(detail, "Telefon", "Phone"),
        ...
    )
```

| Field | Status |
|-------|--------|
| **email** | Works if enrich filled `email`/`eposta` (casefold of `"Email"`). |
| **phone** | Only `telefon` / `Phone`. **Misses `gsm` and `telefaks`** (EvidencaFirm merges them). |
| **TRR / IBAN** | **Not on `AjpesResult` at all**, even though enrich often puts `iban` in `detail` via eRTR. |
| Enrich depth | Uses `enrich_ajpes_candidate_detail` only — **not** EvidencaFirm’s `company_record_from_candidate` / full ePRS chain used for form+TRR upsert. |

UI (`stranke_dialog.py`) fills email/phone from the result; there is **no TRR field** in the dialog payload.

---

### 4. DB schema: `parties` and TRR/IBAN

`D:\PISARNA\Python\Projest\projest_studio\db.py` — `parties` has:

- `email`, `phone` — yes  
- **`iban` / `trr` / `Transakcijski račun` — no**  
- Migrations only add `minimax_code` / `sync_status`, not IBAN

EvidencaFirm stores TRRs separately in `trr_evidenca.json` (+ SQL `ClientTrr`), not only on the company row.

---

### 5. Concrete recommendation for `projest_studio`

**Best match to EvidencaFirm (same as KirKpr):** after `lookup_ajpes` + pick, call:

```python
from ajpes_company_service import company_record_from_candidate
record, ibans, note, iban_status = company_record_from_candidate(pick, zst=0)
# then map:
# name ← Kratko ime / Dolgo
# address ← NASLOV
# email ← Email
# phone ← Telefon   # already merged gsm/telefaks
# iban ← Transakcijski račun or ibans[0]
# ajpes_code ← AJPES sifra
```

**Minimal patch if you keep current `enrich_ajpes_candidate_detail` path:**

1. Add `iban: str = ""` (and optionally `ibans: list[str]`) to `AjpesResult`.
2. Map:  
   `_detail_get(detail, "iban", "trr", "Transakcijski račun")`  
   phone: also `"gsm"`, `"telefaks"` (or copy `_merge_ajpes_phones`).
3. Prefer lowercase keys explicitly: `"email"`, `"eposta"`, `"telefon"`.
4. Schema: `ALTER TABLE parties ADD COLUMN iban TEXT NOT NULL DEFAULT ''` (optional second column / JSON for multi-IBAN), wire upsert in `db.upsert_party` and `stranke_dialog`.
5. For Minimax banks, mirror EvidencaFirm’s `_add_customer_banks_like_stranke` / KirKpr bank helpers — contact email/phone alone is not enough for TRR.

**Do not reinvent HTML parsing** — reuse UPN/`minimax_ajpes`/`ajpes_company_service`; Projest’s gap is mapping + persistence, not the scrapers.
