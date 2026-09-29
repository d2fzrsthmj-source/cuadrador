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
    assert "choose both" in response.get_data(as_text=True)


def test_wrong_columns_show_error(client):
    response = upload(client, b"Foo,Bar\n1,2\n", (SAMPLES / "books.csv").read_bytes())
    assert response.status_code == 400
    assert "date column" in response.get_data(as_text=True)


def test_broken_lines_are_listed(client):
    bank = b"Date,Description,Amount\n08/01/2026,OK,10.00\nnope,BROKEN,5.00\n"
    response = upload(client, bank, b"Date,Name,Num,Amount\n08/01/2026,Bluebird Bakery,INV-1,10.00\n")
    page = response.get_data(as_text=True)
    assert "couldn" in page and "Can&#39;t read the date" in page


def test_unknown_download_is_404(client):
    assert client.get("/download/nothing").status_code == 404


def test_without_balances_asks_for_them(client):
    response = upload(client, (SAMPLES / "bank.csv").read_bytes(), (SAMPLES / "books.csv").read_bytes())
    assert "Enter both ending balances" in response.get_data(as_text=True)
