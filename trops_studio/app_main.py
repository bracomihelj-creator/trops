from __future__ import annotations

import argparse
import sys
from pathlib import Path

from trops_studio.config import DEFAULT_DB
from trops_studio.db import Database
from trops_studio.money import ProjestError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trops Studio — IR/PR SQLite urejevalnik (Vasco / SQL TROPS)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Pot do SQLite baze")
    parser.add_argument("--self-test", action="store_true", help="Hitri testi brez GUI")
    return parser.parse_args(argv)


def self_test() -> None:
    from trops_studio.money import decimal_value, parse_date, tax_digits
    from datetime import date

    assert decimal_value("1.234,56") == decimal_value("1234.56")
    assert parse_date("17.07.2026") == date(2026, 7, 17)
    assert tax_digits("SI12345678") == "12345678"
    db = Database(Path(":memory:"))
    # sqlite :memory: with Path works differently - use tempfile
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.sqlite3")
        party_id = db.upsert_party({"name": "Test d.o.o.", "vat_id": "SI12345678", "tax_number": "12345678"})
        assert party_id > 0
        assert db.find_party_by_tax("SI12345678")["name"] == "Test d.o.o."
        ir_id = db.upsert_ir(
            {
                "book": "Darila",
                "seq": 1,
                "document_no": "A-1",
                "document_date": "2026-06-01",
                "party_name": "Test",
                "vat_id": "SI12345678",
                "net": "100",
                "vat_22": "22",
                "total": "122",
                "party_id": party_id,
            }
        )
        assert db.get_ir(ir_id)["document_no"] == "A-1"
        pr_id = db.upsert_pr(
            {
                "seq": 1,
                "document_no": "P-1",
                "internal_no": "260001",
                "supplier_name": "Dobavitelj",
                "vat_id": "SI12345678",
                "net_taxable": "100",
                "vat_22": "22",
                "vat_5": "5",
                "odhodek01": "4000",
                "placilo": "2200",
            }
        )
        row = db.get_pr(pr_id)
        assert row["vat_5"] == "5.00"
        db.upsert_account_rule(
            {
                "party_kind": "supplier",
                "match_tax": "12345678",
                "match_name": "Dobavitelj",
                "odhodek01": "4100",
                "placilo": "2200",
            }
        )
        rule = db.find_account_rule(vat_id="SI12345678")
        assert rule and rule["odhodek01"] == "4100"
        # Posodobitev istega pravila (ne nov insert).
        rid = db.upsert_account_rule(
            {
                "party_kind": "supplier",
                "match_tax": "12345678",
                "match_name": "Dobavitelj",
                "odhodek01": "6500",
                "placilo": "2200",
            }
        )
        assert rid == rule["id"]
        rule2 = db.find_account_rule(vat_id="SI12345678")
        assert rule2 and rule2["odhodek01"] == "6500"
        from trops_studio.accounts import resolve_pr_accounts, resolve_ir_account

        resolved = resolve_pr_accounts(db, vat_id="SI12345678", name="Dobavitelj")
        assert resolved["odhodek01"] == "6500"
        # Nova stranka → 4190
        fresh = resolve_pr_accounts(db, vat_id="SI99999999", name="Nova d.o.o.")
        assert fresh["odhodek01"] == "4190"
        assert resolve_ir_account(db, vat_id="", name="Neznan") == "7620"
        assert resolve_ir_account(db, vat_id="HR12345678901", name="Kupac Zagreb") == "76301"
        learned = db.learn_account_rules_from_rows()
        assert learned["pr"] >= 1
        db.close()
    print("Samopreizkus: OK")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        try:
            self_test()
            return 0
        except Exception as exc:
            print(f"Samopreizkus ni uspel: {exc}", file=sys.stderr)
            return 1
    try:
        from trops_studio.ui.app import run_app

        run_app(args.db)
        return 0
    except ProjestError as exc:
        print(f"Napaka: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
