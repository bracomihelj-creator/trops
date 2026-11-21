# Podagent: Explore KirKpr UI features

- **Projekt (Cursor):** `D:/PISARNA/Python/Projest`
- **ID pogovora:** `3b4d9030-9ee6-434d-8e64-68c7ec905bb2` (podagent pogovora `e771d261-8f34-4c57-91b0-480a379ad85e`)
- **Ustvarjen:** 2026-07-20 02:49  ·  **zadnja sprememba:** ?
- **Uporabnikovih sporočil v tej datoteki:** 1
- **Vir:** `%USERPROFILE%\.cursor\projects\d-PISARNA-Python-Projest\agent-transcripts\…\3b4d9030-9ee6-434d-8e64-68c7ec905bb2.jsonl`

> Izvoženo 21. 11. 2026 za združitev zgodovine v Trops_v5. Klici orodij so skrajšani na eno vrstico (vsebine datotek in izhodi ukazov niso vključeni). Morebitni ključi/gesla so zamenjani z [REDACTED].

## 👤 Uporabnik — Monday, Jul 20, 2026, 2:49 AM (UTC+2)

Thoroughly explore D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py (and related UI helpers if any) to document the GUI feature set that Projest Studio must match.

Focus on:
1. Main window layout (header, company selector, path panel, notebooks/tabs)
2. IR tab: tree columns, checkboxes (chk), filters, search/iskalnik, book selection (Darila/Fitness/etc), selection toolbar, account bar, editors, keyboard shortcuts
3. PR tab: same level of controls
4. How filters/search work (variables, methods like _apply_filter, _refresh_ir, status filters)
5. Checkbox column implementation if any (or selectmode extended)
6. Summary cards, navigation tree, company list
7. Method names and approximate line ranges for key UI builders and filter/search logic

Return a structured inventory:
- UI sections list
- For IR: every control + bound method
- For PR: every control + bound method  
- Filter/search logic summary with code snippets of the key filter predicates
- What data model fields drive book/chk/filter

