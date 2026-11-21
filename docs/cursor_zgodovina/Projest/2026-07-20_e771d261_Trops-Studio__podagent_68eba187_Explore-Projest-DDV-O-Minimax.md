# Podagent: Explore Projest DDV-O + Minimax

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `68eba187-5932-48d7-94ed-55124ae762b9` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-07-23 09:12  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\68eba187-5932-48d7-94ed-55124ae762b9.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Thursday, Jul 23, 2026, 9:12 AM (UTC+2)

Explore D:\PISARNA\Python\Projest\projest_studio for:

1. Current DDV-O tab/calc (ddvo_tab.py, ddvo_calc.py, etc.) — what it shows, what's missing vs a full verify/export flow.
2. How Minimax is accessed today (kirkpr_bridge, minimax_parties, open_minimax_client) — dependencies on KirKpr path.
3. Gaps for standalone Minimax: own client, credentials, email, forms, API check.

Return file paths and concise gap list.

### 🤖 Asistent

I'll explore `projest_studio` for the DDV-O flow, Minimax access paths, and standalone gaps.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/*ddvo*
- 🔧 `Glob` — **/*minimax*
- 🔧 `Glob` — **/*kirkpr*
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio

- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ui\ddvo_tab.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\kirkpr_bridge.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\minimax_parties.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\minimax_sync.py

- 🔧 `UpdateCurrentStep`
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\config.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio\ui\app.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\account_choices.py

- 🔧 `Glob` — **/minimax_api_client*
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest_studio
- 🔧 `Glob` — **/*ddvo*
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\xml_export.py

- 🔧 `UpdateCurrentStep`

## Key files

| Area | Path |
|------|------|
| DDV-O UI | `D:\PISARNA\Python\Projest\projest_studio\ui\ddvo_tab.py` |
| DDV-O calc | `D:\PISARNA\Python\Projest\projest_studio\ddvo_calc.py` |
| Wiring / refresh | `D:\PISARNA\Python\Projest\projest_studio\ui\app.py` |
| Knjige DDV-O labels | `D:\PISARNA\Python\Projest\projest_studio\ui\knjige.py` |
| KirKpr path bridge | `D:\PISARNA\Python\Projest\projest_studio\kirkpr_bridge.py` |
| Paths config | `D:\PISARNA\Python\Projest\projest_studio\config.py` |
| Minimax parties/API | `D:\PISARNA\Python\Projest\projest_studio\minimax_parties.py` |
| Confirm → XML sync | `D:\PISARNA\Python\Projest\projest_studio\minimax_sync.py` |
| Journal XML export | `D:\PISARNA\Python\Projest\projest_studio\xml_export.py` |
| Account catalog via API | `D:\PISARNA\Python\Projest\projest_studio\account_choices.py` |
| Company registry (also KirKpr) | `D:\PISARNA\Python\Projest\projest_studio\companies.py` |

KirKpr reference (full DDV-O + API): `D:\PISARNA\Python\KirKpr_convert_cursor\` (`convert_KIrKpr_to_minimax.py`, `minimax_api_client.py`, `kirkpr_ddvo_*.py`, `ddvo_obrazec_eDDV_O_11.7.json`)

---

## 1. Current DDV-O — what it shows vs verify/export

**Shows (read-only control):**
- Title “Kontrolni obrazec DDV-O (e-DDV_O_11.7)”, taxpayer, period, search
- **Preračunaj** + filter Vse / <> 0
- Cards: obračunani (21–26), odbitni (41–43), 51/52; split domači SLO vs prevalitev; Access-style payable line; control OK/odstopanje
- INFO chips: F21/F22 uvoz, excluded, MRN, neodbitni, OPR OS (not in DDV-O math)
- Field table: section, code, description, source, exact/rounded/diff/status

**Calc path:** SQLite IR/PR → `ir_row_to_kir` / `pr_row_to_kpr` + synthetic KIR for prevalitev → KirKpr `KirkprDataset` + `ddvo_summary` / `pr_metrics`.

**Missing vs KirKpr full verify/export flow:**
- PDF preview / export (`kirkpr_ddvo_pdf`)
- eDavki XML (`kirkpr_ddvo_xml`, obrazec JSON)
- Minimax compare view (JSON + Minimax amounts)
- Minimax tisk DDV-O
- PDF + SEPA virman (`kirkpr_ddvo_virman`)
- Client email + templates (`kirkpr_ddvo_email_*`)
- Copy control / save kontrolni pregled
- No DDV-O export buttons on Projest tab (only Preračunaj)

Projest “Minimax sync” is **customers API + journal XML**, not DDV-O form export.

---

## 2. How Minimax is accessed today (KirKpr dependency)

```
config.KIRKPR_CURSOR_ROOT / KIRKPR_LEGACY_ROOT
        ↓
kirkpr_bridge.ensure_kirkpr_on_path()  → sys.path.insert
        ↓
minimax_parties.open_minimax_client(org_id)
  → from minimax_api_client import ApiSettings, MinimaxClient, resolve_settings_path
  → ApiSettings.from_file(resolve_settings_path())  # KirKpr/DavčnaBlagajna JSON
  → authenticate() + select_organisation(org)
```

Also on KirKpr path:
- `ddvo_calc` / `knjige` → `kirkpr_minimax_core`
- `xml_export` → KirKpr XML builders + `miniMAXUvozKnjigovodstvo.xsd`
- `companies.py` → `kirkpr_company_registry` (same roots)

Hardcoded roots: `D:\PISARNA\Python\KirKpr_convert_cursor` then `...\KirKpr_convert`. No KirKpr folder → `FileNotFoundError`.

---

## 3. Gaps for standalone Minimax

| Gap | Today |
|-----|--------|
| Own API client | Imports KirKpr `minimax_api_client` only |
| Own credentials / settings path | Uses KirKpr `resolve_settings_path()` (shared JSON); no Projest settings UI/file |
| Email (DDV-O / virman) | Not in Projest; lives in KirKpr `kirkpr_ddvo_email_*` |
| Forms (PDF/XML obrazec) | Not in Projest; KirKpr `kirkpr_ddvo_pdf/xml` + `ddvo_obrazec_eDDV_O_11.7.json` |
| API health / “check connection” UI | Silent fail in `account_choices_from_minimax`; sync throws; no dedicated ping |
| DDV-O verify vs Minimax | No compare mode |
| Decouple DDV-O math | Still requires `kirkpr_minimax_core.ddvo_summary` |
| XSD / journal XML helpers | Still via `kirkpr_bridge.minimax_xsd_path()` + KirKpr modules |

**Already in Projest (but still KirKpr-backed):** pull customers, create customers, sync ready → parties + IR/PR XML to disk.
