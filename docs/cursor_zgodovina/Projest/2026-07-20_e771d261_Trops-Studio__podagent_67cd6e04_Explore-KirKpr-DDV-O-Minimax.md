# Podagent: Explore KirKpr DDV-O + Minimax

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `67cd6e04-eab1-4d7b-9dbe-9b990de58cb7` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-07-23 09:12  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\67cd6e04-eab1-4d7b-9dbe-9b990de58cb7.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Thursday, Jul 23, 2026, 9:12 AM (UTC+2)

Explore D:\PISARNA\Python\KirKpr_convert_cursor thoroughly for:

1. DDV-O / DDVO implementation — UI, calculation, preview, export, verification/check flow. Key files, how user "preverja" (verifies) DDV-O.
2. Minimax integration that makes KirKpr "standalone": API client usage, auth, org, account catalog, customers, any email sending, form submission, XML export/upload, validation against XSD.
3. What patterns Projest should copy so it can access Minimax independently (not only via KirKpr bridge/path hacks).

Return concrete file paths, function names, and a short list of features to port. Focus on DDV-O UX + Minimax self-contained client.

### 🤖 Asistent

I'll explore KirKpr_convert_cursor for DDV-O flows and the standalone Minimax client patterns.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/*.{py,md,json,xml,xsd,html,js,ts,tsx}
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor

- 🔧 `UpdateCurrentStep`
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\README_CURSOR.md
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\EXCEL_PROJEST_MOST.txt
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py

- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_ddvo_xml.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_ddvo_pdf.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py

- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\NAVODILA_convert_KIrKpr_to_minimax.txt
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py

- 🔧 `UpdateCurrentStep`
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_company_registry.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py

- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\kirkpr_bridge.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_KIrKpr_to_minimax.py

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\convert_ddv_json_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_ddvo_xml.py
- 🔧 `Read` — D:\PISARNA\Python\Projest\projest_studio\minimax_parties.py
- 🔧 `UpdateCurrentStep`

## 1. DDV-O / DDVO — how “preverjanje” works

**“Preverja” = control equation + optional Minimax diff**, not eDavki API submission. XML is an unsigned control draft; PDF uses local eDavki XSLT.

### Core calculation
| Path | Functions |
|------|-----------|
| `D:\PISARNA\Python\KirKpr_convert_cursor\kirkpr_minimax_core.py` | `DDVO_FIELD_DEFINITIONS`, `ddvo_codes_for_field`, `load_ddvo_form_layout`, **`ddvo_summary`**, **`ddvo_control_report`**, `ddvo_virman_payment`, `edavki_konto62_credit` |
| `D:\PISARNA\Python\KirKpr_convert_cursor\ddvo_obrazec_eDDV_O_11.7.json` | Form layout metadata |

**Control check** (green/red bar + tab badge):  
`obračunani (21–26) − odbitni (41–43) − 51 + 52 == 0` → `control_ok` / `control_difference`.

Deductible VAT: KPR P18–P21 only if `vat_is_deductible(row)`.

### UI + user verify flow
| Path | Functions |
|------|-----------|
| `...\convert_KIrKpr_to_minimax.py` | `_build_ddvo_tab`, `_populate_ddvo`, `recalculate_ddvo`, `show_ddvo_json_view`, `show_ddvo_compare_view`, `copy_ddvo_control`, `save_ddvo_report`, `preview_ddvo_pdf`, `export_ddvo_pdf_xml`, `print_ddvo_minimax`, `create_ddvo_pdf_virman` |

**How the user verifies:**
1. Open KIR/KPR → DDV-O tab auto-fills via `ddvo_summary`.
2. Green bar = **KONTROLA OK**; red = **RAZLIKA**; notebook title `DDV-O • KONTROLA OK|PREVERI RAZLIKO`.
3. **JSON** = local only; **JSON + Minimax** connects API, filters invoices present in Minimax, re-runs `ddvo_summary`, shows Δ per field.
4. **Preračunaj** / **Kopiraj kontrolni podatek** / **Shrani kontrolni pregled…**.
5. CLI: `cli_validate` → exit `0` if `control_ok` else `1`.

### Preview / export / virman / email
| Path | Role |
|------|------|
| `kirkpr_ddvo_xml.py` | `build_ddvo_envelope`, `build_ddvo_xml_bytes`, `write_ddvo_xml` (no eDavki signatures) |
| `kirkpr_ddvo_pdf.py` | `xml_to_display_html`, `build_ddvo_pdf`, `write_ddvo_preview_html` |
| `ddvo_transforms\DDV_O_11.7-display-sl.xslt` | Official display transform |
| `kirkpr_ddvo_virman.py` | `build_furs_ddv_pain001_xml`, `write_virman_package`, `compose_outlook_with_attachments`, `build_ddvo_client_email` |
| `kirkpr_ddvo_email_*.py` + JSON presets | Outlook template editor |
| `kirkpr_edavki_konto62.py` | Konto 62 credit for payment = field 51 − 62 |

