"""Pruebas de los formatos de archivo: líneas antes del encabezado, mapeos guardados y la pantalla de columnas."""

import io
import re
from pathlib import Path

import pytest

import formats
from app import app
from formats import load_formats, save_format, validate_columns
from reader import UnknownColumns, find_header, read_rows, read_transactions

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "sample_data"


def csv_text(*lines):
    return io.StringIO("\n".join(lines) + "\n")


# ---------- líneas antes del encabezado ----------

def test_text_lines_before_the_header_are_skipped():
    rows, bad = read_transactions(csv_text(
        "Example Community Bank (fictional)",
        "Account ending in 0000",
        "",
        "Statement period: 08/01/2026 - 08/31/2026",
        "Date,Description,Amount",
        "08/01/2026,CHECK 1042,-10.00",
    ), "bank")
    assert bad == []
    assert len(rows) == 1 and rows[0].line == 6 and rows[0].amount == -10


def test_unknown_columns_error_lists_the_columns():
    with pytest.raises(UnknownColumns) as caught:
        read_transactions(csv_text("Bank of Nowhere (fictional)", "When,What,How Much", "08/01/2026,A,1.00"), "bank")
    assert caught.value.columns == ["When", "What", "How Much"]
    assert "date column" in str(caught.value)


# ---------- los 3 formatos de ejemplo ----------

def test_three_example_formats_are_saved():
    saved = load_formats()
    assert set(saved) == {"format_a", "format_b", "format_c"}
    assert "debit" in saved["format_b"] and "credit" in saved["format_b"]


@pytest.mark.parametrize("name", ["format_a", "format_b", "format_c"])
def test_each_format_reads_the_same_statement(name):
    path = SAMPLES / "formats" / f"{name}.csv"
    _, _, used = find_header(read_rows(path), formats=load_formats())
    assert used == name

    rows, bad = read_transactions(path, "bank", formats=load_formats())
    standard, _ = read_transactions(SAMPLES / "bank.csv", "bank")
    assert bad == []
    assert [(t.date, t.amount) for t in rows] == [(t.date, t.amount) for t in standard]


def test_format_a_reads_check_numbers_from_their_own_column():
    rows, _ = read_transactions(SAMPLES / "formats" / "format_a.csv", "bank", formats=load_formats())
    checks = [t for t in rows if t.description.startswith("CHECK ")]
    assert checks and all(t.reference == t.description.split()[1] for t in checks)


def test_standard_files_do_not_use_a_saved_format():
    _, _, used = find_header(read_rows(SAMPLES / "bank.csv"), formats=load_formats())
    assert used == "standard"


# ---------- guardar formatos ----------

def test_save_and_load_a_format(tmp_path):
    save_format("format_d", {"date": "When", "amount": "How Much", "description": ""}, folder=tmp_path)
    assert load_formats(tmp_path) == {"format_d": {"date": "When", "amount": "How Much"}}


@pytest.mark.parametrize("name", ["../evil", "Format D", "", "a" * 41])
def test_format_names_are_restricted(tmp_path, name):
    with pytest.raises(ValueError, match="lowercase"):
        save_format(name, {"date": "When", "amount": "How Much"}, folder=tmp_path)


def test_existing_format_is_not_overwritten(tmp_path):
    save_format("format_d", {"date": "When", "amount": "How Much"}, folder=tmp_path)
    with pytest.raises(ValueError, match="already exists"):
        save_format("format_d", {"date": "Other", "amount": "How Much"}, folder=tmp_path)


@pytest.mark.parametrize("columns, message", [
    ({"amount": "X"}, "date"),
    ({"date": "D"}, "amount"),
    ({"date": "D", "amount": "A", "debit": "B"}, "not both"),
])
def test_incomplete_mappings_are_rejected(columns, message):
    with pytest.raises(ValueError, match=message):
        validate_columns(columns)


# ---------- la pantalla para elegir columnas ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    # Los formatos que se guarden en estas pruebas van a una carpeta temporal
    for path in (ROOT / "mappings").glob("*.json"):
        (tmp_path / path.name).write_text(path.read_text())
    monkeypatch.setattr(formats, "MAPPINGS_DIR", tmp_path)
    app.config["TESTING"] = True
    return app.test_client()


STRANGE_BANK = (b"Bank of Nowhere (fictional)\n\nWhen,What,How Much\n"
                b"08/01/2026,ACH CREDIT BLUEBIRD BAKERY,100.00\n")
BOOKS = b"Date,Name,Num,Amount\n08/01/2026,Bluebird Bakery,INV-1,100.00\n"


def upload(client, bank):
    return client.post("/reconcile", content_type="multipart/form-data", data={
        "bank": (io.BytesIO(bank), "bank.csv"), "books": (io.BytesIO(BOOKS), "books.csv")})


def test_unknown_columns_show_the_mapping_screen(client):
    page = upload(client, STRANGE_BANK).get_data(as_text=True)
    assert "Which column is which?" in page
    assert '<option value="How Much"' in page
    assert "Books" not in page.split("<form")[1].split("legend>")[1]   # solo pregunta por el banco


def test_mapping_screen_reconciles_and_saves_the_format(client, tmp_path):
    page = upload(client, STRANGE_BANK).get_data(as_text=True)
    action = re.search(r'action="(/map/[^"]+)"', page).group(1)
    response = client.post(action, data={
        "bank-date": "When", "bank-description": "What", "bank-amount": "How Much",
        "bank-save_as": "format_d"})
    assert response.status_code == 200
    assert "Reconciliation results" in response.get_data(as_text=True)
    assert (tmp_path / "format_d.json").exists()

    # La próxima vez el archivo se reconoce solo
    assert "Reconciliation results" in upload(client, STRANGE_BANK).get_data(as_text=True)


def test_mapping_screen_rejects_incomplete_choices(client):
    page = upload(client, STRANGE_BANK).get_data(as_text=True)
    action = re.search(r'action="(/map/[^"]+)"', page).group(1)
    response = client.post(action, data={"bank-description": "What"})
    assert response.status_code == 400
    assert "Choose which column is the date." in response.get_data(as_text=True)


def test_expired_mapping_token(client):
    response = client.post("/map/nothing", data={})
    assert response.status_code == 400 and "expired" in response.get_data(as_text=True)
