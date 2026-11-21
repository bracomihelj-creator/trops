/* Trops Studio 5.1.00 — spletni vmesnik (WebView2). Vse poslovne akcije gredo prek /api/* v host.py. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ stanje
  var S = {
    boot: null, view: "ir", rows: {}, sort: {}, limit: {}, search: {}, companies: [],
    ddvo: null, busy: false,
  };
  var STATUSES = [["VSI", "Vsi statusi"], ["OSNUTEK", "Osnutek"], ["Popravi", "Popravi"], ["Popravljeno", "Popravljeno"],
    ["Shranjeno", "Shranjeno"], ["Manjka konto", "Manjka konto"], ["PRIPRAVLJEN", "Pripravljen"], ["Poglej", "Poglej"]];
  var PAGE = 400;

  function $(id) { return document.getElementById(id); }
  function qa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function icon(name, cls) { return "<svg" + (cls ? " class='" + cls + "'" : "") + "><use href='#i-" + name + "'/></svg>"; }
  function errText(r) { return (r && (r.error || r.msg || r.message)) || "Neznana napaka."; }
  function okText(r, fallback) { return (r && (r.msg || r.message)) || fallback || "Končano."; }
  function num(v) {
    if (v == null || v === "") return 0;
    if (typeof v === "number") return v;
    var s = String(v).trim().replace(/\s/g, "");
    if (/,\d{1,2}$/.test(s) || /\.\d{3},/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
    var n = parseFloat(s);
    return isNaN(n) ? 0 : n;
  }
  function money(v) {
    var n = num(v), neg = n < 0;
    var parts = Math.abs(n).toFixed(2).split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return (neg ? "-" : "") + parts[0] + "," + parts[1];
  }
  var CADENCE = { monthly: "mesečno", quarterly: "četrtletno", yearly: "letno" };
  function siDate(v) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(v || ""));
    return m ? m[3] + "." + m[2] + "." + m[1] : (v || "");
  }

  // ------------------------------------------------------------------ API
  function api(path, opt) {
    return fetch(path, Object.assign({ credentials: "same-origin" }, opt || {})).then(function (r) {
      return r.text().then(function (text) {
        var data;
        try { data = JSON.parse(text); } catch (_e) { data = { ok: false, error: text || r.statusText }; }
        if (!r.ok) { data = data || {}; data.ok = false; data.error = data.error || data.msg || ("HTTP " + r.status); }
        if (data && data.ok === false && !data.error) data.error = data.msg || data.message || "Napaka.";
        return data;
      });
    });
  }
  function post(path, body) {
    return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  }
  function act(name, extra) { return post("/api/action", Object.assign({ name: name }, extra || {})); }

  // ------------------------------------------------------------------ toasti / status
  function toast(msg, kind, ms) {
    kind = kind || "ok";
    var el = document.createElement("div");
    el.className = "toast " + kind;
    var ic = kind === "error" ? "alert" : kind === "warn" ? "alert" : kind === "info" ? "info" : "check";
    el.innerHTML = icon(ic) + "<div>" + esc(msg) + "</div><button class='x' title='Zapri'>×</button>";
    el.querySelector(".x").onclick = function () { el.remove(); };
    $("toasts").appendChild(el);
    setTimeout(function () { if (el.parentNode) el.remove(); }, ms || (kind === "error" ? 9000 : 4500));
  }
  function status(msg, kind) {
    $("statusText").textContent = msg || "";
    $("statusDot").className = "dot" + (kind === "busy" ? " busy" : kind === "error" ? " err" : "");
  }
  function report(res, okMsg) {
    if (!res || res.ok === false) { toast(errText(res), "error"); status(errText(res), "error"); return false; }
    toast(okText(res, okMsg), "ok"); status(okText(res, okMsg)); return true;
  }
  function withBusy(btn, promise) {
    if (btn) { btn.classList.add("busy"); btn.disabled = true; }
    return Promise.resolve(promise).finally(function () { if (btn) { btn.classList.remove("busy"); btn.disabled = false; } });
  }

  // ------------------------------------------------------------------ modal
  var modalResolve = null;
  function modal(o) {
    $("modalTitle").textContent = o.title || "";
    $("modalBody").innerHTML = o.html || "";
    var foot = $("modalFoot"); foot.innerHTML = "";
    var m = document.querySelector(".modal"); m.className = "modal" + (o.wide ? " wide" : "");
    (o.buttons || [{ label: "Zapri", kind: "primary" }]).forEach(function (b) {
      var btn = document.createElement("button");
      btn.className = "btn " + (b.kind || "");
      btn.innerHTML = (b.icon ? icon(b.icon) : "") + esc(b.label);
      if (b.id) btn.id = b.id;
      btn.onclick = function () {
        var r = b.onClick ? b.onClick(btn) : undefined;
        if (r === false) return;
        closeModal(b.value);
      };
      foot.appendChild(btn);
    });
    $("modal").hidden = false;
    var first = $("modalBody").querySelector("input:not([disabled]),select,textarea");
    if (first) setTimeout(function () { first.focus(); }, 30);
    return new Promise(function (res) { modalResolve = res; });
  }
  function closeModal(value) {
    $("modal").hidden = true;
    var r = modalResolve; modalResolve = null;
    if (r) r(value);
  }
  function confirmDialog(o) {
    var html = "<div class='confirmBox'><div class='ic" + (o.danger ? " bad" : "") + "'>" + icon(o.icon || "alert") + "</div><div>" + (o.html || "") + "</div></div>";
    return modal({
      title: o.title, html: html, wide: o.wide,
      buttons: [{ label: "Prekliči", value: false }, { label: o.ok || "Potrdi", kind: o.danger ? "danger" : "primary", value: true, onClick: o.validate }],
    }).then(function (v) { return v === true; });
  }

  // ------------------------------------------------------------------ ozadne naloge
  function runJob(name, body, label) {
    if (S.busy) { toast("Druga naloga še teče.", "warn"); return Promise.resolve({ ok: false, error: "Zasedeno" }); }
    S.busy = true;
    $("job").hidden = false;
    $("jobTitle").textContent = label || "Delam…";
    $("jobMsg").textContent = "Začenjam…";
    $("jobBar").className = "indet"; $("jobBar").style.width = "";
    status(label || "Delam…", "busy");
    $("btnSync").disabled = true;
    return act(name, body).then(function (start) {
      if (!start || start.ok === false || !start.job_id) return start;
      return new Promise(function (resolve) {
        (function poll() {
          api("/api/job?id=" + encodeURIComponent(start.job_id)).then(function (j) {
            if (j && j.state === "running") {
              $("jobMsg").textContent = j.message || "";
              if (j.total > 0) { $("jobBar").className = ""; $("jobBar").style.width = Math.min(100, Math.round(100 * j.current / j.total)) + "%"; }
              setTimeout(poll, 600);
              return;
            }
            var res = (j && j.result) || {};
            if (!j || j.ok === false || j.state === "error") { res = Object.assign({}, res, { ok: false, error: (j && (j.error || j.message)) || errText(res) }); }
            resolve(res);
          }).catch(function (e) { resolve({ ok: false, error: String(e) }); });
        })();
      });
    }).finally(function () {
      S.busy = false; $("job").hidden = true; $("btnSync").disabled = false;
    });
  }

  // ------------------------------------------------------------------ datoteke (pywebview Bridge)
  function bridge() { return window.pywebview && window.pywebview.api; }
  function manualPath(title, hint) {
    var html = "<p>" + esc(hint || "Vnesi polno pot do datoteke.") + "</p><label class='fld'><span>Pot</span><input id='mPath' placeholder='D:\\Trops\\…'></label>";
    return modal({ title: title, html: html, buttons: [{ label: "Prekliči", value: "" }, { label: "Uporabi", kind: "primary", onClick: function () { closeModal($("mPath").value.trim()); return false; } }] })
      .then(function (v) { return v || ""; });
  }
  function pickFile(kinds, title) {
    var b = bridge();
    if (b && b.pick_file) return b.pick_file(kinds || null).then(function (p) { return p || ""; });
    return manualPath(title || "Izberi datoteko", "Sistemski izbirnik je na voljo samo v aplikaciji (WebView2).");
  }
  function pickExcelMulti() {
    var b = bridge();
    if (b && b.pick_excel_multi) return b.pick_excel_multi().then(function (p) { return p || []; });
    return manualPath("Vasco datoteke", "Vnesi poti, ločene s podpičjem (IF* = IR, kp* = PR).").then(function (v) {
      return v ? v.split(";").map(function (x) { return x.trim(); }).filter(Boolean) : [];
    });
  }
  function pickFolder() {
    var b = bridge();
    if (b && b.pick_folder) return b.pick_folder().then(function (p) { return p || ""; });
    return manualPath("Izberi mapo", "Vnesi polno pot do mape.");
  }
  function openPath(path) {
    if (!path) return;
    act("open_path", { path: path }).then(function (r) { if (r.ok === false) toast(errText(r), "warn"); });
  }

  // ------------------------------------------------------------------ boot, podjetje, obdobje
  function applyBoot(data) {
    if (!data || data.ok === false) { if (data) toast(errText(data), "error"); return; }
    S.boot = data;
    var c = data.company || {};
    $("brandVer").textContent = "Verzija " + (data.version || "5.1.00");
    $("companyName").textContent = c.zst ? (c.zst + " · " + (c.name || "")) : "Izberi podjetje";
    var p = data.period || {};
    $("periodLbl").textContent = p.label ? (p.label + " " + (p.year || "")) : "Obdobje";
    $("periodRange").textContent = (p.from_si || siDate(p.from) || "—") + " – " + (p.to_si || siDate(p.to) || "—");
    $("periodFrom").value = p.from || ""; $("periodTo").value = p.to || "";
    $("periodYear").value = p.year || new Date().getFullYear();
    var ch = $("periodChoice");
    if (!ch.options.length) (p.choices || []).forEach(function (x) { var o = document.createElement("option"); o.value = x; o.textContent = x; ch.appendChild(o); });
    if (p.label) ch.value = p.label;
    var s = data.summary || {};
    $("navCntIr").textContent = s.ir_count || ""; $("navCntPr").textContent = s.pr_count || ""; $("navCntParties").textContent = s.parties || "";
    $("dbPath").textContent = c.db_path ? ("Baza: " + c.db_path) : "";
    var al = $("alerts"); al.innerHTML = "";
    (data.warnings || []).forEach(function (w) { al.insertAdjacentHTML("beforeend", "<div class='alert warn'>" + icon("alert") + esc(w) + "</div>"); });
    if (!c.key && (data.companies || []).length) al.insertAdjacentHTML("beforeend", "<div class='alert warn'>" + icon("building") + "Najprej izberi podjetje (zgoraj desno).</div>");
    status(data.status || "Pripravljeno.");
  }
  function afterChange(data) { applyBoot(data); return loadView(S.view); }

  function loadCompanies() {
    var q = encodeURIComponent(($("companySearch").value || "").trim());
    return api("/api/companies?q=" + q).then(function (data) {
      S.companies = (data && data.rows) || [];
      var warn = $("companyWarn");
      var w = data && data.ok === false ? errText(data) : (data && data.warning) || "";
      warn.hidden = !w; warn.textContent = w;
      var key = S.boot && S.boot.company && S.boot.company.key;
      $("companyList").innerHTML = S.companies.length ? S.companies.map(function (r, i) {
        return "<button class='companyItem" + (r.key === key ? " active" : "") + "' data-i='" + i + "'><span class='zst'>" + esc(r.zst) + "</span><span><b>" + esc(r.name) +
          "</b><br><small>" + esc(r.source_kind || "") + (r.tax ? " · " + esc(r.tax) : "") + "</small></span><small>Org " + esc(r.org || "—") + "</small></button>";
      }).join("") : "<div class='empty'>" + icon("building") + "<div>Ni podjetij.</div></div>";
      qa(".companyItem", $("companyList")).forEach(function (b) {
        b.onclick = function () { $("companyPop").hidden = true; selectCompany(S.companies[+b.getAttribute("data-i")]); };
      });
    });
  }
  function selectCompany(row) {
    status("Nalagam podjetje…", "busy");
    return post("/api/company/select", { key: row.key, zst: row.zst, name: row.name, org: row.org })
      .then(function (d) { if (d.ok === false) { toast(errText(d), "error"); return; } S.rows = {}; return afterChange(d); });
  }
  function applyPeriod(body) {
    return post("/api/period", body).then(function (d) {
      if (d.ok === false) { toast(errText(d), "error"); return; }
      $("periodPop").hidden = true; S.rows = {}; return afterChange(d);
    });
  }

  // ------------------------------------------------------------------ tabela
  function badgeFor(v) {
    var t = String(v == null ? "" : v);
    var k = t.toLowerCase();
    var cls = /^(synced|shranjeno|ok|potrjen|najden|pripravljen)/.test(k) ? "good"
      : /^(ready|popravljeno|info)/.test(k) ? "info"
      : /(error|napaka|neveljav|manjka|^popravi$|ni najden)/.test(k) ? "bad"
      : /^(osnutek|local|poglej|pregled)/.test(k) ? "warn" : "neutral";
    var labels = { local: "lokalno", ready: "pripravljeno", synced: "v Minimaxu", error: "napaka" };
    return t ? "<span class='badge " + cls + "'>" + esc(labels[k] || t) + "</span>" : "";
  }
  function cell(c, r) {
    var v = r[c.key];
    if (c.fmt === "badge") return badgeFor(v);
    if (c.fmt === "money") return esc(v == null || v === "" ? "" : money(v));
    if (c.fmt === "date") return esc(siDate(v));
    return esc(v == null ? "" : v);
  }
  function sortRows(view, rows, cols) {
    var st = S.sort[view];
    if (!st) return rows;
    var col = cols.filter(function (c) { return c.key === st.key; })[0] || {};
    var numeric = col.num || col.fmt === "money";
    return rows.slice().sort(function (a, b) {
      var x = a[st.key], y = b[st.key], r;
      if (numeric) r = num(x) - num(y);
      else r = String(x == null ? "" : x).localeCompare(String(y == null ? "" : y), "sl", { numeric: true });
      return st.dir * r;
    });
  }
  function clientFilter(rows, q) {
    q = (q || "").trim().toLowerCase();
    if (!q) return rows;
    var terms = q.split(/\s+/);
    return rows.filter(function (r) {
      var hay = Object.keys(r).map(function (k) { return k === "raw_json" ? "" : r[k]; }).join(" ").toLowerCase();
      return terms.every(function (t) { return hay.indexOf(t) >= 0; });
    });
  }
  function renderTable(o) {
    var view = o.view, cols = o.cols;
    var rows = sortRows(view, o.rows || [], cols);
    var lim = S.limit[view] || PAGE;
    var shown = rows.slice(0, lim);
    var st = S.sort[view] || {};
    if (!rows.length) {
      $("content").innerHTML = "<div class='card'><div class='empty'>" + icon(o.emptyIcon || "list") + "<div>" + esc(o.empty || "Ni vrstic za izbrano obdobje.") + "</div></div></div>";
      if (o.kind) updateSelInfo(o.kind);
      return;
    }
    var isNum = function (c) { return c.num || c.fmt === "money"; };
    var head = "<tr>" + (o.kind ? "<th class='c'><input type='checkbox' id='chkHead' title='Označi vse vidne'></th>" : "") +
      cols.map(function (c) {
        return "<th class='sortable" + (isNum(c) ? " num" : "") + (st.key === c.key ? " sorted" : "") + "' data-k='" + esc(c.key) + "' title='Razvrsti: " + esc(c.label) + "'>" +
          esc(c.label) + "<span class='arr'>" + (st.key === c.key ? (st.dir > 0 ? "▲" : "▼") : "↕") + "</span></th>";
      }).join("") + "</tr>";
    var body = shown.map(function (r) {
      var sel = o.kind && r.checked;
      return "<tr data-id='" + esc(r.id) + "' class='" + (sel ? "sel " : "") + (r._warn ? "warnRow" : "") + "'>" +
        (o.kind ? "<td class='c'><input type='checkbox' class='rowChk'" + (sel ? " checked" : "") + "></td>" : "") +
        cols.map(function (c) { return "<td" + (isNum(c) ? " class='num'" : "") + " title='" + esc(r[c.key]) + "'>" + cell(c, r) + "</td>"; }).join("") + "</tr>";
    }).join("");
    var foot = "";
    if (o.totals) {
      foot = "<tfoot><tr>" + (o.kind ? "<td></td>" : "") + cols.map(function (c, i) {
        if (i === 0) return "<td>Σ " + rows.length + "</td>";
        if (o.totals.indexOf(c.key) >= 0) return "<td class='num'>" + money(rows.reduce(function (a, r) { return a + num(r[c.key]); }, 0)) + "</td>";
        return "<td></td>";
      }).join("") + "</tr></tfoot>";
    }
    var more = rows.length > shown.length ? "<div class='more'><button class='btn sm' id='btnMore'>Prikaži vse (" + rows.length + ")</button> <span class='muted small'>prikazano " + shown.length + "</span></div>" : "";
    $("content").innerHTML = "<div class='card'><div class='tableWrap'><table class='grid'><thead>" + head + "</thead><tbody>" + body + "</tbody>" + foot + "</table></div>" + more + "</div>";
    qa("th.sortable", $("content")).forEach(function (th) {
      th.onclick = function () {
        var k = th.getAttribute("data-k"); var cur = S.sort[view];
        S.sort[view] = { key: k, dir: cur && cur.key === k ? -cur.dir : 1 };
        renderTable(o);
      };
    });
    if ($("btnMore")) $("btnMore").onclick = function () { S.limit[view] = rows.length; renderTable(o); };
    if (o.kind) bindSelection(o, shown);
    if (o.onDbl) qa("tbody tr", $("content")).forEach(function (tr) {
      tr.ondblclick = function () { o.onDbl(tr.getAttribute("data-id")); };
    });
  }
  function rowById(kind, id) { return (S.rows[kind] || []).filter(function (r) { return String(r.id) === String(id); })[0]; }
  function selectedIds(kind) { return (S.rows[kind] || []).filter(function (r) { return r.checked; }).map(function (r) { return r.id; }); }
  function updateSelInfo(kind) {
    var n = selectedIds(kind).length;
    var el = $("selInfo"); if (el) el.textContent = n ? ("Označenih: " + n) : "";
    qa("[data-needsel]").forEach(function (b) { b.disabled = !n; });
  }
  function bindSelection(o, shown) {
    var kind = o.kind;
    qa("tbody tr", $("content")).forEach(function (tr) {
      var chk = tr.querySelector(".rowChk");
      chk.onclick = function (e) { e.stopPropagation(); };
      chk.onchange = function () {
        var r = rowById(kind, tr.getAttribute("data-id")); if (r) r.checked = chk.checked;
        tr.classList.toggle("sel", chk.checked);
        act("set_chk", { kind: kind, id: tr.getAttribute("data-id"), checked: chk.checked }).then(function (res) { if (res.ok === false) toast(errText(res), "error"); });
        updateSelInfo(kind);
      };
    });
    var head = $("chkHead");
    if (head) head.onchange = function () { setAll(kind, head.checked, shown.map(function (r) { return r.id; })); };
    updateSelInfo(kind);
  }
  function setAll(kind, on, ids) {
    var idset = ids ? ids.map(String) : null;
    (S.rows[kind] || []).forEach(function (r) { if (!idset || idset.indexOf(String(r.id)) >= 0) r.checked = on; });
    qa("tbody tr", $("content")).forEach(function (tr) {
      var r = rowById(kind, tr.getAttribute("data-id")); var c = tr.querySelector(".rowChk");
      if (r && c) { c.checked = !!r.checked; tr.classList.toggle("sel", !!r.checked); }
    });
    updateSelInfo(kind);
    return act("set_chk_all", { kind: kind, checked: on, ids: ids || null }).then(function (res) { if (res.ok === false) toast(errText(res), "error"); });
  }

  // ------------------------------------------------------------------ KPI / orodna vrstica
  function kpis(list) {
    $("kpis").innerHTML = (list || []).map(function (k) {
      return "<div class='kpi " + (k.cls || "") + "'><div class='lbl'>" + esc(k.lbl) + "</div><div class='val'>" + esc(k.val) + "</div>" + (k.sub ? "<div class='sub'>" + esc(k.sub) + "</div>" : "") + "</div>";
    }).join("");
  }
  function toolbar(html) { $("toolbar").innerHTML = html || ""; }
  function loading() { $("content").innerHTML = "<div class='card'><div class='loading'><span class='spinner'></span>Nalagam…</div></div>"; }
  function searchBox(id, ph, val) { return "<div class='searchBox'>" + icon("search") + "<input id='" + id + "' placeholder='" + esc(ph) + "' value='" + esc(val || "") + "' autocomplete='off'></div>"; }
  function debounce(fn, ms) { var t; return function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, ms || 250); }; }

  // ------------------------------------------------------------------ IR / PR
  var IR_COLS = [
    { key: "seq", label: "Zap.", num: true }, { key: "book", label: "Knjiga" }, { key: "document_date", label: "Datum", fmt: "date" },
    { key: "document_no", label: "Listina" }, { key: "party_name", label: "Kupec" }, { key: "vat_id", label: "ID za DDV" },
    { key: "net", label: "Osnova", fmt: "money" }, { key: "vat_total", label: "DDV", fmt: "money" }, { key: "total", label: "Skupaj", fmt: "money" },
    { key: "account", label: "Konto" }, { key: "status", label: "Status", fmt: "badge" }, { key: "sync_status", label: "Minimax", fmt: "badge" },
  ];
  var PR_COLS = [
    { key: "seq", label: "Zap.", num: true }, { key: "received_date", label: "Prejeto", fmt: "date" }, { key: "document_no", label: "Listina" },
    { key: "internal_no", label: "Interna" }, { key: "supplier_name", label: "Dobavitelj" }, { key: "vat_id", label: "ID za DDV" },
    { key: "osnova", label: "Osnova", fmt: "money" }, { key: "vat_total", label: "DDV", fmt: "money" }, { key: "odhodek_display", label: "Odhodek" },
    { key: "region_label", label: "Regija" }, { key: "status", label: "Status", fmt: "badge" }, { key: "sync_status", label: "Minimax", fmt: "badge" },
  ];
  function prepIr(r) { r.vat_total = num(r.vat_22) + num(r.vat_95); return r; }
  function prepPr(r) {
    r.osnova = num(r.p8_display || r.osnova_display || r.net_taxable);
    r.vat_total = num(r.vat_22) + num(r.vat_95) + num(r.vat_5);
    r._warn = !!r.si_vat_err;
    return r;
  }
  function setFilter(filters) {
    return post("/api/filters", { filters: filters }).then(function (r) {
      if (r.ok === false) { toast(errText(r), "error"); return; }
      if (S.boot) { S.boot.filters = r.filters; S.boot.ir_books = r.ir_books; }
      return reloadDocs(S.view === "pr" ? "PR" : "IR");
    });
  }
  function docToolbar(kind) {
    var f = (S.boot && S.boot.filters) || {};
    var stKey = kind === "IR" ? "ir_status" : "pr_status";
    var key = kind === "IR" ? "ir_search" : "pr_search";
    var books = "";
    if (kind === "IR" && S.boot && S.boot.ir_books) {
      books = "<div class='chips' title='Knjige IR'>" + Object.keys(S.boot.ir_books).map(function (b) {
        return "<button class='chip" + (S.boot.ir_books[b] ? " on" : "") + "' data-book='" + esc(b) + "'>" + esc(b) + "</button>";
      }).join("") + "</div><span class='divider'></span>";
    }
    toolbar(
      searchBox("viewSearch", kind === "IR" ? "Išči listino, kupca, ID za DDV…" : "Išči listino, dobavitelja, interno…", f[key]) +
      "<label class='fld'><select id='statusFilter' title='Filter statusa'>" + STATUSES.map(function (s) { return "<option value='" + esc(s[0]) + "'" + (f[stKey] === s[0] ? " selected" : "") + ">" + esc(s[1]) + "</option>"; }).join("") + "</select></label>" +
      books +
      "<button class='btn sm' data-t='all'>" + icon("check") + "Vse označi</button><button class='btn sm' data-t='none'>Odznači</button>" +
      "<span class='selInfo' id='selInfo'></span><span class='grow'></span>" +
      "<button class='btn sm' data-t='add'>" + icon("plus") + "Dodaj</button>" +
      "<button class='btn sm' data-t='edit' data-needsel>" + icon("edit") + "Uredi</button>" +
      "<button class='btn sm' data-t='account' data-needsel>" + icon("tag") + "Konto…</button>" +
      "<button class='btn sm' data-t='delete' data-needsel>" + icon("trash") + "Izbriši</button>" +
      "<button class='btn sm primary' data-t='confirm' data-needsel>" + icon("check") + "4 · Potrdi</button>" +
      "<button class='btn sm' data-t='sync'>" + icon("sync") + "Sync " + kind + "</button>"
    );
    $("viewSearch").oninput = debounce(function () { var x = {}; x[key] = $("viewSearch").value; setFilter(x); }, 300);
    $("statusFilter").onchange = function () { var x = {}; x[stKey] = $("statusFilter").value; setFilter(x); };
    qa("[data-book]").forEach(function (b) {
      b.onclick = function () {
        var bk = {}; bk[b.getAttribute("data-book")] = !b.classList.contains("on");
        b.classList.toggle("on");
        setFilter({ ir_books: bk });
      };
    });
    qa("[data-t]", $("toolbar")).forEach(function (b) { b.onclick = function () { docAction(kind, b.getAttribute("data-t"), b); }; });
  }
  function docAction(kind, t, btn) {
    var ids = selectedIds(kind);
    if (t === "all") return setAll(kind, true, (S.rows[kind] || []).map(function (r) { return r.id; }));
    if (t === "none") return setAll(kind, false, null);
    if (t === "add") return openEditor(kind, null);
    if (t === "edit") { if (ids.length !== 1) return toast("Za urejanje označi natanko eno vrstico (ali jo dvokliknij).", "warn"); return openEditor(kind, ids[0]); }
    if (t === "account") return accountDialog(kind, ids);
    if (t === "delete") {
      return confirmDialog({ title: "Izbriši vrstice", danger: true, ok: "Izbriši", icon: "trash", html: "<p>Izbrišem <b>" + ids.length + "</b> označenih " + kind + " vrstic iz lokalne baze?</p><p class='muted'>Minimax se ne spremeni.</p>" })
        .then(function (yes) { if (yes) return withBusy(btn, act("delete_rows", { kind: kind, ids: ids }).then(function (r) { report(r); refreshAfter(); })); });
    }
    if (t === "confirm") return withBusy(btn, act("confirm", { kind: kind, ids: ids }).then(function (r) { report(r); refreshAfter(); }));
    if (t === "sync") return syncDialog(kind);
  }
  function refreshAfter() { return act("refresh").then(function (d) { applyBoot(d); return loadView(S.view, true); }); }

  function docKpis(kind, rows, t) {
    var synced = rows.filter(function (r) { return r.sync_status === "synced"; }).length;
    if (kind === "IR") return kpis([
      { lbl: "Izdani računi", val: String(rows.length), sub: "v obdobju (po filtrih)", cls: "info" },
      { lbl: "Osnova", val: money(rows.reduce(function (a, r) { return a + num(r.net); }, 0)) + " €" },
      { lbl: "Izstopni DDV", val: money(rows.reduce(function (a, r) { return a + r.vat_total; }, 0)) + " €", cls: "warn" },
      { lbl: "Skupaj", val: ((t && t.value) || money(rows.reduce(function (a, r) { return a + num(r.total); }, 0))) + " €", cls: "good" },
      { lbl: "V Minimaxu", val: synced + " / " + rows.length, sub: "sinhronizirano" },
    ]);
    var warn = rows.filter(function (r) { return r._warn; }).length;
    kpis([
      { lbl: "Prejeti računi", val: String(rows.length), sub: "v obdobju (po filtrih)", cls: "info" },
      { lbl: "Osnova", val: money(rows.reduce(function (a, r) { return a + r.osnova; }, 0)) + " €" },
      { lbl: "Vstopni DDV", val: money(rows.reduce(function (a, r) { return a + r.vat_total; }, 0)) + " €", cls: "warn" },
      { lbl: "Opozorila", val: String(warn), sub: "SI DDV pri tujem dobavitelju", cls: warn ? "bad" : "good" },
      { lbl: "V Minimaxu", val: synced + " / " + rows.length, sub: "sinhronizirano" },
    ]);
  }
  function reloadDocs(kind) {
    var view = kind.toLowerCase();
    return api("/api/" + view).then(function (data) {
      if (data.ok === false) { $("content").innerHTML = "<div class='card'><div class='empty'>" + esc(errText(data)) + "</div></div>"; return; }
      var rows = (data.rows || []).map(kind === "IR" ? prepIr : prepPr);
      S.rows[kind] = rows;
      docKpis(kind, rows, data.totals);
      renderTable({ view: view, kind: kind, cols: kind === "IR" ? IR_COLS : PR_COLS, rows: rows, totals: kind === "IR" ? ["net", "vat_total", "total"] : ["osnova", "vat_total"],
        onDbl: function (id) { openEditor(kind, id); }, emptyIcon: kind === "IR" ? "in" : "out", empty: "Ni " + kind + " vrstic za obdobje in filtre." });
    });
  }
  function loadDocs(kind) { docToolbar(kind); loading(); return reloadDocs(kind); }

  // ------------------------------------------------------------------ urejevalnik vrstice
  var IR_FORM = [
    ["Dokument"], ["book", "Knjiga", "select:Darila,Fitness,Paragoni,Fakture,KIR"], ["seq", "Zap. št.", "int"], ["document_no", "Številka listine", "text", true],
    ["document_date", "Datum listine", "date", true], ["booking_date", "Datum knjiženja", "date"], ["status", "Status", "status"],
    ["Kupec"], ["party_name", "Naziv kupca", "text", true, "span2"], ["vat_id", "ID za DDV", "text"],
    ["Zneski (EUR)"], ["net", "Osnova", "money"], ["base_22", "Osnova 22 %", "money"], ["vat_22", "DDV 22 %", "money"],
    ["base_95", "Osnova 9,5 %", "money"], ["vat_95", "DDV 9,5 %", "money"], ["total", "Skupaj", "money", true],
    ["eu_goods", "Blago EU", "money"], ["eu_services", "Storitve EU", "money"], ["reverse_charge", "Obrnjena davčna obv.", "money"],
    ["exempt", "Oproščeno", "money"], ["excluded", "Ne gre v knjigo", "money"], ["account", "Konto prihodka", "text"],
    ["Opombe"], ["notes", "Opombe", "textarea", false, "span3"],
  ];
  var PR_FORM = [
    ["Dokument"], ["seq", "Zap. št.", "int"], ["document_no", "Številka listine", "text", true], ["internal_no", "Interna številka", "text"],
    ["received_date", "Datum prejema", "date", true], ["document_date", "Datum listine", "date"], ["booking_date", "Datum knjiženja", "date"],
    ["Dobavitelj"], ["supplier_name", "Naziv dobavitelja", "text", true, "span2"], ["vat_id", "ID za DDV", "text"], ["tax_number", "Davčna številka", "text"],
    ["Osnove in DDV (EUR)"], ["net_taxable", "Obdavčljiva osnova", "money"], ["base_22", "Osnova 22 %", "money"], ["vat_22", "DDV 22 %", "money"],
    ["base_95", "Osnova 9,5 %", "money"], ["vat_95", "DDV 9,5 %", "money"], ["base_5", "Osnova 5 %", "money"], ["vat_5", "DDV 5 %", "money"],
    ["eu_goods", "Blago EU", "money"], ["eu_services", "Storitve EU", "money"], ["f76a", "76.a člen", "money"],
    ["exempt_non", "Oproščeno (brez odbitka)", "money"], ["exempt_os", "Oproščeno OS", "money"], ["exempt_on", "Oproščeno ON", "money"],
    ["nondeduct_22", "Neodbitni DDV 22 %", "money"], ["nondeduct_95", "Neodbitni DDV 9,5 %", "money"], ["excluded", "Ne gre v knjigo", "money"],
    ["self_assessment", "Samoobdavčitev", "bool"], ["vat_deductible", "DDV odbiten", "bool"], ["status", "Status", "status"],
    ["Konti"], ["odhodek01", "Odhodek (osnova)", "text"], ["odhodek07", "Odhodek 07", "text"], ["odhodek10", "Odhodek EU blago", "text"],
    ["odhodek11", "Odhodek EU storitve", "text"], ["odhodek_excluded", "Konto »ne gre v knjigo«", "text"], ["placilo", "Konto plačila", "text"],
    ["Opombe"], ["notes", "Opombe", "textarea", false, "span3"],
  ];
  function fieldHtml(f, row) {
    if (f.length === 1) return "<div class='formSec'>" + esc(f[0]) + "</div>";
    var key = f[0], label = f[1], type = f[2], req = f[3], cls = f[4] || "";
    var v = row[key]; if (v == null) v = "";
    var inp;
    if (type === "textarea") inp = "<textarea data-f='" + key + "'>" + esc(v) + "</textarea>";
    else if (type === "bool") inp = "<select data-f='" + key + "'><option value='1'" + (String(v) === "1" ? " selected" : "") + ">da</option><option value='0'" + (String(v) !== "1" ? " selected" : "") + ">ne</option></select>";
    else if (type === "status" || type.indexOf("select:") === 0) {
      var opts = type === "status" ? STATUSES.slice(1).map(function (s) { return s[0]; }) : type.slice(7).split(",");
      if (v && opts.indexOf(String(v)) < 0) opts.unshift(String(v));
      inp = "<select data-f='" + key + "'>" + opts.map(function (o) { return "<option" + (String(v) === o ? " selected" : "") + ">" + esc(o) + "</option>"; }).join("") + "</select>";
    } else if (type === "date") inp = "<input type='date' data-f='" + key + "' value='" + esc(String(v).slice(0, 10)) + "'>";
    else if (type === "money") inp = "<input data-f='" + key + "' data-type='money' inputmode='decimal' class='num' value='" + esc(v === "" ? "" : money(v)) + "'>";
    else if (type === "int") inp = "<input data-f='" + key + "' data-type='int' inputmode='numeric' value='" + esc(v) + "'>";
    else inp = "<input data-f='" + key + "' value='" + esc(v) + "'>";
    return "<label class='fld " + cls + "'" + (req ? " data-req='1'" : "") + "><span>" + esc(label) + (req ? " *" : "") + "</span>" + inp + "<small class='err'></small></label>";
  }
  function readForm(kind) {
    var out = {}, ok = true;
    qa("[data-f]", $("modalBody")).forEach(function (el) {
      var fld = el.closest(".fld"); var err = fld && fld.querySelector(".err");
      if (fld) fld.classList.remove("invalid"); if (err) err.textContent = "";
      var v = el.value.trim(); var t = el.getAttribute("data-type");
      var fail = "";
      if (fld && fld.getAttribute("data-req") && !v) fail = "Obvezno polje.";
      else if (t === "money" && v && !/^-?\d{1,3}(\.\d{3})*(,\d+)?$|^-?\d+([.,]\d+)?$/.test(v.replace(/\s/g, ""))) fail = "Neveljaven znesek.";
      else if (t === "int" && v && !/^\d+$/.test(v)) fail = "Samo cela števila.";
      if (fail) { ok = false; fld.classList.add("invalid"); if (err) err.textContent = fail; }
      out[el.getAttribute("data-f")] = t === "money" ? (v ? num(v).toFixed(2) : "0") : v;
    });
    if (ok && kind === "IR") {
      var calc = num(out.net) + num(out.vat_22) + num(out.vat_95);
      var special = num(out.exempt) || num(out.excluded) || num(out.eu_goods) || num(out.eu_services) || num(out.reverse_charge);
      if (num(out.total) && !special && Math.abs(calc - num(out.total)) > 0.05) out._warn = "Skupaj (" + money(out.total) + ") ni enako osnova + DDV (" + money(calc) + ").";
    }
    return ok ? out : null;
  }
  function openEditor(kind, id) {
    var activeBooks = S.boot && S.boot.ir_books ? Object.keys(S.boot.ir_books).filter(function (b) { return S.boot.ir_books[b]; }) : [];
    var blank = kind === "IR" ? { book: activeBooks[0] || "Darila", status: "OSNUTEK", account: "7620" } : { status: "OSNUTEK", odhodek01: "4190", placilo: "2200", vat_deductible: 1 };
    var load = id ? api("/api/row?kind=" + kind + "&id=" + encodeURIComponent(id)) : Promise.resolve({ ok: true, row: blank });
    load.then(function (d) {
      if (d.ok === false) return toast(errText(d), "error");
      var row = d.row || {};
      var form = kind === "IR" ? IR_FORM : PR_FORM;
      var meta = id ? "<p class='muted small'>ID " + esc(row.id) + " · Minimax: " + badgeFor(row.sync_status) + " · po shranjevanju gre vrstica v »lokalno« — pred sinhronizacijo jo znova potrdi.</p>" : "";
      var warned = false;
      modal({
        title: (id ? "Uredi " : "Nov ") + (kind === "IR" ? "izdani račun" : "prejeti račun") + (row.document_no ? " · " + row.document_no : ""), wide: true,
        html: meta + "<div class='formGrid'>" + form.map(function (f) { return fieldHtml(f, row); }).join("") + "</div><div id='formWarn'></div>",
        buttons: [{ label: "Prekliči" }, { label: "Shrani", kind: "primary", icon: "check", onClick: function (btn) {
          var data = readForm(kind);
          if (!data) { toast("Popravi označena polja.", "warn"); return false; }
          if (data._warn && !warned) {
            warned = true;
            $("formWarn").innerHTML = "<div class='alert warn' style='margin-top:12px'>" + icon("alert") + esc(data._warn) + " Klikni Shrani še enkrat za potrditev.</div>";
            return false;
          }
          delete data._warn;
          if (id) data.id = id;
          withBusy(btn, post("/api/row/save", { kind: kind, row: data }).then(function (r) {
            if (r.ok === false) { toast(errText(r), "error"); return; }
            toast("Shranjeno (" + kind + " #" + r.id + ").", "ok"); closeModal();
            var books = S.boot && S.boot.ir_books;
            if (kind === "IR" && books && data.book && books[data.book] === false) {
              var bk = {}; bk[data.book] = true;
              toast("Vklopljen filter knjige »" + data.book + "«, da je vrstica vidna.", "info");
              post("/api/filters", { filters: { ir_books: bk } }).then(function () { refreshAfter(); });
            } else refreshAfter();
          }));
          return false;
        } }],
      });
    });
  }
  function accountDialog(kind, ids) {
    act("defaults").then(function (d) {
      var def = kind === "IR" ? d.ir : d.pr;
      var hint = kind === "IR" ? "Npr. " + d.ir + " (SI) ali " + d.ir_eu + " (EU)." : "Npr. " + d.pr + ".";
      modal({
        title: "Nastavi konto (" + ids.length + " vrstic)",
        html: "<label class='fld'><span>Konto</span><input id='mAcc' value='" + esc(def || "") + "'></label><p class='muted small'>" + esc(hint) + "</p>" +
          "<label class='chk'><input type='checkbox' id='mRemember' checked> Zapomni za te stranke (pravilo za naslednji uvoz)</label>",
        buttons: [{ label: "Prekliči" }, { label: "Uporabi", kind: "primary", onClick: function (btn) {
          var acc = $("mAcc").value.trim();
          if (!acc) { $("mAcc").closest(".fld").classList.add("invalid"); return false; }
          withBusy(btn, act("apply_account", { kind: kind, ids: ids, account: acc, remember: $("mRemember").checked }).then(function (r) { if (report(r)) { closeModal(); refreshAfter(); } }));
          return false;
        } }],
      });
    });
  }

  // ------------------------------------------------------------------ Minimax sinhronizacija
  function syncDialog(scope) {
    scope = scope || "ALL";
    if (S.busy) return toast("Naloga že teče.", "warn");
    act("sync_preview", { scope: scope }).then(function (p) {
      if (p.ok === false) return toast(errText(p), "error");
      var nothing = !p.ir && !p.pr && !p.parties && !p.synced_recheck;
      var html = "<p>Pošljem v <b>Minimax</b> (osnutki temeljnic, status O) za <b>" + esc(p.company || "—") + "</b>" + (p.org ? " · Org " + esc(p.org) : "") + "?</p>" +
        "<div class='stats'>" + (scope !== "PR" ? "<div class='stat'><b>" + p.ir + "</b><span>IR potrjenih</span></div>" : "") + (scope !== "IR" ? "<div class='stat'><b>" + p.pr + "</b><span>PR potrjenih</span></div>" : "") +
        (scope === "ALL" ? "<div class='stat'><b>" + p.parties + "</b><span>novih strank</span></div>" : "") +
        "<div class='stat'><b>" + p.synced_recheck + "</b><span>že poslanih (preverim)</span></div></div>" +
        "<p class='muted small'>Pošljejo se samo vrstice, potrjene s »4 · Potrdi«. Obstoječe temeljnice v Minimaxu se ne podvojijo.</p>" +
        (nothing ? "<div class='alert warn'>" + icon("alert") + "Ni potrjenih vrstic. Najprej označi in potrdi IR/PR.</div>" : "");
      confirmDialog({ title: "Sinhronizacija z Minimax" + (scope !== "ALL" ? " (" + scope + ")" : ""), icon: "sync", ok: "Pošlji v Minimax", html: html }).then(function (yes) {
        if (!yes) return;
        runJob("sync_ready", { scope: scope }, "Sinhronizacija z Minimax").then(function (r) {
          report(r, "Sinhronizacija končana.");
          if (r && r.failures && r.failures.length) modal({ title: "Sinhronizacija — opozorila (" + r.failures.length + ")", wide: true, html: "<div class='pre'>" + esc(r.failures.join("\n")) + "</div>" });
          refreshAfter();
        });
      });
    });
  }

  // ------------------------------------------------------------------ DDV-O
  function loadDdvo() {
    toolbar(
      "<button class='btn sm' data-d='pdf'>" + icon("file") + "Predogled PDF</button>" +
      "<button class='btn sm primary' data-d='xml'>" + icon("file") + "XML + PDF za eDavke</button>" +
      "<button class='btn sm' data-d='virman'>" + icon("bank") + "PDF + virman (UPN QR)</button>" +
      "<button class='btn sm' data-d='mail'>" + icon("mail") + "E-pošta stranki…</button>" +
      "<span class='grow'></span><button class='btn sm' data-d='mrn'>" + icon("down") + "eDavki MRN</button>" +
      searchBox("viewSearch", "Išči polje ali vir…", "")
    );
    loading();
    qa("[data-d]", $("toolbar")).forEach(function (b) { b.onclick = function () { ddvoAction(b.getAttribute("data-d")); }; });
    return api("/api/ddvo").then(function (d) {
      if (d.ok === false) { kpis([]); $("content").innerHTML = "<div class='card'><div class='empty'>" + icon("tax") + "<div>" + esc(errText(d)) + "</div></div></div>"; return; }
      S.ddvo = d;
      var s = d.summary || {};
      var excess = num(s.excess);
      kpis([
        { lbl: "Izstopni DDV", val: (s.output_vat || "0,00") + " €", sub: "natančno " + (s.output_vat_exact || "—"), cls: "warn" },
        { lbl: "Vstopni DDV", val: (s.input_vat || "0,00") + " €", sub: "natančno " + (s.input_vat_exact || "—"), cls: "info" },
        excess > 0
          ? { lbl: "Presežek (52)", val: (s.excess || "0,00") + " €", sub: "vračilo / prenos", cls: "hero good" }
          : { lbl: "Obveznost za plačilo (51)", val: (s.obligation || "0,00") + " €", sub: "rok: zadnji delovni dan naslednjega meseca", cls: "hero" },
        { lbl: "Kontrola", val: s.control_ok ? "Usklajeno" : "Razlika " + (s.control_difference || ""), sub: "KIR/KPR ↔ DDV-O", cls: s.control_ok ? "good" : "bad" },
        { lbl: "Neodbitni DDV", val: (s.non_deductible_vat || "0,00") + " €", sub: (s.vat_not_deducted_count || 0) + " PR brez odbitka" },
      ]);
      var fields = d.fields || [];
      var render = function (q) {
        q = (q || "").toLowerCase();
        var sec = "", html = "";
        fields.forEach(function (f) {
          if (q && (f.code + " " + f.label + " " + f.source).toLowerCase().indexOf(q) < 0) return;
          if (f.section !== sec) { sec = f.section; html += "<tr class='secRow'><td colspan='7'>" + esc(sec) + "</td></tr>"; }
          var bad = String(f.status || "").toUpperCase() !== "OK" && f.status;
          html += "<tr" + (["51", "52"].indexOf(String(f.code)) >= 0 ? " class='strong'" : "") + "><td class='code'>" + esc(f.code) + "</td><td>" + esc(f.label) + "</td><td>" + esc(f.source) +
            "</td><td class='num'>" + esc(f.exact) + "</td><td class='num'><b>" + esc(f.value) + "</b></td><td class='num muted'>" + esc(f.difference) + "</td><td>" + (bad ? badgeFor(f.status) : "<span class='badge good'>OK</span>") + "</td></tr>";
        });
        $("content").innerHTML = "<div class='card'><div class='cardHead'><h3>Obrazec DDV-O · " + esc((d.period || {}).from_si || "") + " – " + esc((d.period || {}).to_si || "") + "</h3><span class='muted small'>" + esc((d.company || {}).name || "") + " · " + esc(CADENCE[(d.company || {}).ddv_cadence] || (d.company || {}).ddv_cadence || "") + "</span></div>" +
          "<div class='tableWrap'><table class='grid ddvo'><thead><tr><th>Polje</th><th>Opis</th><th>Vir</th><th class='num'>Natančno</th><th class='num'>Obrazec</th><th class='num'>Razlika</th><th>Status</th></tr></thead><tbody>" + html + "</tbody></table></div></div>" +
          (s.info_mrn_text ? "<div class='card'><div class='cardHead'><h3>Uvoz (MRN)</h3></div><div class='pre'>" + esc(s.info_mrn_text) + "</div></div>" : "");
      };
      render("");
      $("viewSearch").oninput = debounce(function () { render($("viewSearch").value); }, 150);
    });
  }
  function fileLinks(r) {
    var paths = [].concat(r.paths || [], r.xml ? [r.xml] : [], r.pdf ? [r.pdf] : []).filter(Boolean);
    var uniq = paths.filter(function (p, i) { return paths.indexOf(p) === i; });
    var html = uniq.map(function (p) { return "<button class='link' data-open='" + esc(p) + "'>" + icon("file") + esc(p) + "</button>"; }).join("");
    if (r.folder) html += "<button class='link' data-open='" + esc(r.folder) + "'>" + icon("folder") + esc(r.folder) + "</button>";
    return html;
  }
  function resultModal(title, r) {
    modal({ title: title, wide: true, html: "<p>" + esc(okText(r)) + "</p>" + (r.detail ? "<div class='pre'>" + esc(r.detail) + "</div>" : "") + "<div class='links'>" + fileLinks(r) + "</div>" });
    qa("[data-open]", $("modalBody")).forEach(function (b) { b.onclick = function () { openPath(b.getAttribute("data-open")); }; });
  }
  function ddvoAction(t) {
    if (t === "pdf") return runJob("ddvo_preview_pdf", {}, "DDV-O predogled PDF").then(function (r) { if (report(r)) resultModal("Predogled DDV-O", r); });
    if (t === "xml") return runJob("ddvo_export", {}, "DDV-O XML + PDF").then(function (r) { if (report(r)) resultModal("DDV-O XML + PDF", r); });
    if (t === "virman") return runJob("ddvo_virman", {}, "DDV-O PDF + virman").then(function (r) { if (report(r)) resultModal("DDV-O paket z virmanom", r); });
    if (t === "mail") return emailFlow();
    if (t === "mrn") return mrnFlow();
  }
  function emailFlow() {
    runJob("ddvo_email_draft", {}, "Pripravljam osnutek e-pošte").then(function (d) {
      if (!d || d.ok === false) return toast(errText(d), "error");
      var att = (d.attachments || []).map(function (p, i) {
        return "<label class='chk'><input type='checkbox' class='mAtt' data-i='" + i + "' checked> " + esc(p.split(/[\\/]/).pop()) + " <small class='muted'>" + esc(p) + "</small></label>";
      }).join("") || "<p class='muted'>Ni priponk.</p>";
      var html = (d.warning ? "<div class='alert warn'>" + icon("alert") + esc(d.warning) + "</div>" : "") +
        "<div class='formGrid'>" +
        "<label class='fld span3'><span>Pošiljatelj</span><input value='" + esc(d.from || "") + "' disabled></label>" +
        "<label class='fld span2' data-req='1'><span>Za *</span><input id='mTo' value='" + esc(d.to || "") + "'><small class='err'></small></label>" +
        "<label class='fld'><span>Kp</span><input id='mCc' value='" + esc(d.cc || "") + "'></label>" +
        "<label class='fld span3' data-req='1'><span>Zadeva *</span><input id='mSubj' value='" + esc(d.subject || "") + "'><small class='err'></small></label></div>" +
        "<div class='formSec'>Predogled sporočila</div><iframe id='mPrev' class='mailPreview' sandbox=''></iframe>" +
        "<div class='formSec'>Priponke</div>" + att +
        "<div class='alert info' style='margin-top:12px'>" + icon("info") + "E-pošta se pošlje <b>samo</b> po kliku »Pošlji« in potrditvi spodaj. Nič se ne pošlje samodejno.</div>" +
        "<label class='chk strong'><input type='checkbox' id='mReviewed'> Pregledal sem prejemnika, vsebino in priponke.</label>";
      modal({
        title: "E-pošta stranki · DDV-O", wide: true, html: html,
        buttons: [{ label: "Prekliči" }, { label: "Pošlji", kind: "primary", icon: "mail", id: "mSend", onClick: function (btn) {
          var to = $("mTo").value.trim(), subj = $("mSubj").value.trim();
          var bad = false;
          [["mTo", /@/.test(to) ? "" : "Vnesi veljaven e-naslov."], ["mSubj", subj ? "" : "Manjka zadeva."]].forEach(function (x) {
            var f = $(x[0]).closest(".fld"); f.classList.toggle("invalid", !!x[1]); f.querySelector(".err").textContent = x[1]; if (x[1]) bad = true;
          });
          if (bad) return false;
          if (!$("mReviewed").checked) { toast("Najprej označi, da si pregledal sporočilo.", "warn"); return false; }
          var atts = qa(".mAtt", $("modalBody")).filter(function (c) { return c.checked; }).map(function (c) { return d.attachments[+c.getAttribute("data-i")]; });
          var body = { to: to, cc: $("mCc").value.trim(), subject: subj, body_html: d.body_html || "", attachments: atts, confirm: true };
          closeModal();
          runJob("ddvo_email_send", body, "Pošiljam e-pošto").then(function (r) { report(r, "E-pošta poslana."); });
          return false;
        } }],
      });
      var fr = $("mPrev");
      fr.srcdoc = "<!doctype html><meta charset='utf-8'><body style='font:14px Segoe UI,Arial,sans-serif;margin:14px;color:#1f2937'>" + (d.body_html || "") + "</body>";
    });
  }
  function mrnFlow() {
    confirmDialog({ title: "eDavki MRN", icon: "down", ok: "Prenesi", html: "<p>Prenesem uvozne carinske deklaracije (MRN) iz eDavkov za izbrano obdobje in podjetje?</p><p class='muted small'>Potrebno je veljavno digitalno potrdilo v Windows.</p>" })
      .then(function (yes) {
        if (!yes) return;
        runJob("fetch_mrn", {}, "eDavki MRN").then(function (r) {
          if (!report(r, "MRN prenesen.")) return;
          var rows = r.rows || [];
          modal({ title: "eDavki MRN (" + rows.length + ")", wide: true, html: rows.length ? "<div class='pre'>" + esc(rows.map(function (x) { return typeof x === "string" ? x : JSON.stringify(x); }).join("\n")) + "</div>" : "<p>Ni MRN zapisov.</p>" });
          if (S.view === "ddvo") loadDdvo();
        });
      });
  }

  // ------------------------------------------------------------------ knjige, konti, stranke, knjižbe, analitika
  var BOOK_LABELS = {
    IR: { ZAPST: "Zap.", P2: "Datum knj.", P3: "Št. listine", P4: "Datum listine", P5: "Kupec", P6: "ID za DDV", P7: "Vrednost z DDV", P8: "Oproščeno z odbitkom", P9: "Oproščeno brez", P10: "Dobave EU", P11: "Storitve EU", P12: "Daljinska prodaja", P13: "Montaža", P14: "Osnova 22", P15: "Osnova 9,5", P16: "Osnova 5", P17: "DDV 22", P18: "DDV 9,5", P19: "DDV 5", OBDOBJE: "Obdobje" },
    PR: { ZAPST: "Zap.", P2: "Datum prejema", P3: "Št. listine", P4: "Datum listine", P5: "Dobavitelj", P6: "ID za DDV", P7: "Vrednost z DDV", OBDOBJE: "Obdobje" },
  };
  function genericCols(rows, labels, moneyLike) {
    if (!rows.length) return [];
    return Object.keys(rows[0]).filter(function (k) { return k !== "raw_json"; }).map(function (k) {
      return { key: k, label: (labels && labels[k]) || k, fmt: moneyLike && moneyLike(k) ? "money" : undefined };
    });
  }
  function listView(o) {
    toolbar(searchBox("viewSearch", o.ph || "Išči…", S.search[o.view] || "") + "<span class='grow'></span>" + (o.extra || ""));
    loading();
    var draw = function (data) {
      if (data.ok === false) { $("content").innerHTML = "<div class='card'><div class='empty'>" + esc(errText(data)) + "</div></div>"; return; }
      var rows = data.rows || [];
      S.rows[o.view] = rows;
      if (o.kpis) kpis(o.kpis(data, rows)); else kpis([]);
      var shownRows = o.server ? rows : clientFilter(rows, S.search[o.view]);
      renderTable({ view: o.view, cols: o.cols ? o.cols(rows) : genericCols(rows), rows: shownRows, totals: o.totals, empty: o.empty, onDbl: o.onDbl });
    };
    var load = function () {
      var url = o.url + (o.server ? (o.url.indexOf("?") >= 0 ? "&" : "?") + "q=" + encodeURIComponent(S.search[o.view] || "") : "");
      return api(url).then(draw);
    };
    $("viewSearch").oninput = debounce(function () {
      S.search[o.view] = $("viewSearch").value; S.limit[o.view] = 0;
      if (o.server) load(); else draw({ ok: true, rows: S.rows[o.view] || [] });
    }, 250);
    if (o.bind) o.bind();
    return load();
  }
  function loadBook(book) {
    return listView({
      view: "knjiga_" + book.toLowerCase(), url: "/api/knjige?book=" + book, ph: "Išči v knjigi " + book + "…",
      cols: function (rows) { return genericCols(rows, BOOK_LABELS[book], function (k) { return /^P(7|[89]|1\d|2\d)/.test(k); }); },
      kpis: function (d, rows) { return [{ lbl: "Knjiga " + book, val: String(rows.length), sub: "vrstic v obdobju", cls: "info" }, { lbl: "Vrednost (P7)", val: money(rows.reduce(function (a, r) { return a + num(r.P7); }, 0)) + " €" }]; },
      totals: ["P7", "P14", "P15", "P16", "P17", "P18", "P19"],
      empty: "Knjiga " + book + " je za obdobje prazna.",
    });
  }
  function loadKonti() {
    return listView({
      view: "konti", url: "/api/konti", ph: "Išči konto, stranko, listino…",
      cols: function () {
        return [{ key: "group", label: "Skupina" }, { key: "konto", label: "Konto" }, { key: "party", label: "Stranka" }, { key: "document", label: "Listina" },
          { key: "tip", label: "Tip" }, { key: "debet", label: "Debet", fmt: "money" }, { key: "kredit", label: "Kredit", fmt: "money" }, { key: "ddvo", label: "DDV-O" }, { key: "opis", label: "Opis" }];
      },
      kpis: function (d, rows) {
        var konti = {}; rows.forEach(function (r) { konti[r.konto] = 1; });
        return [{ lbl: "Knjižbe", val: String(rows.length), cls: "info" }, { lbl: "Kontov", val: String(Object.keys(konti).length) },
          { lbl: "Debet", val: (d.total_debet || "0,00") + " €" }, { lbl: "Kredit", val: (d.total_kredit || "0,00") + " €" },
          { lbl: "Ravnotežje", val: num(d.total_debet) === num(d.total_kredit) ? "Usklajeno" : "Razlika", cls: num(d.total_debet) === num(d.total_kredit) ? "good" : "bad" }];
      },
      totals: ["debet", "kredit"],
    });
  }
  function loadParties() {
    return listView({
      view: "parties", url: "/api/parties", server: true, ph: "Išči naziv, ID za DDV, davčno, kraj…",
      extra: "<button class='btn sm primary' id='btnPartyNew' title='Dodaj novo stranko (podatke lahko izpolniš iz AJPES ali VIES)'>" + icon("plus") + "Nova stranka</button><button class='btn sm' id='btnMissing'>" + icon("users") + "Manjkajoče stranke</button><button class='btn sm' id='btnPartiesSync'>" + icon("down") + "Stranke iz Minimax</button>",
      onDbl: function (id) { partyEditor(id); },
      bind: function () { $("btnPartyNew").onclick = function () { partyEditor(null); }; $("btnMissing").onclick = function () { menuAction("missing"); }; $("btnPartiesSync").onclick = function () { menuAction("sync_parties"); }; },
      cols: function () {
        return [{ key: "name", label: "Naziv" }, { key: "vat_id", label: "ID za DDV" }, { key: "tax_number", label: "Davčna" }, { key: "country", label: "Država" },
          { key: "address", label: "Naslov" }, { key: "postal_code", label: "Pošta" }, { key: "city", label: "Kraj" }, { key: "email", label: "E-pošta" },
          { key: "minimax_code", label: "Minimax šifra" }, { key: "sync_status", label: "Minimax", fmt: "badge" }];
      },
      kpis: function (d, rows) {
        var foreign = rows.filter(function (r) { return +r.is_foreign; }).length;
        var mm = rows.filter(function (r) { return r.minimax_code; }).length;
        return [{ lbl: "Stranke", val: String(d.count != null ? d.count : rows.length), cls: "info" }, { lbl: "Domače", val: String(rows.length - foreign) }, { lbl: "Tuje", val: String(foreign) },
          { lbl: "S šifro Minimax", val: mm + " / " + rows.length, cls: mm === rows.length ? "good" : "warn" }];
      },
    });
  }
  function loadKnjizbe() {
    return listView({
      view: "knjizbe", url: "/api/knjizbe", server: true, ph: "Išči konto, listino, opis…",
      cols: function () {
        return [{ key: "doc_kind", label: "Vrsta" }, { key: "document_no", label: "Listina" }, { key: "line_no", label: "Vrstica", num: true }, { key: "account", label: "Konto" },
          { key: "debit", label: "Debet", fmt: "money" }, { key: "credit", label: "Kredit", fmt: "money" }, { key: "description", label: "Opis" }, { key: "created_at", label: "Ustvarjeno" }];
      },
      kpis: function (d, rows) { return [{ lbl: "Knjižbe", val: String(rows.length), cls: "info" }]; },
      totals: ["debit", "credit"],
    });
  }
  function loadAnalysis() {
    toolbar("<button class='btn sm' id='btnAnRefresh'>" + icon("refresh") + "Osveži</button><span class='grow'></span><span class='muted small'>Pregled obdobja in DDV-O</span>");
    loading();
    $("btnAnRefresh").onclick = function () { loadAnalysis(); };
    return Promise.all([api("/api/analysis"), api("/api/ddvo")]).then(function (res) {
      var a = res[0], d = res[1], s = (d && d.summary) || {}, sm = (S.boot && S.boot.summary) || {};
      var pay = num(s.excess) > 0 ? { lbl: "Presežek DDV", val: (s.excess || "0,00") + " €", cls: "hero good" } : { lbl: "Obveznost DDV", val: (s.obligation || "0,00") + " €", cls: "hero" };
      kpis([{ lbl: "Promet IR", val: (sm.ir_value || "0,00") + " €", sub: (sm.ir_count || 0) + " računov", cls: "info" },
        { lbl: "Promet PR", val: (sm.pr_value || "0,00") + " €", sub: (sm.pr_count || 0) + " računov" },
        { lbl: "Izstopni DDV", val: (s.output_vat || "0,00") + " €", cls: "warn" }, { lbl: "Vstopni DDV", val: (s.input_vat || "0,00") + " €" }, pay]);
      var ir = num(sm.ir_value), pr = num(sm.pr_value), mx = Math.max(ir, pr, 1);
      var bar = function (lbl, v, cls) { return "<div class='barRow'><span>" + esc(lbl) + "</span><div class='bar'><i class='" + cls + "' style='width:" + Math.round(100 * v / mx) + "%'></i></div><b>" + money(v) + " €</b></div>"; };
      $("content").innerHTML = "<div class='cols2'><div class='card'><div class='cardHead'><h3>Promet obdobja</h3></div><div class='bars'>" + bar("Izdani (IR)", ir, "good") + bar("Prejeti (PR)", pr, "info") +
        bar("Izstopni DDV", num(s.output_vat), "warn") + bar("Vstopni DDV", num(s.input_vat), "info") + "</div></div>" +
        "<div class='card'><div class='cardHead'><h3>Povzetek</h3></div><div class='pre'>" + esc((a && a.ok !== false && a.text) || errText(a)) + "</div></div></div>";
    });
  }

  // ------------------------------------------------------------------ Integra SQL
  function integraDialog() {
    api("/api/integra").then(function (info) {
      if (info.ok === false) return toast(errText(info), "error");
      var files = [].concat(info.candidates || [], info.baks || []).filter(function (p, i, a) { return a.indexOf(p) === i; });
      var list = files.length ? files.map(function (p, i) {
        return "<label><input type='radio' name='mBak' value='" + i + "'" + (i === 0 ? " checked" : "") + "><span><b>" + esc(p.split(/[\\/]/).pop()) + "</b><br><small class='muted'>" + esc(p) + "</small></span></label>";
      }).join("") : "<div class='empty small'>" + icon("db") + "<div>" + esc(info.status || "V SQL mapi ni ZIP/BAK kopij.") + "</div></div>";
      modal({
        title: "Integra SQL · TROPS", wide: true,
        html: "<div class='formGrid'><label class='fld span2'><span>SQL mapa</span><input id='mSqlDir' value='" + esc(info.sql_dir || "") + "'></label>" +
          "<div class='fld'><span>&nbsp;</span><div class='row'><button class='btn sm' id='mPickDir'>" + icon("folder") + "Izberi…</button><button class='btn sm' id='mSaveDir'>Shrani</button></div></div></div>" +
          "<div class='formSec'>Varnostne kopije (" + files.length + ")</div><div class='radioList'>" + list + "</div>" +
          "<div class='formSec'>UrejanjeKisanal → IR/PR</div><div class='row'><label class='fld'><span>Leto</span><input id='mYear' inputmode='numeric' value='" + esc(info.year || (S.boot && S.boot.period && S.boot.period.year) || "") + "'></label>" +
          "<button class='btn' id='mKisanal'>" + icon("db") + "Preberi UrejanjeKisanal</button></div>",
        buttons: [{ label: "Zapri" }, { label: "RESTORE izbrane kopije…", kind: "danger", icon: "db", onClick: function () {
          var sel = document.querySelector("input[name=mBak]:checked");
          if (!sel) { toast("Izberi varnostno kopijo.", "warn"); return false; }
          var cand = files[+sel.value];
          closeModal();
          confirmDialog({ title: "Obnova baze TROPS", danger: true, ok: "Nadaljuj", icon: "alert",
            html: "<p>RESTORE prepiše SQL bazo <b>TROPS</b> z vsebino:</p><p><code>" + esc(cand) + "</code></p><p class='muted'>Trenutni podatki v TROPS bodo zamenjani.</p>" })
            .then(function (yes) {
              if (!yes) return;
              return confirmDialog({ title: "Zadnja potrditev", danger: true, ok: "Da, obnovi TROPS", html: "<p>Res obnovim TROPS iz <b>" + esc(cand.split(/[\\/]/).pop()) + "</b>? Tega ni mogoče razveljaviti.</p>" });
            })
            .then(function (yes2) {
              if (!yes2) return;
              runJob("integra_restore", { candidate: cand, confirm: true }, "Obnova TROPS (RESTORE)").then(function (r) { report(r, "TROPS obnovljen."); });
            });
          return false;
        } }],
      });
      $("mPickDir").onclick = function () { pickFolder().then(function (p) { if (p) $("mSqlDir").value = p; }); };
      $("mSaveDir").onclick = function () {
        act("integra_set_dir", { path: $("mSqlDir").value.trim() }).then(function (r) { if (report(r, "SQL mapa shranjena.")) { closeModal(); integraDialog(); } });
      };
      $("mKisanal").onclick = function () {
        var y = $("mYear").value.trim();
        if (!/^\d{4}$/.test(y)) { $("mYear").closest(".fld").classList.add("invalid"); return; }
        closeModal();
        runJob("integra_kisanal", { year: y }, "UrejanjeKisanal " + y).then(function (r) {
          if (!report(r, "UrejanjeKisanal prebran.")) return;
          var lines = [r.kisanal && r.kisanal.message, r.irpr && (r.irpr.message || r.irpr.error)].filter(Boolean);
          if (lines.length) modal({ title: "UrejanjeKisanal", wide: true, html: "<div class='pre'>" + esc(lines.join("\n\n")) + "</div>" });
          refreshAfter();
        });
      };
    });
  }

  // ------------------------------------------------------------------ meni orodij
  // ------------------------------------------------------------------ 5.1: konti Trops → Minimax, kontni plan
  function accountMapDialog() {
    api("/api/account_map").then(function (d) {
      if (!d || d.ok === false) return toast(errText(d), "error");
      var rows = d.rows || [];
      var dl = "<datalist id='mmChoices'>" + (d.choices || []).map(function (c) { return "<option value='" + esc(c) + "'>"; }).join("") + "</datalist>";
      var info = "<div class='stats'><div class='stat'><b>" + rows.length + "</b><span>kontov za preslikavo</span></div><div class='stat'><b>" + (d.mm_count || 0) +
        "</b><span>knjižljivih v Minimaxu</span></div><div class='stat'><b>" + (d.saved || []).length + "</b><span>shranjenih preslikav</span></div></div>";
      var warn = d.warning ? "<div class='alert warn'>" + icon("alert") + esc(d.warning) + "</div>" : "";
      var body = rows.length ? "<div class='tableWrap short tall'><table class='grid'><thead><tr><th>Trops konto</th><th class='num'>Uporab</th><th>Minimax konto (zamenjava)</th></tr></thead><tbody>" +
        rows.map(function (r, i) {
          return "<tr><td class='code'>" + esc(r.trops_code) + "</td><td class='num'>" + esc(r.count) + "</td><td class='fldCell'><input class='mmPick' list='mmChoices' data-i='" + i + "' value='" + esc(r.suggested_label || "") + "' placeholder='Vpiši šifro ali naziv …'></td></tr>";
        }).join("") + "</tbody></table></div>" +
        "<label class='chk strong'><input type='checkbox' id='mApplyData' checked> Prepiši tudi obstoječe vrstice (IR, PR, knjižbe, kisanal)</label>"
        : "<div class='empty small'>" + icon("check") + "<div><b>Vsi konti so skladni z Minimaxom.</b><br>Ni kontov, ki bi potrebovali preslikavo.</div></div>";
      var saved = (d.saved || []).length ? "<details class='savedMaps'><summary>Shranjene preslikave (" + d.saved.length + ")</summary><div class='tableWrap short'><table class='grid'><thead><tr><th>Trops</th><th>Minimax</th><th>Vir</th><th>Posodobljeno</th></tr></thead><tbody>" +
        d.saved.map(function (m) { return "<tr><td class='code'>" + esc(m.trops_code) + "</td><td>" + esc(m.minimax_label || m.minimax_code) + "</td><td>" + esc(m.source) + "</td><td>" + esc(siDate(m.updated_at)) + "</td></tr>"; }).join("") +
        "</tbody></table></div></details>" : "";
      var buttons = [{ label: "Zapri" }];
      if (rows.length) buttons.push({ label: "Shrani preslikave", kind: "primary", icon: "check", onClick: function (btn) {
        var maps = {}, missing = [];
        qa(".mmPick", $("modalBody")).forEach(function (inp) {
          var r = rows[+inp.getAttribute("data-i")], v = inp.value.trim();
          inp.classList.toggle("bad", !v);
          if (v) maps[r.trops_code] = v.split(" ")[0]; else missing.push(r.trops_code);
        });
        if (missing.length) { toast("Manjka Minimax konto za: " + missing.join(", "), "warn"); return false; }
        var apply = $("mApplyData").checked;
        var go = function (confirmed) {
          withBusy(btn, act("account_map_save", { maps: maps, apply_data: apply, confirm: confirmed }).then(function (r) { if (report(r)) { closeModal(); refreshAfter(); } }));
        };
        if (!apply) { go(false); return false; }
        closeModal();
        confirmDialog({ title: "Prepis kontov v podatkih", icon: "alert", ok: "Shrani in prepiši",
          html: "<p>Shranim <b>" + Object.keys(maps).length + "</b> preslikav in v lokalni bazi zamenjam konte v obstoječih IR, PR, knjižbah in kisanal?</p><p class='muted small'>Minimax se ne spremeni. Spremenjene vrstice bo treba pred sinhronizacijo znova potrditi.</p>" })
          .then(function (yes) { if (yes) act("account_map_save", { maps: maps, apply_data: true, confirm: true }).then(function (r) { if (report(r)) refreshAfter(); }); });
        return false;
      } });
      modal({ title: "Konti Trops → Minimax", wide: true, html: dl + "<p class='muted'>Konti, ki jih v Minimaxu ni ali niso knjižljivi. Izberi zamenjavo; preslikava se shrani in velja za vse naslednje uvoze in sinhronizacije." +
        (d.org ? " Org " + esc(d.org) + "." : "") + "</p>" + warn + info + body + saved, buttons: buttons });
    });
  }
  function minimaxAccountsSync() {
    return confirmDialog({ title: "Kontni plan iz Minimax", icon: "down", ok: "Prenesi kontni plan",
      html: "<p>Preberem kontni plan iz Minimaxa in ga shranim v lokalno bazo podjetja?</p><p class='muted small'>V Minimaxu se nič ne spremeni. Kontni plan se uporablja za izbiro kontov in preslikavo.</p>" })
      .then(function (y) { if (y) runJob("minimax_accounts_sync", {}, "Kontni plan iz Minimax").then(function (r) { report(r, "Kontni plan prenesen."); if (S.view === "konti") loadView("konti"); }); });
  }

  // ------------------------------------------------------------------ 5.1: stranka (urejanje, AJPES, VIES)
  var PARTY_FORM = [
    ["Osnovno"], ["kind", "Vrsta", "select:SI,EU,THIRD,NONE"], ["name", "Naziv", "text", true, "span2"],
    ["vat_id", "ID za DDV", "text"], ["tax_number", "Davčna / lokalni ID", "text"], ["country", "Država (2 črki)", "text"],
    ["Naslov in kontakt"], ["address", "Naslov", "text", false, "span2"], ["postal_code", "Pošta", "text"], ["city", "Kraj", "text"],
    ["email", "E-pošta", "text"], ["phone", "Telefon", "text"],
    ["Registri"], ["registration_no", "Matična številka", "text"], ["ajpes_code", "AJPES šifra", "text"], ["iban", "TRR / IBAN", "text"],
    ["minimax_code", "Minimax šifra", "text"], ["Opombe"], ["notes", "Opombe", "textarea", false, "span3"],
  ];
  var KIND_LABEL = { SI: "SI – domača", EU: "EU – tuja", THIRD: "Tretja država", NONE: "Ni zavezanec" };
  function partyKind(r) {
    var c = String(r.country || "SI").toUpperCase();
    if (!+r.is_foreign && c === "SI") return r.tax_number || r.vat_id ? "SI" : "NONE";
    return /^(AT|BE|BG|CY|CZ|DE|DK|EE|EL|GR|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SK|XI)$/.test(c) ? "EU" : "THIRD";
  }
  function partyVals() {
    var o = {};
    qa("[data-p]", $("modalBody")).forEach(function (el) { o[el.getAttribute("data-p")] = el.value.trim(); });
    return o;
  }
  function setParty(field, value, onlyEmpty) {
    var el = document.querySelector("#modalBody [data-p='" + field + "']");
    if (!el || value == null) return;
    if (onlyEmpty && el.value.trim()) return;
    el.value = value;
    el.classList.add("filled"); setTimeout(function () { el.classList.remove("filled"); }, 1600);
  }
  function partyResult(kind, html) { var el = $("pResult"); if (el) el.innerHTML = "<div class='alert " + kind + "'>" + icon(kind === "error" ? "alert" : kind === "warn" ? "alert" : "check") + "<div>" + html + "</div></div>"; }
  function partyAjpes(entity) {
    var v = partyVals(); if (entity) v.ajpes_code = entity;
    runJob("party_ajpes", { party: v }, "AJPES poizvedba").then(function (r) {
      if (!r || r.ok === false) {
        var cand = (r && r.candidates) || [];
        var list = cand.length ? "<div class='candList'>" + cand.map(function (c, i) { return "<button class='link' data-c='" + i + "'>" + icon("building") + esc(c.name) + " · " + esc(c.tax_number || "—") + (c.city ? " · " + esc(c.city) : "") + "</button>"; }).join("") + "</div>" : "";
        partyResult(r && r.needs_login ? "warn" : "error", esc(errText(r)) + list);
        qa("[data-c]", $("pResult")).forEach(function (b) { b.onclick = function () { var c = cand[+b.getAttribute("data-c")]; setParty("ajpes_code", c.ajpes_code || ""); setParty("tax_number", c.tax_number || ""); partyAjpes(c.ajpes_code || ""); }; });
        return;
      }
      setParty("kind", "SI"); setParty("country", "SI"); setParty("name", r.name); setParty("tax_number", r.tax_number); setParty("vat_id", "");
      ["address", "postal_code", "city", "registration_no", "ajpes_code", "email", "phone"].forEach(function (k) { if (r[k]) setParty(k, r[k]); });
      if (r.iban || (r.ibans || []).length) setParty("iban", r.iban || r.ibans[0]);
      partyResult("good", esc(okText(r)) + " Preveri podatke in klikni <b>Shrani</b>.");
    });
  }
  function partyVies() {
    runJob("party_vies", { party: partyVals() }, "VIES preverba").then(function (r) {
      if (!r || r.ok === false) return partyResult("error", esc(errText(r)));
      if (r.valid) {
        setParty("vat_id", r.full_vat); setParty("tax_number", r.vat_number); setParty("country", r.country);
        setParty("kind", r.country === "SI" ? "SI" : "EU");
        if (r.name) setParty("name", r.name, true);
        if (r.address) setParty("address", String(r.address).split(/\r?\n/)[0], true);
        partyResult("good", "<b>Je v sistemu VIES.</b> " + esc(r.full_vat) + (r.name ? " · " + esc(r.name) : "") + (r.address ? "<br><small>" + esc(r.address) + "</small>" : ""));
      } else {
        setParty("vat_id", "");
        partyResult("warn", "<b>Ni v sistemu VIES.</b> " + esc(r.message || "") + "<br><small>Polje ID za DDV ostane prazno; v Minimax gre kot »ni zavezanec«.</small>");
      }
    });
  }
  function partyEditor(id) {
    var load = id ? api("/api/party?id=" + encodeURIComponent(id)) : Promise.resolve({ ok: true, row: { country: "SI" } });
    load.then(function (d) {
      if (!d || d.ok === false) return toast(errText(d), "error");
      var row = Object.assign({}, d.row || {}); row.kind = row.kind || partyKind(row);
      var fields = PARTY_FORM.map(function (f) {
        if (f.length === 1) return "<div class='formSec'>" + esc(f[0]) + "</div>";
        var k = f[0], v = row[k] == null ? "" : row[k], inp;
        if (f[2] === "textarea") inp = "<textarea data-p='" + k + "'>" + esc(v) + "</textarea>";
        else if (f[2].indexOf("select:") === 0) inp = "<select data-p='" + k + "'>" + f[2].slice(7).split(",").map(function (o) { return "<option value='" + o + "'" + (String(v) === o ? " selected" : "") + ">" + esc(KIND_LABEL[o] || o) + "</option>"; }).join("") + "</select>";
        else inp = "<input data-p='" + k + "' value='" + esc(v) + "'>";
        return "<label class='fld " + (f[4] || "") + "'" + (f[3] ? " data-req='1'" : "") + "><span>" + esc(f[1]) + (f[3] ? " *" : "") + "</span>" + inp + "<small class='err'></small></label>";
      }).join("");
      var meta = id ? "<p class='muted small'>ID " + esc(row.id) + " · Minimax: " + (badgeFor(row.sync_status) || "—") + (row.source ? " · vir: " + esc(row.source) : "") + "</p>" : "";
      modal({
        title: id ? "Stranka · " + (row.name || "") : "Nova stranka", wide: true,
        html: meta + "<div class='lookupBar'><button class='btn sm' id='pAjpes'>" + icon("building") + "Poišči v AJPES</button><button class='btn sm' id='pVies'>" + icon("check") + "Preveri VIES</button>" +
          "<span class='muted small'>Poizvedba samo izpolni obrazec — shrani se šele s klikom Shrani.</span></div><div id='pResult'></div><div class='formGrid'>" + fields + "</div>",
        buttons: [{ label: "Prekliči" }, { label: "Shrani", kind: "primary", icon: "check", onClick: function (btn) {
          var v = partyVals();
          var nameFld = document.querySelector("#modalBody [data-p='name']").closest(".fld");
          nameFld.classList.toggle("invalid", !v.name); nameFld.querySelector(".err").textContent = v.name ? "" : "Naziv je obvezen.";
          if (!v.name) return false;
          if (id) v.id = id;
          var saved = function (r) { if (report(r)) { closeModal(); refreshAfter(); } };
          withBusy(btn, act("party_save", { party: v }).then(function (r) {
            if (r && r.duplicate && r.existing) {
              // 5.1: stranka s to davčno / ID za DDV že obstaja — vprašaj, ne prepiši tiho.
              var ex = r.existing;
              partyResult("warn", "<b>Stranka že obstaja:</b> " + esc(ex.name || "") + " (ID " + esc(ex.id) + (ex.vat_id ? " · " + esc(ex.vat_id) : "") + (ex.city ? " · " + esc(ex.city) : "") + ")." +
                "<br>Shrani bi prepisal njene podatke s tem obrazcem.<div class='lookupBar'><button class='btn sm' id='pDupOpen'>Odpri obstoječo</button>" +
                "<button class='btn sm primary' id='pDupUpdate'>Posodobi obstoječo</button><button class='btn sm' id='pDupCancel'>Prekliči</button></div>");
              $("pDupOpen").onclick = function () { closeModal(); partyEditor(ex.id); };
              $("pDupUpdate").onclick = function () { var v2 = Object.assign({}, v, { confirm_existing: true }); act("party_save", { party: v2 }).then(saved); };
              $("pDupCancel").onclick = function () { $("pResult").innerHTML = ""; };
              return;
            }
            saved(r);
          }));
          return false;
        } }],
      });
      $("pAjpes").onclick = function () { partyAjpes(""); };
      $("pVies").onclick = partyVies;
    });
  }

  // ------------------------------------------------------------------ 5.1: videz (Trops 4 / Trops 5) in tema — shranjeno v nastavitvah
  function applyLook(look) {
    look = look === "t4" ? "t4" : "t5";
    document.documentElement.setAttribute("data-look", look);
    qa("[data-look-btn]").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-look-btn") === look); b.setAttribute("aria-pressed", b.getAttribute("data-look-btn") === look ? "true" : "false"); });
    closeFlyouts();
  }
  function saveUiPref(key, value) {
    try { localStorage.setItem("trops5." + key, value); } catch (_e) { /* zasebni način */ }
    return act("set_ui_pref", { key: key, value: value }).then(function (r) { if (r && r.ok === false) toast("Nastavitev ni shranjena: " + errText(r), "warn"); });
  }
  function setLook(look) { applyLook(look); saveUiPref("ui_videz", look); }

  // ------------------------------------------------------------------ 5.1: bližnjice
  var SHORTCUTS = [["F5", "Osveži podatke"], ["Ctrl+F", "Iskanje v pogledu"], ["Alt+1 … Alt+9", "Pogledi: IR, PR, DDV-O, Knjiga IR, Knjiga PR, Konti, Knjižbe, Stranke, Analitika"],
    ["Alt+← / Alt+→", "Prejšnje / naslednje obdobje"], ["Ctrl+Enter", "Potrdi okno (Shrani / Potrdi)"], ["Esc", "Zapri okno ali meni"], ["?", "Ta seznam bližnjic"], ["Dvoklik", "Uredi vrstico ali stranko"]];
  function shortcutsHelp() {
    modal({ title: "Bližnjice na tipkovnici", html: "<table class='grid keys'><tbody>" + SHORTCUTS.map(function (s) { return "<tr><td><kbd>" + esc(s[0]) + "</kbd></td><td>" + esc(s[1]) + "</td></tr>"; }).join("") + "</tbody></table>" });
  }

  function menuAction(a) {
    closeFlyouts();
    switch (a) {
      case "import_vasco":
        return pickExcelMulti().then(function (paths) {
          if (!paths || !paths.length) return;
          runJob("import_vasco", { paths: paths }, "Uvoz Vasco").then(function (r) {
            if (!report(r, "Vasco uvoz končan.")) return;
            if (r.report) modal({ title: "Vasco uvoz", wide: true, html: "<div class='pre'>" + esc(typeof r.report === "string" ? r.report : JSON.stringify(r.report, null, 2)) + "</div>" });
            refreshAfter();
          });
        });
      case "import_kirkpr":
        return pickFile(["FURS KIR/KPR (*.xml;*.csv;*.xlsx;*.xls)", "Vse (*.*)"], "FURS KIR/KPR datoteka").then(function (p) {
          if (!p) return;
          runJob("import_kirkpr", { path: p }, "Uvoz KIR/KPR").then(function (r) { if (report(r)) refreshAfter(); });
        });
      case "integra": return integraDialog();
      case "learn_accounts": return act("learn_accounts").then(function (r) { report(r); });
      case "delete_import":
        return act("delete_preview").then(function (p) {
          if (p.ok === false) return toast(errText(p), "error");
          if (!p.ir && !p.pr) return toast("V obdobju ni vrstic za brisanje.", "info");
          return confirmDialog({ title: "Briši uvoz obdobja", danger: true, ok: "Izbriši " + (p.ir + p.pr) + " vrstic", icon: "trash",
            html: "<p>Iz lokalne baze izbrišem vrstice obdobja <b>" + esc(siDate(p.from)) + " – " + esc(siDate(p.to)) + "</b>:</p><div class='stats'><div class='stat'><b>" + p.ir + "</b><span>IR</span></div><div class='stat'><b>" + p.pr + "</b><span>PR</span></div></div>" +
              "<p class='muted small'>Vrstice brez datuma ostanejo. Minimax se ne spremeni.</p><label class='chk strong'><input type='checkbox' id='mSure'> Razumem, brisanje je dokončno.</label>",
            validate: function () { if (!$("mSure").checked) { toast("Označi potrditev.", "warn"); return false; } } })
            .then(function (yes) { if (yes) act("delete_import_period", { confirm: true }).then(function (r) { report(r); refreshAfter(); }); });
        });
      case "sync_parties":
        return confirmDialog({ title: "Stranke iz Minimax", icon: "down", ok: "Prenesi", html: "<p>Prenesem šifrant strank iz Minimaxa v lokalno bazo podjetja?</p>" })
          .then(function (y) { if (y) runJob("sync_parties", {}, "Minimax↓ stranke").then(function (r) { report(r); refreshAfter(); }); });
      case "missing":
        return Promise.all([act("missing_parties", { book: "IR" }), act("missing_parties", { book: "PR" })]).then(function (res) {
          var bad = res.filter(function (r) { return r.ok === false; })[0];
          if (bad) return toast(errText(bad), "error");
          var rowsHtml = function (rows) {
            if (!rows.length) return "<p class='muted'>Ni manjkajočih.</p>";
            var keys = Object.keys(rows[0]).slice(0, 6);
            return "<div class='tableWrap short'><table class='grid'><thead><tr>" + keys.map(function (k) { return "<th>" + esc(k) + "</th>"; }).join("") + "</tr></thead><tbody>" +
              rows.map(function (r) { return "<tr>" + keys.map(function (k) { return "<td>" + esc(r[k]) + "</td>"; }).join("") + "</tr>"; }).join("") + "</tbody></table></div>";
          };
          modal({ title: "Manjkajoče stranke", wide: true, html: "<div class='formSec'>IR (" + res[0].count + ")</div>" + rowsHtml(res[0].rows || []) + "<div class='formSec'>PR (" + res[1].count + ")</div>" + rowsHtml(res[1].rows || []) +
            "<p class='muted small'>Nove stranke se ustvarijo v Minimaxu ob sinhronizaciji (5 · Sinhroniziraj).</p>" });
        });
      case "sync_ready": return syncDialog("ALL");
      case "export_kirkpr_xml": return runJob("export_kirkpr_xml", {}, "Izvoz XML za KirKpr").then(function (r) { if (report(r)) resultModal("Izvoz XML za KirKpr/Minimax", r); });
      case "check_api": return runJob("check_api", {}, "Preverjanje Minimax API").then(function (r) { report(r, "Minimax API dosegljiv."); });
      case "mrn": return mrnFlow();
      case "classic": return act("open_classic").then(function (r) { report(r, "Klasični urejevalnik se odpira."); });
      case "theme": return toggleTheme();
      case "look_t4": return setLook("t4");
      case "look_t5": return setLook("t5");
      case "shortcuts": return shortcutsHelp();
      case "account_map": return accountMapDialog();
      case "mm_accounts": return minimaxAccountsSync();
      case "party_new": return partyEditor(null);
      case "about":
        return modal({ title: "O programu", html: "<p><b>Trops Studio " + esc((S.boot && S.boot.version) || "5.1.00") + "</b></p><p>" + esc((S.boot && S.boot.workflow) || "") + "</p><p class='muted small'>" + esc($("dbPath").textContent) + "</p>" });
      case "close":
        return confirmDialog({ title: "Izhod", ok: "Zapri program", html: "<p>Zaprem Trops Studio?</p>" }).then(function (y) {
          if (!y) return;
          var b = bridge(); if (b && b.close_window) b.close_window(); else window.close();
        });
    }
  }
  function placeFlyout(btn, fly) {
    if (!fly) return;
    var r = btn.getBoundingClientRect();
    var h = fly.offsetHeight;
    if (document.documentElement.getAttribute("data-look") === "t4") {
      fly.style.left = Math.max(8, Math.min(r.left, window.innerWidth - fly.offsetWidth - 8)) + "px";
      fly.style.top = (r.bottom + 2) + "px";
      return;
    }
    fly.style.left = (r.right + 6) + "px";
    fly.style.top = Math.max(8, Math.min(r.top, window.innerHeight - h - 8)) + "px";
  }
  function closeFlyouts() { qa(".menuGroup.open").forEach(function (g) { g.classList.remove("open"); }); }

  // ------------------------------------------------------------------ pogledi
  var VIEWS = {
    ir: { title: "Izdani računi", sub: "IR · knjiga izdanih računov", load: function () { return loadDocs("IR"); } },
    pr: { title: "Prejeti računi", sub: "PR · knjiga prejetih računov", load: function () { return loadDocs("PR"); } },
    ddvo: { title: "Obrazec DDV-O", sub: "Obračun DDV za obdobje", load: loadDdvo },
    knjiga_ir: { title: "Knjiga IR", sub: "Polja P2–P27 po pravilniku", load: function () { return loadBook("IR"); } },
    knjiga_pr: { title: "Knjiga PR", sub: "Polja P2–P27 po pravilniku", load: function () { return loadBook("PR"); } },
    konti: { title: "Konti", sub: "Pivot knjižb po kontih", load: loadKonti },
    knjizbe: { title: "Vse knjižbe", sub: "Temeljnične vrstice", load: loadKnjizbe },
    parties: { title: "Stranke", sub: "Šifrant strank podjetja", load: loadParties },
    analysis: { title: "Analitika", sub: "Povzetek obdobja", load: loadAnalysis },
  };
  function loadView(view, keep) {
    var v = VIEWS[view] || VIEWS.ir;
    S.view = VIEWS[view] ? view : "ir";
    qa(".navItem[data-view]").forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-view") === S.view); });
    $("viewTitle").textContent = v.title; $("viewSub").textContent = v.sub;
    if (!keep) { $("kpis").innerHTML = ""; }
    if (!(S.boot && S.boot.company && S.boot.company.key)) {
      kpis([]); toolbar("");
      $("content").innerHTML = "<div class='card'><div class='empty big'>" + icon("building") + "<div><b>Ni izbranega podjetja</b><br>Izberi podjetje v zgornji vrstici.</div><button class='btn primary' id='btnPickCo'>Izberi podjetje</button></div></div>";
      $("btnPickCo").onclick = function () { openCompanyPop(); };
      return Promise.resolve();
    }
    if (keep && (S.view === "ir" || S.view === "pr")) return reloadDocs(S.view.toUpperCase());
    return Promise.resolve(v.load()).catch(function (e) { toast(String(e), "error"); });
  }

  // ------------------------------------------------------------------ tema
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    var u = $("btnTheme").querySelector("use"); if (u) u.setAttribute("href", t === "dark" ? "#i-sun" : "#i-moon");
  }
  function toggleTheme() {
    var t = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(t);
    saveUiPref("ui_tema", t);
  }

  // ------------------------------------------------------------------ dogodki
  function openCompanyPop() { $("periodPop").hidden = true; $("companyPop").hidden = false; $("companySearch").focus(); loadCompanies(); }
  function bind() {
    qa(".navItem[data-view]").forEach(function (b) { b.onclick = function () { closeFlyouts(); loadView(b.getAttribute("data-view")); }; });
    qa(".navItem[data-menu]").forEach(function (b) {
      b.onclick = function (e) { e.stopPropagation(); var g = b.parentNode; var open = g.classList.contains("open"); closeFlyouts(); if (!open) { g.classList.add("open"); placeFlyout(b, g.querySelector(".flyout")); } };
    });
    qa(".flyout [data-act]").forEach(function (b) { b.onclick = function (e) { e.stopPropagation(); menuAction(b.getAttribute("data-act")); }; });
    $("companyBtn").onclick = function (e) { e.stopPropagation(); if ($("companyPop").hidden) openCompanyPop(); else $("companyPop").hidden = true; };
    $("companySearch").oninput = debounce(loadCompanies, 200);
    $("periodBtn").onclick = function (e) { e.stopPropagation(); $("companyPop").hidden = true; $("periodPop").hidden = !$("periodPop").hidden; };
    $("btnApplyChoice").onclick = function () {
      var y = $("periodYear").value.trim();
      if (!/^\d{4}$/.test(y)) return toast("Vnesi leto (npr. " + new Date().getFullYear() + ").", "warn");
      applyPeriod({ label: $("periodChoice").value, year: y });
    };
    $("btnApplyPeriod").onclick = function () {
      var f = $("periodFrom").value, t = $("periodTo").value;
      if (!f || !t) return toast("Vnesi začetni in končni datum.", "warn");
      if (f > t) return toast("Začetni datum je po končnem.", "warn");
      applyPeriod({ from: f, to: t });
    };
    $("btnResetPeriod").onclick = function () { act("reset_period").then(function (d) { $("periodPop").hidden = true; if (d.ok === false) return toast(errText(d), "error"); S.rows = {}; afterChange(d); }); };
    $("btnPrevPeriod").onclick = function () { act("shift_period", { delta: -1 }).then(function (d) { if (d.ok === false) return toast(errText(d), "error"); S.rows = {}; afterChange(d); }); };
    $("btnNextPeriod").onclick = function () { act("shift_period", { delta: 1 }).then(function (d) { if (d.ok === false) return toast(errText(d), "error"); S.rows = {}; afterChange(d); }); };
    $("btnRefresh").onclick = function () { withBusy($("btnRefresh"), act("refresh").then(function (d) { if (d.ok === false) return toast(errText(d), "error"); afterChange(d); toast("Osveženo.", "info", 1800); })); };
    $("btnTheme").onclick = toggleTheme;
    qa("[data-look-btn]").forEach(function (b) { b.onclick = function (e) { e.stopPropagation(); setLook(b.getAttribute("data-look-btn")); }; });
    $("btnSync").onclick = function () { syncDialog("ALL"); };
    $("modalX").onclick = function () { closeModal(); };
    $("modal").addEventListener("mousedown", function (e) { if (e.target === $("modal")) closeModal(); });
    [$("companyPop"), $("periodPop")].forEach(function (p) { p.addEventListener("click", function (e) { e.stopPropagation(); }); });
    document.addEventListener("click", function () { $("companyPop").hidden = true; $("periodPop").hidden = true; closeFlyouts(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { if (!$("modal").hidden) closeModal(); $("companyPop").hidden = true; $("periodPop").hidden = true; closeFlyouts(); }
      if (e.key === "F5") { e.preventDefault(); $("btnRefresh").click(); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") { var s = $("viewSearch"); if (s) { e.preventDefault(); s.focus(); s.select(); } }
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || "");
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !$("modal").hidden) {
        var btns = qa("#modalFoot .btn.primary,#modalFoot .btn.danger"); if (btns.length) { e.preventDefault(); btns[btns.length - 1].click(); }
      }
      if (e.altKey && !e.ctrlKey && $("modal").hidden) {
        var order = ["ir", "pr", "ddvo", "knjiga_ir", "knjiga_pr", "konti", "knjizbe", "parties", "analysis"];
        var n = parseInt(e.key, 10);
        if (n >= 1 && n <= order.length) { e.preventDefault(); loadView(order[n - 1]); }
        if (e.key === "ArrowLeft") { e.preventDefault(); $("btnPrevPeriod").click(); }
        if (e.key === "ArrowRight") { e.preventDefault(); $("btnNextPeriod").click(); }
      }
      if (e.key === "?" && !typing && $("modal").hidden) { e.preventDefault(); shortcutsHelp(); }
    });
  }

  function init() {
    // Pred odgovorom strežnika uporabi zadnjo lokalno izbiro (brez utripa); veljavna je vrednost iz nastavitev (boot.ui).
    var t = "light", look = "t5";
    try {
      t = localStorage.getItem("trops5.ui_tema") || localStorage.getItem("trops5.theme") || "light";
      look = localStorage.getItem("trops5.ui_videz") || "t5";
    } catch (_e) { /* ignore */ }
    applyTheme(t);
    applyLook(look);
    bind();
    status("Nalagam…", "busy");
    api("/api/boot").then(function (d) {
      if (d.ok === false) { toast(errText(d), "error"); status(errText(d), "error"); return; }
      applyBoot(d);
      if (d.ui) {
        applyLook(d.ui.ui_videz);
        var oldDark = false;
        try { oldDark = !localStorage.getItem("trops5.ui_tema") && localStorage.getItem("trops5.theme") === "dark"; } catch (_e) { /* ignore */ }
        if (oldDark && d.ui.ui_tema === "light") saveUiPref("ui_tema", "dark"); // prenos stare izbire iz 5.0
        else applyTheme(d.ui.ui_tema);
        try { localStorage.setItem("trops5.ui_videz", d.ui.ui_videz); } catch (_e) { /* ignore */ }
      }
      loadView("ir");
    }).catch(function (e) { toast("Strežnik ni dosegljiv: " + e, "error"); status("Strežnik ni dosegljiv.", "error"); });
  }

  window.TropsUI = { api: api, act: act, loadView: loadView, toast: toast, state: S, runJob: runJob };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
