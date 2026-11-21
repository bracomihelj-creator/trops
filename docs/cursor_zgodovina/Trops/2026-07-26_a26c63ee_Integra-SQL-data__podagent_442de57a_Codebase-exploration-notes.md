# Podagent: Codebase exploration notes

- **Projekt (Cursor):** `D:/PISARNA/Python/Trops`
- **ID pogovora:** `442de57a-9cce-43ad-9de0-c8d35b8f5410` (podagent pogovora `a26c63ee-b07f-4640-8b56-08158b973f17`)
- **Ustvarjen:** 2026-07-26 11:58  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Trops\agent-transcripts\…\442de57a-9cce-43ad-9de0-c8d35b8f5410.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Sunday, Jul 26, 2026, 11:58 AM (UTC+2)

Explore D:\PISARNA\Python\Trops codebase for:
1. How minimax_accounts and account_rules / kont_map are stored in db.py
2. Current _TROPS_TO_MINIMAX and coerce_minimax_bookable_account in account_choices.py
3. How Integra IR/PR transfer and Vse knjižbe work (integra_irpr.py, vse_knjizbe_tab.py)
4. Existing dialog patterns in trops_studio/ui/ (simple Toplevel dialogs to copy style from)
5. Whether there's already any account mapping UI

Return: schema snippets for relevant tables, best place to store persistent Trops→Minimax mappings, dialog style notes, and call sites where validation should run (after kisanal import, before/after Prenos v IR/PR, on Vse knjižbe refresh).

Be quick/medium thorough.

### 🤖 Asistent

