"""Pruebas de la pantalla web (sin abrir el navegador: usa el cliente de pruebas de Flask)."""

import io
import re
from pathlib import Path

import pytest

from app import app
from reconciliation import load_balances

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def upload(client, bank_bytes, books_bytes, **balances):
    return client.post("/reconcile", content_type="multipart/form-data", data={
        "bank": (io.BytesIO(bank_bytes), "bank.csv"),
        "books": (io.BytesIO(books_bytes), "books.csv"),
        **balances,
    })


def test_upload_page(client):
    page = client.get("/").get_data(as_text=True)
    assert "Bank reconciliation" in page and 'type="file"' in page


def test_results_page_and_excel_download(client):
    bank_balance, book_balance = load_balances(SAMPLES)
    response = upload(client, (SAMPLES / "bank.csv").read_bytes(), (SAMPLES / "books.csv").read_bytes(),
                      bank_balance=str(bank_balance), book_balance=str(book_balance))
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Needs review" in page and "Not matched" in page
    assert "Adjusted bank balance" in page and "Reconciled" in page
    # Lo que no cuadra aparece antes que lo que cuadró, y lo que cuadró va plegado
    assert page.index("In the bank, not in the books") < page.index("<details>")

    link = re.search(r'href="(/download/[^"]+)"', page).group(1)
    excel = client.get(link)
    assert excel.status_code == 200
    assert excel.data[:2] == b"PK"   # un .xlsx es un zip por dentro


def test_missing_file_shows_error(client):
    response = client.post("/reconcile", content_type="multipart/form-data",
                           data={"bank": (io.BytesIO(b"x"), "bank.csv")})
    assert response.status_code == 400
    assert "Please choose the books file." in response.get_data(as_text=True)


def test_wrong_columns_ask_which_is_which(client):
    response = upload(client, b"Foo,Bar\n1,2\n", (SAMPLES / "books.csv").read_bytes())
    assert response.status_code == 200
    assert "Which column is which?" in response.get_data(as_text=True)


def test_empty_file_shows_error(client):
    response = upload(client, b"", (SAMPLES / "books.csv").read_bytes())
    assert response.status_code == 400
    assert "empty" in response.get_data(as_text=True)


def test_broken_lines_are_listed(client):
    bank = b"Date,Description,Amount\n08/01/2026,OK,10.00\nnope,BROKEN,5.00\n"
    response = upload(client, bank, b"Date,Name,Num,Amount\n08/01/2026,Bluebird Bakery,INV-1,10.00\n")
    page = response.get_data(as_text=True)
    assert "couldn" in page and "Can&#39;t read the date" in page


def test_unknown_download_is_404(client):
    assert client.get("/download/nothing").status_code == 404


def test_without_balances_asks_for_them(client):
    response = upload(client, (SAMPLES / "bank.csv").read_bytes(), (SAMPLES / "books.csv").read_bytes())
    assert "Ending balances needed" in response.get_data(as_text=True)


def test_sample_button_reconciles(client):
    page = client.post("/sample/clean").get_data(as_text=True)
    assert "Reconciled" in page and 'class="status good"' in page
    assert "sample_data/bank.csv" in page


def test_error_sample_button_shows_the_difference_in_red(client):
    page = client.post("/sample/error").get_data(as_text=True)
    assert 'class="status bad"' in page and "-$90.00" in page and "swapped" in page


def test_unknown_sample_is_404(client):
    assert client.post("/sample/secret").status_code == 404


def test_only_csv_files_are_accepted(client):
    response = client.post("/reconcile", content_type="multipart/form-data", data={
        "bank": (io.BytesIO(b"%PDF-1.7"), "statement.pdf"),
        "books": (io.BytesIO(b"Date,Name,Num,Amount\n"), "books.csv")})
    assert response.status_code == 400
    assert "must be a .csv or .xlsx file" in response.get_data(as_text=True)


def test_bad_balance_is_explained(client):
    response = upload(client, (SAMPLES / "bank.csv").read_bytes(), (SAMPLES / "books.csv").read_bytes(),
                      bank_balance="lots")
    assert response.status_code == 400
    assert "is not a number" in response.get_data(as_text=True)


def test_too_large_upload(client):
    big = b"x" * (6 * 1024 * 1024)
    response = upload(client, big, b"Date,Name,Num,Amount\n")
    assert response.status_code == 413
    assert "too large" in response.get_data(as_text=True)


def test_results_page_has_print_and_excel(client):
    page = client.post("/sample/clean").get_data(as_text=True)
    assert "window.print()" in page and "Download Excel" in page
    # Primero lo que hay que revisar y lo que no cuadra; lo que cuadró al final, plegado
    assert page.index("Needs review (") < page.index("Not matched (") < page.index("<summary>Matched")
