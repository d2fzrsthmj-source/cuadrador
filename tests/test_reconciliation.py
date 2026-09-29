"""Pruebas de la conciliación en formato estándar (saldos, partidas pendientes, diferencia)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from matcher import reconcile
from reader import Transaction
from reconcile import reconcile_files
from reconciliation import build_reconciliation, load_balances, swap_changes_by

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "sample_data"
WITH_ERROR = ROOT / "sample_data_error"


def run(folder):
    bank_balance, book_balance = load_balances(folder)
    return reconcile_files(folder / "bank.csv", folder / "books.csv", bank_balance, book_balance)


def test_clean_sample_reconciles_to_zero():
    result, recon = run(CLEAN)
    assert recon.is_complete
    assert recon.difference == Decimal("0.00")
    assert recon.is_balanced
    assert recon.hints() == []
    # Aun así, los casos para revisar siguen ahí para una persona
    assert len(result.review) >= 4


def test_clean_sample_reconciling_items():
    _, recon = run(CLEAN)
    # 3 depósitos en tránsito + los asientos que siguen en revisión
    assert {t.reference for t in recon.deposits_in_transit} >= {"INV-5003", "INV-5004", "INV-5005"}
    # 3 cheques sin cobrar + el pago a Riverside Lumber
    assert {t.reference for t in recon.outstanding_checks} == {"1040", "1041", "1042", "BILL-3002"}
    assert recon.fees_total == Decimal("27.00")        # 12.00 + 15.00 no registradas
    assert recon.interest_total == Decimal("1.87")
    assert [t.description for t in recon.bank_fees] == ["RETURNED ITEM FEE", "MONTHLY SERVICE FEE"]


def test_review_items_are_marked_as_pending():
    result, recon = run(CLEAN)
    duplicate = next(m for m in result.review if "duplicate" in m.reason)
    assert recon.is_pending(duplicate.bank[0])
    assert duplicate.bank[0] in recon.other_bank


def test_sample_with_error_points_to_swapped_digits():
    result, recon = run(WITH_ERROR)
    assert recon.difference == Decimal("-90.00")
    assert not recon.is_balanced
    hints = recon.hints()
    assert "swapped" in hints[0] and "$540.00" in hints[0] and "$450.00" in hints[0]
    assert "That explains the whole difference." in hints


def test_divisible_by_nine_hint_without_a_pair():
    # Un error de dígitos que el motor no puede emparejar (no hay nombre ni número en común)
    bank = [Transaction("bank", 2, date(2026, 8, 3), Decimal("-540.00"), "SOMETHING", "")]
    books = [Transaction("books", 2, date(2026, 8, 3), Decimal("-450.00"), "Other name", "")]
    result = reconcile(bank, books)
    recon = build_reconciliation(result, Decimal("1000.00") - Decimal("540.00"), Decimal("1000.00") - Decimal("450.00"))
    # Sin pareja, las dos líneas quedan como partidas pendientes y todo cuadra "de papel"
    assert recon.difference == Decimal("0.00")
    # Si el contador trae un saldo de libros distinto, aparece la pista del 9
    recon = build_reconciliation(result, Decimal("460.00"), Decimal("640.00"))
    assert recon.difference == Decimal("-90.00")
    assert any("divisible by 9" in h for h in recon.hints())


def test_missing_balances_give_no_difference():
    result, _ = reconcile_files(CLEAN / "bank.csv", CLEAN / "books.csv")
    recon = build_reconciliation(result)
    assert not recon.is_complete
    assert recon.difference is None and recon.adjusted_bank is None
    assert recon.hints() == []


def test_swap_changes_by():
    assert swap_changes_by(Decimal("450.00"), Decimal("90.00"))
    assert swap_changes_by(Decimal("-1243.56"), Decimal("9.00"))
    assert not swap_changes_by(Decimal("450.00"), Decimal("10.00"))


def test_load_balances_missing_file(tmp_path):
    assert load_balances(tmp_path) == (None, None)