I'll explore the codebase for account storage, mapping logic, IR/PR transfer flow, and existing dialog patterns.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/db.py
- 🔧 `Glob` — **/account_choices.py
- 🔧 `Glob` — **/integra_irpr.py
- 🔧 `Glob` — **/vse_knjizbe_tab.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\account_choices.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\integra_kisanal.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio
- 🔧 `Glob` — **/ui/*dialog*.py

- 🔧 `UpdateCurrentStep`
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\integra_irpr.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\integra_irpr.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\vse_knjizbe_tab.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\progress_dialog.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\party_web_results_dialog.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\nove_firme_dialog.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\integra_irpr.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\accounts.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\integra_dialog.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\integra_dialog.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\db.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\konti_tab.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio\ui

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\account_choices.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\integra_kisanal.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\missing_pr_parties_dialog.py
- 🔧 `Grep` — D:\PISARNA\Python\Trops\trops_studio
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\vse_knjizbe_tab.py

- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\account_choices.py
- 🔧 `Read` — D:\PISARNA\Python\Trops\trops_studio\ui\pr_editor.py
- 🔧 `CallDynamicTool`

## 1. DB storage (three different things)

**Same company SQLite** (`company_db_path`, e.g. Integra org 20): Studio schema from `db.py` + Integra tables from `integra_kisanal.py`.

### `minimax_accounts` — Minimax chart (bookable filter)
```185:198:D:\PISARNA\Python\Trops\trops_studio\db.py
CREATE TABLE IF NOT EXISTS minimax_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL DEFAULT '',
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    minimax_id TEXT NOT NULL DEFAULT '',
    allowed_posting TEXT NOT NULL DEFAULT '',
    application TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'minimax',
    updated_at TEXT NOT NULL,
    UNIQUE(org_id, code)
);
```
- Filled by API pull (`replace_minimax_accounts`). Choices = `AllowedPosting ≠ N`.

### `account_rules` — per-party templates (not Trops→MM aliases)
```54:73:D:\PISARNA\Python\Trops\trops_studio\db.py
CREATE TABLE IF NOT EXISTS account_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    party_kind TEXT NOT NULL DEFAULT 'supplier',
    match_vat / match_tax / match_name,
    odhodek01/07/10/11, odhodek_excluded, placilo, prihodek,
    self_assessment, vat_deductible, active, source, notes, updated_at
);
```
- Supplier/customer defaults + history learning — **not** Trops code remapping.

### `kont_map` — Integra OLDSIFRA → KONTCTRL (DBF), not Minimax
```31:38:D:\PISARNA\Python\Trops\trops_studio\integra_kisanal.py
CREATE TABLE IF NOT EXISTS kont_map (
    old_sifra TEXT NOT NULL PRIMARY KEY,
    new_konto TEXT NOT NULL,
    old_naziv / new_naziv / source / year
);
```
- Rewritten on every `urejanje_kisanal_to_sqlite`; applied to `kisanal.anal_akon` at import.

---

## 2. Current Trops→Minimax logic

Hardcoded only in `account_choices.py`:

| Trops | Minimax |
|-------|---------|
| 7622 | 7620 |
| 7409 | 7400 |
| 4061→4199 (PR) | 4060/4070/4190/4150… |
| 6526/6527/660/66 | 6500 |

`coerce_minimax_bookable_account`: try `raw → base → alias → sibling(*1→*0) → fallback` against `minimax_account_codes` (bookable set). Fallback IR: `7620`.

---

## 3. IR/PR transfer & Vse knjižbe

**Import:** `IntegraDialog.urejanje_kisanal_sqlite` → `urejanje_kisanal_to_sqlite` (POPA + KISANAL + `kont_map`).

**Prenos:** `VseKnjizbeTab.transfer_to_ir_pr` → `import_kisanal_to_ir_pr`:
- Groups: IR=`100*`/`120*`, PR=`220*`, BD=`BOD*`/`110*`
- Coerce on IR `account`, PR `odhodek01`/`odhodek10`/`placilo` inside `_build_ir_from_group` / `_build_pr_from_group`
- Also `resolve_ir_account` → coerce

**Vse knjižbe refresh:** reads `kisanal` for period; marks transferred via `notes`/`raw_json` `kisanal:`; **no** account validation today.

---

## 4. Dialog style (copy these)

Common pattern (`NoveFirmeDialog`, `PartyWebResultsDialog`, `_PickDialog`, `MissingJournalPartiesDialog`):
- `tk.Toplevel` + `transient` + `grab_set`
- `ttk.Frame` padding `(12,…)`
- Muted subtitle labels, action bar, `Treeview` + scroll
- `Accent.TButton` / `Success.TButton`, `ToolTip`, `messagebox` with `parent=self`
- Best small templates: `_PickDialog` in `integra_dialog.py`, `PartyWebResultsDialog`, `ProgressDialog`

---

## 5. Account mapping UI?

**None.** No Trops→Minimax mapping editor. Related but different:
- File menu: sync Minimax chart → SQL
- IR/PR editors: validate bookable codes on save
- `KontiTab`: pivot analytics, not mapping

---

## Best place for persistent Trops→Minimax mappings

**New table in company SQLite via `db.py` SCHEMA**, e.g. `trops_minimax_account_map(trops_code PK, minimax_code, notes, updated_at)` — same DB as `minimax_accounts`, org-scoped if needed.

Do **not** reuse:
- `kont_map` (Integra DBF remap, wiped on import)
- `account_rules` (party templates)

Wire: load into/override `_TROPS_TO_MINIMAX` inside `coerce_minimax_bookable_account` (keep hardcoded as seed/defaults).

---

## Validation call sites

| When | Where | Why |
|------|--------|-----|
| After kisanal import | End of `urejanje_kisanal_to_sqlite` / `IntegraDialog.urejanje_kisanal_sqlite` | Distinct `anal_akon` not bookable / unmapped |
| Before Prenos | Start of `VseKnjizbeTab.transfer_to_ir_pr` (or start of `import_kisanal_to_ir_pr`) | Block/warn before writing IR/PR |
| During Prenos | Already: coerce in `_build_ir_*` / `_build_pr_*` | Soft remap; add hard fail if still unbookable |
| After Prenos | After `import_kisanal_to_ir_pr` returns | Spot-check written IR/PR accounts |
| Vse knjižbe refresh | End of `VseKnjizbeTab.refresh` | Flag rows whose `anal_akon` needs mapping (status column / info_var) |
