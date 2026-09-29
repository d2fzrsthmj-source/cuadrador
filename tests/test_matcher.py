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

from matcher import MATCHED, PROBABLE, REVIEW, is_transposition, money, name_similarity, reconcile
from reader import Transaction, read_transactions

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "sample_data"


# ---------- preparar: correr el motor una vez con los datos de ejemplo ----------

class Outcome:
    """Permite preguntar: ¿qué le pasó a la línea 12 del banco? ¿y al asiento INV-5003?"""

    def __init__(self, result):
        self.result = result
        self.bank = {}    # línea del banco -> (estado, Match o None)
        self.books = {}   # referencia del asiento -> (estado, Match o None)
        for match in result.matched + result.review:
            for t in match.bank:
                self.bank[t.line] = (match.status, match)
            for t in match.books:
                self.books[t.reference] = (match.status, match)
        for t in result.bank_only:
            self.bank[t.line] = ("Bank only", None)
        for t in result.books_only:
            self.books[t.reference] = ("Books only", None)


@pytest.fixture(scope="module")
def outcome():
    bank, _ = read_transactions(SAMPLES / "bank.csv", "bank")
    books, _ = read_transactions(SAMPLES / "books.csv", "books")
    return Outcome(reconcile(bank, books))


def expected_rows(case):
    with open(SAMPLES / "expected.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["case"] == str(case)]
    assert rows, f"expected.csv has no rows for case {case}"
    return rows


def check_case(outcome, case):
    """Revisa cada fila del caso: estado correcto y banco+libros en el MISMO resultado."""
    reasons = []
    for row in expected_rows(case):
        lines = [int(n) for n in row["bank_lines"].split(";") if n]
        refs = [r for r in row["book_refs"].split(";") if r]
        matches = set()
        for line in lines:
            status, match = outcome.bank[line]
            assert status == row["expected_status"], f"bank line {line}: {row['note']}"
            matches.add(id(match))
        for ref in refs:
            status, match = outcome.books[ref]
            assert status == row["expected_status"], f"book entry {ref}: {row['note']}"
            matches.add(id(match))
        if lines and refs:
            assert len(matches) == 1, f"bank and books should be together: {row['note']}"
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
    assert any("check 10" in r for r in reasons)
    assert any("reference 50" in r for r in reasons)


def test_case_5_two_entries_same_amount_is_ambiguous(outcome):
    [reason] = check_case(outcome, 5)
    assert "Can't tell" in reason


def test_case_6_bank_charges_not_recorded(outcome):
    check_case(outcome, 6)


def test_case_7_in_books_not_yet_in_bank(outcome):
    check_case(outcome, 7)


def test_case_8_partial_payment(outcome):
    [reason] = check_case(outcome, 8)
    assert "Partial payment" in reason and "$1,200.00 short" in reason


def test_case_9_one_payment_for_two_entries(outcome):
    [reason] = check_case(outcome, 9)
    assert "2 entries" in reason


def test_case_10_duplicate_bank_line(outcome):
    original_reason, copy_reason = check_case(outcome, 10)
    assert "duplicate" not in original_reason
    assert "duplicate" in copy_reason


# ---------- reglas generales ----------

def test_every_line_appears_exactly_once(outcome):
    result = outcome.result
    bank_lines, book_lines = [], []
    for match in result.matched + result.review:
        bank_lines += [t.line for t in match.bank]
        book_lines += [t.line for t in match.books]
    bank_lines += [t.line for t in result.bank_only]
    book_lines += [t.line for t in result.books_only]
    assert sorted(bank_lines) == list(range(2, 63))   # 61 líneas del banco, sin repetir
    assert sorted(book_lines) == list(range(2, 68))   # 66 asientos, sin repetir


def test_every_match_has_a_reason(outcome):
    for match in outcome.result.matched + outcome.result.review:
        assert match.reason.strip()


def test_statuses_are_in_the_right_list(outcome):
    assert all(m.status == MATCHED for m in outcome.result.matched)
    assert all(m.status in (PROBABLE, REVIEW) for m in outcome.result.review)


def tx(source, line, day, amount, description="", reference=""):
    return Transaction(source, line, date(2026, 8, day), Decimal(amount), description, reference)


def test_date_too_far_is_not_matched():
    bank = [tx("bank", 2, 20, "100.00", "MOBILE DEPOSIT")]
    books = [tx("books", 2, 1, "100.00", "Bluebird Bakery", "INV-1")]
    result = reconcile(bank, books)
    assert result.matched == [] and result.review == []
    assert len(result.bank_only) == 1 and len(result.books_only) == 1


def test_check_number_beats_date():
    # El cheque se cobró 20 días después: el número basta
    bank = [tx("bank", 2, 25, "-50.00", "CHECK 1042")]
    books = [tx("books", 2, 5, "-50.00", "Red Barn Hardware", "1042")]
    [match] = reconcile(bank, books).matched
    assert match.reason == "Same amount and check 1042 in the bank description"


def test_one_entry_two_bank_lines_is_not_matched_blindly():
    # Dos depósitos iguales (fechas distintas, no duplicados) y un solo asiento
    bank = [tx("bank", 2, 10, "300.00", "MOBILE DEPOSIT REF 1"),
            tx("bank", 3, 12, "300.00", "MOBILE DEPOSIT REF 2")]
    books = [tx("books", 2, 11, "300.00", "Bluebird Bakery", "INV-1")]
    result = reconcile(bank, books)
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
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "ok")
    monkeypatch.setattr(module, "ERROR_DIR", tmp_path / "error")
    module.main()
    for folder, saved in [("ok", SAMPLES), ("error", ROOT / "sample_data_error")]:
        for path in saved.iterdir():
            assert (tmp_path / folder / path.name).read_text() == path.read_text(), path


def test_transposed_digits():
    assert is_transposition(Decimal("540.00"), Decimal("450.00"))
    assert is_transposition(Decimal("-1234.56"), Decimal("-1243.56"))
    assert not is_transposition(Decimal("540.00"), Decimal("540.00"))
    assert not is_transposition(Decimal("540.00"), Decimal("541.00"))
    assert not is_transposition(Decimal("540.00"), Decimal("405.10"))


def test_transposed_check_is_paired_but_not_matched():
    bank = [tx("bank", 2, 17, "-540.00", "CHECK 1052")]
    books = [tx("books", 2, 12, "-450.00", "Red Barn Hardware", "1052")]
    result = reconcile(bank, books)
    [match] = result.review
    assert match.status == REVIEW and match.cleared
    assert match.discrepancy == Decimal("-90.00")
    assert "swapped" in match.reason and "check 1052" in match.reason
