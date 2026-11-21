"""Statična kontrola povezav UI (app.js) ↔ Python (host.py, Bridge)."""
from __future__ import annotations

import re
from pathlib import Path

import host

APP = Path(__file__).resolve().parents[1]
JS = (APP / "ui" / "app.js").read_text(encoding="utf-8")
HTML = (APP / "ui" / "index.html").read_text(encoding="utf-8")
HOST = (APP / "host.py").read_text(encoding="utf-8")


def _actions_used():
    names = set(re.findall(r'\bact\(\s*"([a-z_]+)"', JS))
    names |= set(re.findall(r'\brunJob\(\s*"([a-z_]+)"', JS))
    return names


def test_js_actions_exist_in_host():
    table = host._actions(object())
    missing = sorted(n for n in _actions_used() if n not in table)
    assert not missing, f"Akcije v app.js brez Python obdelave: {missing}"


def test_long_actions_are_registered():
    table = host._actions(object())
    assert set(host.LONG_ACTIONS) <= set(table)


def test_js_runjob_only_for_long_actions():
    run = set(re.findall(r'\brunJob\(\s*"([a-z_]+)"', JS))
    assert run <= set(host.LONG_ACTIONS), sorted(run - set(host.LONG_ACTIONS))


def test_js_endpoints_exist():
    paths = set(re.findall(r'(?:api|post)\(\s*"(/api/[a-z_/]+)', JS))
    paths |= {p.split("?")[0] for p in re.findall(r'url:\s*"(/api/[a-z_/?=A-Z]+)', JS)}
    paths |= {"/api/job"}
    served = set(re.findall(r'path == "(/api/[a-z_/]+)"', HOST))
    missing = sorted(p for p in paths if p.split("?")[0] not in served)
    assert not missing, missing


def test_bridge_methods_exist():
    used = set(re.findall(r'\bb\.([a-z_]+)\(', JS))
    missing = sorted(m for m in used if not hasattr(host.Bridge, m))
    assert not missing, missing


def test_html_ids_used_by_js_exist():
    ids_js = set(re.findall(r'\$\("([A-Za-z]+)"\)', JS))
    dynamic = {"chkHead", "btnMore", "selInfo", "viewSearch", "statusFilter", "formWarn", "mPath", "mAcc", "mRemember", "mTo", "mCc",
               "mSubj", "mPrev", "mReviewed", "mSqlDir", "mPickDir", "mSaveDir", "mYear", "mKisanal", "mSure", "btnMissing",
               "btnPartiesSync", "btnAnRefresh", "btnPickCo",
                   "btnPartyNew", "mApplyData", "pAjpes", "pResult", "pVies",
                   "pDupOpen", "pDupUpdate", "pDupCancel"}  # 5.1: opozorilo »Stranka že obstaja« (dinamično)
    ids_html = set(re.findall(r'id="([A-Za-z]+)"', HTML))
    missing = sorted(i for i in ids_js - dynamic if i not in ids_html)
    assert not missing, missing


def test_menu_actions_handled():
    acts = set(re.findall(r'data-act="([a-z_]+)"', HTML))
    handled = set(re.findall(r'case "([a-z_]+)":', JS))
    assert acts <= handled, sorted(acts - handled)


def test_nav_views_handled():
    views = set(re.findall(r'data-view="([a-z_]+)"', HTML))
    m = re.search(r"var VIEWS = \{(.*?)\n  \};", JS, re.S)
    assert m
    defined = set(re.findall(r"^\s{4}([a-z_]+):", m.group(1), re.M))
    assert views <= defined, sorted(views - defined)


def test_no_cdn_or_external_urls_in_ui():
    for text in (JS, HTML, (APP / "ui" / "app.css").read_text(encoding="utf-8")):
        assert not re.search(r'(src|href)=["\']https?://', text)
        assert "@import url(" not in text
