"""Pruebas del lector de CSV: fechas, montos raros, columnas y líneas rotas."""

import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from reader import parse_amount, parse_date, read_transactions

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


# ---------- fechas ----------

@pytest.mark.parametrize("text", ["08/05/2026", "2026-08-05", "8/5/2026", "08/05/26", " 08/05/2026 "])
def test_common_us_date_formats(text):
    assert parse_date(text) == date(2026, 8, 5)


@pytest.mark.parametrize("text", ["31/12/2026", "hello", "", "2026/13/01"])
def test_bad_dates_raise(text):
    with pytest.raises(ValueError):
        parse_date(text)


# ---------- montos ----------

@pytest.mark.parametrize("text, expected", [
    ("1234.50", "1234.50"),
    ("$1,234.50", "1234.50"),
    ("-975.00", "-975.00"),
    ("(975.00)", "-975.00"),
    ("($975.00)", "-975.00"),
    ("-$975.00", "-975.00"),
    ("$-975", "-975.00"),
    ("12.5", "12.50"),
    ("  3,000 ", "3000.00"),
])
def test_amount_formats(text, expected):
    amount = parse_amount(text)
    assert isinstance(amount, Decimal)
    assert amount == Decimal(expected)


@pytest.mark.parametrize("text", ["", "  ", "$"])
def test_empty_amount_is_none(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize("text", ["abc", "NaN", "Infinity", "1.2.3"])
def test_bad_amounts_raise(text):
    with pytest.raises(ValueError):
        parse_amount(text)


# ---------- archivos completos ----------

def csv_text(*lines):
    return io.StringIO("\n".join(lines) + "\n")


def test_debit_and_credit_columns():
    rows, bad = read_transactions(csv_text(
        "Posting Date,Description,Debit,Credit",
        "2026-08-01,CHECK 1042,$975.00,",
        "2026-08-02,ACH CREDIT BLUEBIRD BAKERY,,\"$1,850.00\"",
        "2026-08-03,FEE,-15.00,",   # algunos bancos ponen el débito con signo menos
    ), "bank")
    assert bad == []
    assert [r.amount for r in rows] == [Decimal("-975.00"), Decimal("1850.00"), Decimal("-15.00")]


def test_column_names_are_flexible_and_case_insensitive():
    rows, _ = read_transactions(csv_text(
        "TRANSACTION DATE,Memo,Check Number,Amount",
        "08/01/2026,Some payment,1042,-10.00",
    ), "bank")
    assert rows[0].description == "Some payment"
    assert rows[0].reference == "1042"


def test_custom_column_map():
    rows, bad = read_transactions(csv_text(
        "Fecha Pago,Cliente,Importe,Folio",
        "08/01/2026,Bluebird Bakery,100.00,INV-9",
    ), "books", column_map={"date": "Fecha Pago", "description": "Cliente",
                               "amount": "Importe", "reference": "Folio"})
    assert bad == []
    assert rows[0].date == date(2026, 8, 1)
    assert rows[0].description == "Bluebird Bakery"
    assert rows[0].amount == Decimal("100.00")
    assert rows[0].reference == "INV-9"


def test_broken_lines_are_set_aside_with_a_reason():
    rows, bad = read_transactions(csv_text(
        "Date,Description,Amount",
        "08/01/2026,GOOD LINE,10.00",
        "not a date,BAD DATE,10.00",
        "08/02/2026,BAD AMOUNT,ten dollars",
        "",
        "08/03/2026,NO AMOUNT,",
        "08/04/2026",
        "08/05/2026,ANOTHER GOOD LINE,-5.00",
    ), "bank")
    assert [r.description for r in rows] == ["GOOD LINE", "ANOTHER GOOD LINE"]
    assert [b.line for b in bad] == [3, 4, 6, 7]
    assert "date" in bad[0].reason
    assert "amount" in bad[1].reason
    assert "empty" in bad[2].reason
    assert "empty" in bad[3].reason


def test_line_numbers_match_the_file():
    rows, _ = read_transactions(csv_text(
        "Date,Description,Amount",
        "08/01/2026,A,1.00",
        "",
        "08/02/2026,B,2.00",
    ), "bank")
    assert [r.line for r in rows] == [2, 4]


def test_missing_date_column_is_a_clear_error():
    with pytest.raises(ValueError, match="date column"):
        read_transactions(csv_text("When,Description,Amount", "x,y,1"), "bank")


def test_missing_amount_column_is_a_clear_error():
    with pytest.raises(ValueError, match="Amount"):
        read_transactions(csv_text("Date,Description", "08/01/2026,y"), "bank")


def test_empty_file_is_a_clear_error():
    with pytest.raises(ValueError, match="empty"):
        read_transactions(io.StringIO(""), "bank")


def test_bytes_with_excel_bom():
    # Excel guarda los CSV con una marca invisible (BOM) al principio
    data = io.BytesIO("﻿Date,Description,Amount\n08/01/2026,A,1.00\n".encode("utf-8"))
    rows, bad = read_transactions(data, "bank")
    assert bad == [] and rows[0].amount == Decimal("1.00")


def test_both_sample_bank_formats_read_the_same():
    single, bad1 = read_transactions(SAMPLES / "bank.csv", "bank")
    split, bad2 = read_transactions(SAMPLES / "bank_debit_credit.csv", "bank")
    assert bad1 == [] and bad2 == []
    assert len(single) == 62
    assert [(t.date, t.amount) for t in single] == [(t.date, t.amount) for t in split]


def test_sample_books_read_with_negatives_in_parentheses():
    rows, bad = read_transactions(SAMPLES / "books.csv", "books")
    assert bad == []
    assert len(rows) == 67
    assert any(r.amount < 0 for r in rows) and any(r.amount > 0 for r in rows)