**Minimax** button (`print_ddvo_minimax`): sync compare → PDF/XML → confirm virman (51 − 62) → optional Outlook email.

Docs: `NAVODILA_convert_KIrKpr_to_minimax.txt` § “OBRAZEC DDV-O…”, `README_CURSOR.md`.

---

## 2. Minimax self-contained client (what makes KirKpr standalone)

### Auth + settings (no hard-coded secrets)
| Path | Functions |
|------|-----------|
| `D:\PISARNA\Python\KirKpr_convert_cursor\minimax_api_client.py` | `ApiSettings.from_file`, `shared_settings_candidates`, `resolve_settings_path`, `MinimaxClient.authenticate` (OAuth password grant), `_authorized_request` (401 retry) |

Settings search order:
1. `...\DavčnaBlagajna\blagajna_minimax_settings.json`
2. `...\Podatki\minimax_config.json`
3. local `minimax_api_settings.json`

### `MinimaxClient` surface to copy
| Area | Methods |
|------|---------|
| Org | `organisations`, `select_organisation`, `organisation_label` |
| Catalogs | `account_catalog`, `item_catalog`, `document_numbering_catalog`, `vat_accounting_type_catalog`, `refresh_references` (`journaltypes`, `accounts`, `customers`, `vatrates`, `currencies`, `items`) |
| Customers | `_customer_lookup`, `_customer_reference`, `_enrich_journal_customers` |
| Invoices | `received_invoices`, `invoice_book`, `invoice_status_catalog`, `existing_document_references`, attachments |
| Journals | `journals`, `journal`, `journal_books`, `prepare_journal_payload`, `_send_journal_with_vat` |
| Submit | `prepare_issued_invoice_payload`, `prepare_received_invoice_payload`, `preflight_row`, **`validate_rows`**, **`send_row`** |
| Dedup | `_assert_unique_document_reference` |

API base: `https://moj.minimax.si/SI/API` · Auth: `.../AUT/OAuth20/Token`.

GUI wiring: `ConverterApp.connect_minimax_api`, `validate_api_selection` (“Predpreveri izbrane”), org from `kirkpr_company_registry.company_org_id`.

### XML export + XSD (import path, not API upload)
| Path | Functions |
|------|-----------|
| `convert_ddv_json_to_minimax.py` | `build_issued`, `build_received`, **`write_and_validate`** (lxml `XMLSchema.assertValid`) |
| `kirkpr_minimax_core.py` | `find_xsd`, `_write_xml`, **`export_minimax`**, `_validate_balances` |
| `miniMAXUvozKnjigovodstvo.xsd` | Schema |
| CLI | `cli_dry_run` — temp export + XSD, then delete |

Email is **Outlook COM** (virman package), not Minimax mail API. Browser automation (`kirkpr_minimax_pw\`, `kirkpr_minimax_browser.py`) is optional PR UI assist, not the API client.

---

## 3. What Projest should copy (drop `kirkpr_bridge` path hacks)

Projest today: `projest_studio\kirkpr_bridge.py` → `sys.path` into KirKpr; wrappers in `ddvo_calc.py`, `minimax_parties.py`, `xml_export.py`.

### Port list (priority)
1. **Vendored Minimax client** — copy `minimax_api_client.py` (+ thin deps if needed); local `resolve_settings_path` / same settings candidates; stop importing via bridge.
2. **DDV-O calc** — `ddvo_summary` / `DDVO_FIELD_DEFINITIONS` / `ddvo_control_report` (or keep `ddvo_calc` but remove KirKpr import).
3. **XML + XSD** — `convert_ddv_json_to_minimax.py` builders + `write_and_validate` + ship `miniMAXUvozKnjigovodstvo.xsd` inside Projest.
4. **DDV-O UX parity** — control bar OK/Δ, JSON vs JSON+Minimax compare, Predogled/Izvoz PDF+XML (XSLT), Preračunaj, kontrolni pregled; Projest already has thinner `ui\ddvo_tab.py`.
5. **Org + account catalog** — `organisations` + `select_organisation` + cache `account_catalog` per company (KirKpr pattern in `company_profile` / `_set_account_catalog`).
6. **API predpreverjanje** — `validate_rows` / `preflight_row` before any write.
7. **Optional later** — virman/Outlook (`kirkpr_ddvo_virman.py`), eDavki envelope PDF (`kirkpr_ddvo_xml` + `kirkpr_ddvo_pdf`), Playwright PR opener.

### Patterns to copy (not path hacks)
- Shared settings file, secrets never in app config.
- Org ID from company registry, not free-typed in API tab.
- Catalogs loaded on connect and cached on company profile.
- Preflight builds payload (partners/accounts/VAT/balance/dedup) without POST; only “OK” rows submit.
- XSD validate on write (`write_and_validate`), balance check before schema.
- DDV-O verify = arithmetic `control_ok` + optional live Minimax invoice filter compare.
