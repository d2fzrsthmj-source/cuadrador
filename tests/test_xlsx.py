"""Pruebas de los archivos de Excel (.xlsx): mismo resultado que el CSV, fechas y montos."""

import io
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import Workbook

from app import app
from reader import read_transactions
from reconcile import reconcile_files
from reconciliation import load_balances

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "sample_data"


def xlsx_bytes(*rows):
    """Un .xlsx en memoria con estas filas (las celdas guardan el tipo que les demos)."""
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def summary(bank_file, books_file):
    result, recon = reconcile_files(bank_file, books_file, *load_balances(SAMPLES))
    return recon.difference, len(result.matched), len(result.review), result.unmatched_count


def test_sample_xlsx_gives_exactly_the_same_result_as_csv():
    from_csv = summary(SAMPLES / "bank.csv", SAMPLES / "books.csv")
    from_xlsx = summary(SAMPLES / "bank.xlsx", SAMPLES / "books.xlsx")
    assert from_xlsx == from_csv == (Decimal("0.00"), 53, 6, 10)


def test_sample_xlsx_reads_the_same_lines_as_csv():
    for name, source in [("bank", "bank"), ("books", "books")]:
        from_csv, _ = read_transactions(SAMPLES / f"{name}.csv", source)
        from_xlsx, bad = read_transactions(SAMPLES / f"{name}.xlsx", source)
        assert bad == []
        assert [(t.date, t.amount, t.description, t.reference) for t in from_xlsx] == \
               [(t.date, t.amount, t.description, t.reference) for t in from_csv]


def test_date_that_comes_as_datetime():
    data = xlsx_bytes(["Date", "Description", "Amount"], [datetime(2026, 8, 5, 0, 0), "CHECK 1042", -10])
    [row], bad = read_transactions(io.BytesIO(data), "bank")
    assert bad == [] and row.date == date(2026, 8, 5)


def test_float_amount_becomes_exact_decimal():
    data = xlsx_bytes(["Date", "Description", "Amount"], ["08/05/2026", "DEPOSIT", 540.1])
    [row], _ = read_transactions(io.BytesIO(data), "bank")
    assert row.amount == Decimal("540.10")
    assert str(row.amount) == "540.10"      # Decimal exacto, no 540.1000000000000227...


def test_xlsx_with_lines_before_the_header():
    data = xlsx_bytes(["Example Community Bank (fictional)"], [],
                      ["Posting Date", "Description", "Debit", "Credit"],
                      [datetime(2026, 8, 3), "WIRE TRANSFER FEE", 25, None])
    [row], _ = read_transactions(io.BytesIO(data), "bank")
    assert row.amount == Decimal("-25.00") and row.line == 4


def test_old_xls_file_is_rejected_by_the_reader():
    old_excel = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
    with pytest.raises(ValueError, match="Save the file as .xlsx or .csv"):
        read_transactions(io.BytesIO(old_excel), "bank")


def test_old_xls_file_is_rejected_by_the_web():
    app.config["TESTING"] = True
    response = app.test_client().post("/reconcile", content_type="multipart/form-data", data={
        "bank": (io.BytesIO(b"\xd0\xcf\x11\xe0"), "statement.xls"),
        "books": (io.BytesIO((SAMPLES / "books.csv").read_bytes()), "books.csv")})
    assert response.status_code == 400
    assert "Save the file as .xlsx or .csv" in response.get_data(as_text=True)


def test_web_accepts_xlsx_uploads():
    app.config["TESTING"] = True
    bank_balance, book_balance = load_balances(SAMPLES)
    response = app.test_client().post("/reconcile", content_type="multipart/form-data", data={
        "bank": (io.BytesIO((SAMPLES / "bank.xlsx").read_bytes()), "bank.xlsx"),
        "books": (io.BytesIO((SAMPLES / "books.xlsx").read_bytes()), "books.xlsx"),
        "bank_balance": str(bank_balance), "book_balance": str(book_balance)})
    page = response.get_data(as_text=True)
    assert response.status_code == 200 and 'class="status good"' in page
