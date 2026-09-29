"""Pruebas del motor: una por cada uno de los 10 casos difíciles, más algunas reglas generales.

Los casos esperados salen de sample_data/expected.csv, que escribe el generador
de datos (tools/make_sample_data.py).
"""

import csv
import importlib.util
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from matcher import MATCHED, PROBABLE, REVIEW, money, name_similarity, reconcile
from reader import Transaction, read_transactions

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "sample_data"


# ---------- preparar: correr el motor una vez con los datos de ejemplo ----------

class Outcome:
    """Permite preguntar: ¿qué le pasó a la línea 12 del banco? ¿y a la factura INV-5003?"""

    def __init__(self, result):
        self.result = result
        self.bank = {}      # línea del banco -> (estado, Match o None)
        self.invoice = {}   # referencia de factura -> (estado, Match o None)
        for match in result.matched + result.review:
            for t in match.bank:
                self.bank[t.line] = (match.status, match)
            for t in match.invoices:
                self.invoice[t.reference] = (match.status, match)
        for t in result.unmatched_bank:
            self.bank[t.line] = ("Unmatched in bank", None)
        for t in result.unmatched_invoices:
            self.invoice[t.reference] = ("Unmatched invoice", None)


@pytest.fixture(scope="module")
def outcome():
    bank, _ = read_transactions(SAMPLES / "bank.csv", "bank")
    invoices, _ = read_transactions(SAMPLES / "invoices.csv", "invoice")
    return Outcome(reconcile(bank, invoices))


