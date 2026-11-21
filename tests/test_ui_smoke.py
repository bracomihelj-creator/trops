"""Brskalniški dimni test UI (Playwright + Chrome). Preskoči se, če Playwright ni nameščen."""
from __future__ import annotations

import threading

import pytest

from conftest import needs_real

pw = pytest.importorskip("playwright.sync_api")


@needs_real
def test_ui_smoke(motor21):
    import host

    srv = host.AppServer()
    srv.motor = motor21
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    errors: list[str] = []
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
            except Exception:
                try:
                    browser = p.chromium.launch(args=["--no-sandbox"])
                except Exception as exc:  # pragma: no cover
                    pytest.skip(f"Brskalnik ni na voljo: {exc}")
            page = browser.new_page(viewport={"width": 1480, "height": 940})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://{srv.allowed_host}/?ticket={srv.token}")
            page.wait_for_selector("#content tbody tr", timeout=15000)
            assert page.locator("#content tbody tr").count() == 186
            page.locator("#content tbody tr").first.dblclick()
            page.wait_for_selector("#modal:not([hidden])")
            assert "Uredi izdani račun" in page.inner_text("#modalTitle")
            page.keyboard.press("Escape")
            page.click("[data-view=ddvo]")
            page.wait_for_selector(".kpi.hero")
            assert "6.828,00" in page.inner_text("#kpis")
            for view in ("pr", "knjiga_ir", "knjiga_pr", "konti", "knjizbe", "parties", "analysis"):
                page.click(f"[data-view={view}]")
                page.wait_for_timeout(600)
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
    assert not errors, errors