Be concrete with method names and line numbers. Read enough of the file (it's large ~4500 lines). Also check kirkpr_minimax_core.py only if needed for book/filter concepts.

Working directory: D:\PISARNA\Python\KirKpr_convert

### 🤖 Asistent

I'll map the KirKpr convert GUI in depth—layout, IR/PR controls, filters, and the methods that wire them.

- 🔧 `UpdateCurrentStep`
- 🔧 `Glob` — **/*.{py,ui,json,md}
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py

- 🔧 `UpdateCurrentStep`
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py

The convert GUI looks simpler than expected—I'll check the core module and Projest for book filters, chk columns, and iskalnik.

- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert
- 🔧 `Grep` — D:\PISARNA\Python\Projest
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py

Confirming: Darila/Fitness and iskalnik aren't in the convert GUI—I'll finish mapping its real controls and note those gaps.

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Grep` — D:\PISARNA\Python\KirKpr_convert\kirkpr_minimax_core.py
- 🔧 `Grep` — D:\PISARNA\Python\Projest\projest.py

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\kirkpr_minimax_core.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `GetDynamicTools`

- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `Read` — D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py
- 🔧 `UpdateCurrentStep`

# KIR/KPR → Minimax Studio GUI inventory

Source: `D:\PISARNA\Python\KirKpr_convert\convert_KIrKpr_to_minimax.py` (app v2.19, `ConverterApp`). Helpers: `ToolTip` (L118–153), `kirkpr_company_registry`, `kirkpr_minimax_core`. No separate UI module.

**Important absences vs your focus list:** this GUI has **no** Darila/Fitness book picker, **no** `chk` checkbox column, **no** IR/PR iskalnik, and **no** methods named `_apply_filter` / `_refresh_ir`. Selection is `Treeview(selectmode="extended")`. Darila/Fitness belong to Projest Excel import (`projest.py` / `projest_studio`), not this convert app.

---

## 1. UI sections (main window)

| Section | Builder | Lines | Contents |
|---|---|---|---|
| Menu | `_build_menu` | 498–523 | Datoteka + Pomoč |
| Header | `_build_layout` | 529–555 | Title, subtitle, Odpri / Shrani delovno kopijo / Minimax API / Izvozi |
| Path / source card | `_build_layout` | 557–573 | Company label, source path, format/period/members, XSD badge |
| Summary cards | `_build_layout` + `_summary_card` | 575–580, 890–908 | IR count/net, PR count/net, KIR samoobdavčitev |
| Left navigation | `_build_navigation` | 621–672 | Company search + company tree + content nav tree |
| Notebook tabs | `_build_layout` | 596–611 | IR, PR, DDV-O, Minimax API |
| Status bar | `_build_layout` | 616–619 | `status_var` + shortcut hint |

Layout shell: `_build_layout` **525–619**. Paned workspace: `workspace_paned` **582–594**.

---

## 2. Company list + navigation tree

### Company search / list
- Entry `company_search_var` → `<KeyRelease>` → `_populate_company_tree` (**623–625**, **726–779**)
- Tree columns: `zst`, `name`, `org`; `selectmode="browse"` (**628–647**)
- Sort: `sort_company_tree` (**781–792**)
- Select: `_on_company_select` → `_activate_company` (**836–858**, **802–834**)

### Content nav tree
- Items: `nav:data` → `nav:ir` / `nav:pr` / `nav:ddvo`; `nav:minimax` → `nav:api`; `nav:output` → `nav:export` (**653–660**)
- Select: `_on_navigation_select` (**879–888**) — switches notebook or calls `export_files`
- Sync from tabs: `_on_tab_changed` (**1418–1428**)

---

## 3. IR tab — every control + bound method

Built by: `_build_ir_tree` **940–953** + `_build_ir_account_bar` **970–995**.

### Tree
| Control | Binding / method | Lines |
|---|---|---|
| Section title + yellow-row hint | (static labels) | 941–944 |
| `ir_tree` columns | see below | 945–948 |
| `<<TreeviewSelect>>` | `_on_ir_selection` | 949, 3570–3577 |
| `<Double-1>` | `_on_ir_double_click` → `open_ir_editor` | 950, 3579–3583 |
| `<Return>` | `open_ir_editor` | 951 |
| `<Control-a>` | `_select_all_ir` | 952, 3792–3794 |
| Column heading click | `_sort_tree` via `_make_tree` | 932 |

**IR columns** (headings):  
`zapst` Zap. št. · `date` Datum · `invoice` Listina · `party` Kupec · `tax_id` ID za DDV · `net` Neto · `vat` DDV · `gross` Skupaj · `account` Konto · `account_name` Naziv konta · `minimax_status` Status · `status` Obravnava

**Tags:** `odd`, `tax_only` (yellow KIR samoobdavčitev) — set in `_populate_trees` **1564–1578**.

**No chk column.** Selection = native multi-select (`selectmode="extended"` default in `_make_tree` **917**).

### Account / selection toolbar
| Control | Bound method | Lines |
|---|---|---|
| `ir_selection_var` label (“Izbranih IR: N”) | updated by `_on_ir_selection` | 973, 3572 |
| Label “Konto prihodka:” | — | 974 |
| `ir_account_combo` | `_configure_account_filter`; Enter → `apply_ir_account`; select → `_refresh_account_name_labels` | 975–979 |
| `ir_account_name_var` | `_refresh_account_name_labels` | 980, 406–408 |
| “Uporabi za izbrane” | `apply_ir_account` | 981–982, 3800–3837 |
| “Nastavi 7601” | `set_selected_ir_account("7601")` | 983–984, 3796–3798 |
| “Zapomni si za kupca” | `remember_customer_var` | 985 |
| “Uredi podatke” | `open_data_editor("IR")` | 989–990, 4099+ |
| “Odpri račun / popravi” | `open_ir_editor` | 987–988, 3585–3790 |
| “Shrani vse konte” | `save_accounts` | 986, 4345+ |

### Editors (modal)
- **Invoice editor** `open_ir_editor` **3585–3790**: account combo, description, remember-customer chk, document fields panel, Save temporary / Cancel; Esc / Ctrl+S / Ctrl+Return
- **Data editor** `open_data_editor("IR")` **4099–4260**: original vs working field grid

### Populate / row data
`_populate_trees` **1560–1599** — all `dataset.kir` rows (no book filter). Fields: `ZAPST`, `P2`, `P3`, `P5`, `P6DS`, metrics, `__konto__`, Minimax status, status text.

---

## 4. PR tab — every control + bound method

Built by: `_build_pr_tree` **955–968** + `_build_pr_account_bar` **997–1028**.

### Tree
| Control | Binding / method | Lines |
|---|---|---|
| Section title + hint | (static) | 956–959 |
| `pr_tree` columns | see below | 960–963 |
| `<<TreeviewSelect>>` | `_on_pr_selection` | 964, 3839–3846 |
| `<Double-1>` | `_on_pr_double_click` → `open_pr_editor` | 965, 3848–3852 |
| `<Return>` | `open_pr_editor` | 966 |
| `<Control-a>` | `_select_all_pr` | 967, 4262–4264 |

**PR columns:**  
`zapst` · `date` · `invoice` · `party` Dobavitelj · `tax_id` · `net` Osnova · `vat` Odbitni DDV · `gross` Obveznost · `account` · `account_name` · `self_tax` Samoobd. · `vat_deductible` DDV se odbija · `minimax_status` · `status` Vrsta

**Tags:** `vat_not_deducted`, `self_assessment`, `odd` — **1579–1596**.

### Account / selection toolbar
| Control | Bound method | Lines |
|---|---|---|
| `selection_var` (“Izbranih PR: N”) | `_on_pr_selection` | 1000, 3841 |
| “Konto:” + `account_combo` | `_configure_account_filter`; Enter → `apply_account` | 1001–1006 |
| `account_name_var` | `_refresh_account_name_labels` | 1007 |
| “Uporabi za izbrane” | `apply_account` | 1008–1009, 4306–4343 |
| “Nastavi 4190” | `set_selected_account("4190")` | 1010–1011, 4266–4268 |
| “DDV se odbija” | `set_selected_vat_deductible(True)` | 1012–1013, 4270–4303 |
| “DDV brez odbitka” | `set_selected_vat_deductible(False)` | 1014–1015 |
| “Zapomni si za dobavitelja” | `remember_supplier_var` | 1016 |
| “Uredi podatke” | `open_data_editor("PR")` | 1020–1021 |
| “Odpri račun / popravi” | `open_pr_editor` | 1018–1019, 3854–4097 |
| “Shrani vse konte” | `save_accounts` | 1017 |

### PR editor extras
`open_pr_editor` **3854–4097**: same as IR + checkboxes **Samoobdavčitev** / **DDV se odbija** → `__samoobdavcitev__`, `__ddv_se_odbija__`.

---

## 5. Filter / search logic (what actually exists)

There is **no** IR/PR row filter or iskalnik. Closest filters:

### A) Company search predicate (`_populate_company_tree` 732–744)

```python
query = re.sub(r"\s+", " ", self.company_search_var.get().strip().casefold())
haystack = " ".join((zst, name, tax_number, org_id)).casefold()
if query and any(term not in haystack for term in query.split()):
    continue  # hide company
```

### B) Account combobox filter (`_filtered_account_choices` 353–363; wired by `_configure_account_filter` 365–383)

```python
terms = self._account_search_value(query).split()
return tuple(
    label for label in choices
    if all(term in self._account_search_value(label) for term in terms)
)
```

`_account_search_value` normalizes (unicodedata / casefold) — **348–351**.

### C) API view filter (`set_api_view_filter` 2388–2400; applied in `_populate_api_tree` 2311–2336)

```python
if self.api_view_filter not in {"ALL", "IR"}:
    continue  # skip IR rows
# ...
if metrics["tax_only"]:
    continue  # never show tax-only KIR on API tab
# ...
if self.api_view_filter not in {"ALL", "PR"}:
    continue  # skip PR rows
```

Buttons: Vsi / Samo IR / Samo PR (**1264–1266**). State: `api_view_filter` ∈ `{ALL,IR,PR}`.

### D) IR “status” display (not a filter)
Derived in `_populate_trees`: `"Samoobdavčitev → PR"` if `core.ir_metrics(... )["tax_only"]` else `"Izvoz v IR"`. Summary card count uses `dataset_summary` which **excludes** tax-only from `ir_count` (core **909–922**).

---

## 6. Checkbox column vs selection

| Mechanism | Present? |
|---|---|
| Dedicated `chk` column | **No** |
| Treeview checkboxes | **No** |
| Multi-select | **Yes** — `selectmode="extended"` (`_make_tree` 917–921) |
| Select all | Ctrl+A → `_select_all_ir` / `_select_all_pr` |
| Boolean UI | Toolbar/editor Checkbuttons only (`remember_*`, PR samoobdavčitev / DDV se odbija) |

---

## 7. Summary cards, nav, company — method map

| Piece | Method | Lines |
|---|---|---|
| Card widget | `_summary_card` | 890–908 |
| Fill cards + tab titles | `_update_header_and_summary` | 1601–1621 |
| Metrics source | `core.dataset_summary` | core 909–922 |
| Company tree fill | `_populate_company_tree` | 726–779 |
| Nav width | `_apply_navigation_width`, `show_navigation_panel` | 678–724 |
| Tree helper | `_make_tree` | 910–938 |
| Sort any data tree | `_sort_tree` | 4517+ |

---

## 8. Global shortcuts (`_bind_shortcuts` 1357–1364)

| Key | Action |
|---|---|
| Ctrl+O | `choose_source` |
| Ctrl+L | `open_last_source` |
| Ctrl+S | `save_accounts` |
| Ctrl+Shift+S | `save_working_copy` |
| Ctrl+E | `export_files` |
| Ctrl+B | `show_navigation_panel` |
| F5 | `reload_source` |

Tree-local: Ctrl+A, Double-click, Return (IR/PR editors). Editor: Esc, Ctrl+S, Ctrl+Return.

---

## 9. Data model fields driving book / chk / filter

| Concept you asked about | In this app |
|---|---|
| Book Darila/Fitness | **N/A** — only IR (`dataset.kir`) vs PR (`dataset.kpr`); CSV `KNJIGA` maps to KIR/KPR in core, not sub-books |
| chk | **N/A** — selection state is Treeview selection; IID `ir:{index}` / `pr:{index}` |
| Filter | Company search; account combo; API `api_view_filter`; IR tax-only is display/tag only |
| Account | `__konto__` (default IR `7601`, PR `4190`) |
| Description | `__opis__` |
| PR VAT flags | `__samoobdavcitev__`, `__ddv_se_odbija__` (+ core `is_self_assessment` / `vat_is_deductible`) |
| IR tax-only | `core.ir_metrics` → `tax_only` / `kir_is_tax_only` (not a stored filter flag) |
| Party fields | IR `P5`/`P6DS`; PR `P6`/`P7DS` |
| Invoice key | `P3` (+ `core.row_key`) |
| Minimax status col | `_minimax_status_for_row` from API catalog / sent map |

---

## 10. Key UI builders — line index (for Projest Studio parity)

```
_configure_gui_style     417–496
_build_menu              498–523
_build_layout            525–619
_build_navigation        621–672
_summary_card            890–908
_make_tree               910–938
_build_ir_tree           940–953
_build_pr_tree           955–968
_build_ir_account_bar    970–995
_build_pr_account_bar    997–1028
_build_ddvo_tab          1030–1089
_build_api_tab           1091–1355
_bind_shortcuts          1357–1364
_populate_company_tree   726–779
_populate_trees          1560–1599
_update_header_and_summary 1601–1621
_configure_account_filter / _filtered_account_choices  353–383
set_api_view_filter / _populate_api_tree  2388–2400 / 2299–2366
open_ir_editor / open_pr_editor / open_data_editor  3585 / 3854 / 4099
```

---

## Parity takeaway for Projest Studio

Match this convert GUI’s **shell** (header, path card, 3 summary cards, left company+nav, IR/PR trees with account bars + editors, multi-select, shortcuts) and **working-row fields** (`__konto__`, `__opis__`, PR VAT flags). Do **not** expect to copy Darila/Fitness book chips, chk columns, or IR/PR iskalnik from this file — they are Projest-domain features to design separately if still required.