def expected_rows(case):
    with open(SAMPLES / "expected.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["case"] == str(case)]
    assert rows, f"expected.csv has no rows for case {case}"
    return rows


def check_case(outcome, case):
    """Revisa cada fila del caso: estado correcto y banco+factura en el MISMO resultado."""
    reasons = []
    for row in expected_rows(case):
        lines = [int(n) for n in row["bank_lines"].split(";") if n]
        refs = [r for r in row["invoice_refs"].split(";") if r]
        matches = set()
        for line in lines:
            status, match = outcome.bank[line]
            assert status == row["expected_status"], f"bank line {line}: {row['note']}"
            matches.add(id(match))
        for ref in refs:
            status, match = outcome.invoice[ref]
            assert status == row["expected_status"], f"invoice {ref}: {row['note']}"
            matches.add(id(match))
        if lines and refs:
            assert len(matches) == 1, f"bank and invoices should be together: {row['note']}"
        match = outcome.bank[lines[0]][1] if lines else None
        reasons.append(match.reason if match else "")
    return reasons


# ---------- los 10 casos ----------

def test_case_1_exact_match(outcome):
    reasons = check_case(outcome, 1)
    assert all("same date" in r for r in reasons)


def test_case_2_date_shifted_1_to_5_days(outcome):
    reasons = check_case(outcome, 2)
    assert all("apart" in r for r in reasons)


def test_case_3_name_written_differently(outcome):
    [reason] = check_case(outcome, 3)
    assert "similar name" in reason
    assert "J SMITH PLUMBING" in reason


def test_case_4_check_or_invoice_number_in_description(outcome):
    reasons = check_case(outcome, 4)
    assert "check 1042" in " | ".join(reasons)
    assert any("invoice" in r for r in reasons)


def test_case_5_two_invoices_same_amount_is_ambiguous(outcome):
    [reason] = check_case(outcome, 5)
    assert "Can't tell" in reason


def test_case_6_bank_charges_without_invoice(outcome):
    check_case(outcome, 6)


def test_case_7_unpaid_invoices(outcome):
    check_case(outcome, 7)


def test_case_8_partial_payment(outcome):
    [reason] = check_case(outcome, 8)
    assert "Partial payment" in reason and "$1,200.00 short" in reason


def test_case_9_one_payment_for_two_invoices(outcome):
    [reason] = check_case(outcome, 9)
    assert "2 invoices" in reason


def test_case_10_duplicate_bank_line(outcome):
    original_reason, copy_reason = check_case(outcome, 10)
    assert "duplicate" not in original_reason
    assert "duplicate" in copy_reason


# ---------- reglas generales ----------

def test_every_line_appears_exactly_once(outcome):
    result = outcome.result
    bank_lines, invoice_lines = [], []
    for match in result.matched + result.review:
        bank_lines += [t.line for t in match.bank]
        invoice_lines += [t.line for t in match.invoices]
    bank_lines += [t.line for t in result.unmatched_bank]
    invoice_lines += [t.line for t in result.unmatched_invoices]
    assert sorted(bank_lines) == list(range(2, 62))       # 60 líneas, sin repetir
    assert sorted(invoice_lines) == list(range(2, 59))    # 57 facturas, sin repetir


def test_every_match_has_a_reason(outcome):
    for match in outcome.result.matched + outcome.result.review:
        assert match.reason.strip()


def test_statuses_are_in_the_right_list(outcome):
    assert all(m.status == MATCHED for m in outcome.result.matched)
    assert all(m.status in (PROBABLE, REVIEW) for m in outcome.result.review)


def test_totals_use_decimal(outcome):
    assert isinstance(outcome.result.difference, Decimal)


def tx(source, line, day, amount, description="", reference=""):
    return Transaction(source, line, date(2026, 8, day), Decimal(amount), description, reference)


def test_date_too_far_is_not_matched():
    bank = [tx("bank", 2, 20, "100.00", "MOBILE DEPOSIT")]
    invoices = [tx("invoice", 2, 1, "100.00", "Bluebird Bakery", "INV-1")]
    result = reconcile(bank, invoices)
    assert result.matched == [] and result.review == []
    assert len(result.unmatched_bank) == 1 and len(result.unmatched_invoices) == 1


def test_check_number_beats_date():
    # El cheque se cobró 20 días después: el número basta
    bank = [tx("bank", 2, 25, "-50.00", "CHECK 1042")]
    invoices = [tx("invoice", 2, 5, "-50.00", "Red Barn Hardware", "1042")]
    [match] = reconcile(bank, invoices).matched
    assert match.reason == "Same amount and check 1042 in the bank description"


def test_one_invoice_two_bank_lines_is_not_matched_blindly():
    # Dos depósitos iguales (fechas distintas, no duplicados) y una sola factura
    bank = [tx("bank", 2, 10, "300.00", "MOBILE DEPOSIT REF 1"),
            tx("bank", 3, 12, "300.00", "MOBILE DEPOSIT REF 2")]
    invoices = [tx("invoice", 2, 11, "300.00", "Bluebird Bakery", "INV-1")]
    result = reconcile(bank, invoices)
    assert result.matched == []
    [review] = result.review
    assert len(review.bank) == 2 and "Can't tell" in review.reason


def test_name_similarity():
    assert name_similarity("ACH DEBIT J SMITH PLUMBING", "John Smith Plumbing LLC") > 0.8
    assert name_similarity("ACH DEBIT J SMITH PLUMBING", "Riverside Lumber Supply") < 0.5
    assert name_similarity("MOBILE DEPOSIT REF 553190", "Oak Hollow Apartments") == 0.0


def test_money_format():
    assert money(Decimal("1234.5")) == "$1,234.50"
    assert money(Decimal("-975")) == "-$975.00"


def test_sample_data_is_reproducible(tmp_path, monkeypatch):
    """El generador, con su semilla fija, produce exactamente los archivos guardados."""
    spec = importlib.util.spec_from_file_location("make_sample_data", ROOT / "tools" / "make_sample_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT_DIR", tmp_path)
    module.main()
    for name in ["bank.csv", "bank_debit_credit.csv", "invoices.csv", "expected.csv"]:
        assert (tmp_path / name).read_text() == (SAMPLES / name).read_text(), name
