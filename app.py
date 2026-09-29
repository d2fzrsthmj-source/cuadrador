"""Pantalla web (Flask). Solo corre en esta computadora.

    python app.py      ->  abrir http://127.0.0.1:5001

(El puerto 5000 lo usa otra app de esta computadora.)

Los archivos subidos se leen en memoria y NUNCA se guardan en disco.
Mientras la persona elige columnas (si el formato no se reconoce), el archivo
espera en memoria; el Excel de resultados también vive en memoria.
La interfaz está en inglés porque los clientes son negocios de EE. UU.
"""

import io
import secrets
from collections import OrderedDict
from pathlib import Path

from flask import Flask, abort, render_template, request, send_file

from excel_report import save_report
from formats import FIELDS, load_formats, save_format, validate_columns
from matcher import money
from reader import UnknownColumns, find_header, parse_amount, read_rows
from reconcile import reconcile_files
from reconciliation import load_balances

app = Flask(__name__)
MAX_UPLOAD_MB = 5
ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024   # tope por envío (los dos archivos juntos)
app.jinja_env.filters["money"] = money

# Cosas en memoria, cada una con un código al azar:
# - REPORTS: Excels ya generados
# - PENDING: archivos subidos que esperan a que la persona elija las columnas
# Guardamos solo los últimos pocos para no llenar la memoria.
REPORTS = OrderedDict()
PENDING = OrderedDict()
MAX_KEPT = 20

# Datos de ejemplo (inventados) para los botones de demostración
ROOT = Path(__file__).resolve().parent
SAMPLES = {"clean": ROOT / "sample_data", "error": ROOT / "sample_data_error"}

FILE_LABELS = {"bank": "Bank statement", "books": "Books"}
FIELD_LABELS = {
    "date": "Date", "description": "Description / name", "amount": "Amount (one column)",
    "debit": "Debit / money out", "credit": "Credit / money in", "reference": "Check or reference number",
}


def remember(store, value):
    """Guarda algo en memoria con un código al azar y devuelve el código."""
    token = secrets.token_urlsafe(16)
    store[token] = value
    while len(store) > MAX_KEPT:
        store.popitem(last=False)   # se borra el más viejo
    return token


@app.get("/")
def upload_form():
    return render_template("upload.html")


@app.post("/reconcile")
def reconcile_upload():
    try:
        bank_name, bank_bytes = read_upload("bank", "bank statement")
        books_name, books_bytes = read_upload("books", "books")
        upload = {
            "bank": bank_bytes, "books": books_bytes,   # en memoria, nunca a disco
            "bank_name": bank_name, "books_name": books_name,
            # Saldos finales: opcionales
            "bank_balance": read_balance("bank_balance", "bank ending balance"),
            "book_balance": read_balance("book_balance", "book ending balance"),
        }
    except ValueError as error:
        return render_template("upload.html", error=str(error)), 400
    return process(upload)


def read_upload(field, label):
    """Revisa un archivo subido y devuelve (nombre, contenido en bytes). Lanza ValueError con un mensaje claro."""
    file = request.files.get(field)
    if not file or not file.filename:
        raise ValueError(f"Please choose the {label} file.")
    extension = Path(file.filename).suffix.lower()
    if extension == ".xls":
        raise ValueError(f"The {label} file is an old Excel file ('{file.filename}'). "
                         f"Save the file as .xlsx or .csv")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(f"The {label} file must be a .csv or .xlsx file (you chose '{file.filename}').")
    content = file.read()
    if not content.strip():
        raise ValueError(f"The {label} file is empty.")
    return file.filename, content


def read_balance(field, label):
    """Un saldo opcional escrito por la persona ('$93,505.90', '-120', vacío)."""
    text = request.form.get(field, "")
    try:
        return parse_amount(text)
    except ValueError:
        raise ValueError(f"The {label} '{text.strip()}' is not a number. Use something like 12,345.67.")


@app.route("/sample/<name>", methods=["GET", "POST"])
def sample(name):
    """Los botones de demostración: usan los datos inventados de sample_data/, sin subir nada."""
    folder = SAMPLES.get(name)
    if folder is None:
        abort(404)
    bank_balance, book_balance = load_balances(folder)
    upload = {
        "bank": (folder / "bank.csv").read_bytes(), "books": (folder / "books.csv").read_bytes(),
        "bank_name": f"{folder.name}/bank.csv", "books_name": f"{folder.name}/books.csv",
        "bank_balance": bank_balance, "book_balance": book_balance,
    }
    return process(upload)


def unknown_files(upload, columns):
    """Qué archivos no se reconocen: dict archivo -> columnas que tiene."""
    formats = load_formats()
    unknown = {}
    for which in ("bank", "books"):
        try:
            find_header(read_rows(io.BytesIO(upload[which])), columns.get(which), formats)
        except UnknownColumns as error:
            unknown[which] = error.columns
    return unknown


def process(upload, columns=None):
    """Concilia lo subido; si algún archivo tiene columnas desconocidas, pregunta primero."""
    columns = columns or {}
    try:
        unknown = unknown_files(upload, columns)
        if unknown:
            token = remember(PENDING, {"upload": upload, "columns": columns})
            return show_mapping(token, unknown)
        result, recon = reconcile_files(
            io.BytesIO(upload["bank"]), io.BytesIO(upload["books"]),
            upload["bank_balance"], upload["book_balance"],
            columns.get("bank"), columns.get("books"))
    except ValueError as error:
        return render_template("upload.html", error=str(error)), 400

    excel = io.BytesIO()
    save_report(result, recon, excel)
    token = remember(REPORTS, excel.getvalue())
    return render_template("results.html", result=result, recon=recon, token=token,
                           bank_name=upload["bank_name"], books_name=upload["books_name"])


def show_mapping(token, unknown, error=None, status=200):
    return render_template("mapping.html", token=token, unknown=unknown, error=error,
                           file_labels=FILE_LABELS, fields=FIELDS, field_labels=FIELD_LABELS,
                           chosen=request.form), status


@app.post("/map/<token>")
def apply_mapping(token):
    pending = PENDING.get(token)
    if pending is None:
        return render_template("upload.html", error="That upload expired. Please upload the files again."), 400
    upload, columns = pending["upload"], dict(pending["columns"])
    unknown = unknown_files(upload, columns)

    # Primero se revisan todos los mapeos; solo si todos están bien se guardan
    try:
        for which in unknown:
            mapping = {field: request.form.get(f"{which}-{field}", "") for field in FIELDS}
            columns[which] = validate_columns(mapping)
        for which in unknown:
            save_as = request.form.get(f"{which}-save_as", "").strip()
            if save_as:
                save_format(save_as, columns[which], description=f"Saved from the web ({FILE_LABELS[which]})")
    except ValueError as error:
        return show_mapping(token, unknown, error=str(error), status=400)

    PENDING.pop(token, None)
    return process(upload, columns)


@app.get("/download/<token>")
def download(token):
    data = REPORTS.get(token)
    if data is None:
        abort(404)
    return send_file(io.BytesIO(data), as_attachment=True, download_name="reconciliation.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.errorhandler(413)
def too_large(_error):
    return render_template("upload.html", error=f"The files are too large (limit is {MAX_UPLOAD_MB} MB in total)."), 413


if __name__ == "__main__":
    # 127.0.0.1 = solo esta computadora puede abrirlo. Nunca usar host="0.0.0.0".
    app.run(host="127.0.0.1", port=5001, debug=False)
