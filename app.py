"""Pantalla web (Flask). Solo corre en esta computadora.

    python app.py      ->  abrir http://127.0.0.1:5000

Los archivos subidos se leen en memoria y NUNCA se guardan en disco.
Mientras la persona elige columnas (si el formato no se reconoce), el archivo
espera en memoria; el Excel de resultados también vive en memoria.
La interfaz está en inglés porque los clientes son negocios de EE. UU.
"""

import io
import secrets
from collections import OrderedDict

from flask import Flask, abort, render_template, request, send_file

from excel_report import save_report
from formats import FIELDS, load_formats, save_format, validate_columns
from matcher import money
from reader import UnknownColumns, find_header, parse_amount, read_rows
from reconcile import reconcile_files

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024   # máximo 5 MB por envío
app.jinja_env.filters["money"] = money

# Cosas en memoria, cada una con un código al azar:
# - REPORTS: Excels ya generados
# - PENDING: archivos subidos que esperan a que la persona elija las columnas
# Guardamos solo los últimos pocos para no llenar la memoria.
REPORTS = OrderedDict()
PENDING = OrderedDict()
MAX_KEPT = 20

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
    bank_file = request.files.get("bank")
    books_file = request.files.get("books")
    if not bank_file or not bank_file.filename or not books_file or not books_file.filename:
        return render_template("upload.html", error="Please choose both CSV files."), 400
    try:
        upload = {
            "bank": bank_file.read(), "books": books_file.read(),   # en memoria, nunca a disco
            "bank_name": bank_file.filename, "books_name": books_file.filename,
            # Saldos finales: opcionales
            "bank_balance": parse_amount(request.form.get("bank_balance", "")),
            "book_balance": parse_amount(request.form.get("book_balance", "")),
        }
    except ValueError as error:
        return render_template("upload.html", error=f"Ending balance: {error}"), 400
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
    return render_template("upload.html", error="Files are too large (limit is 5 MB)."), 413


if __name__ == "__main__":
    # 127.0.0.1 = solo esta computadora puede abrirlo. Nunca usar host="0.0.0.0".
    app.run(host="127.0.0.1", port=5000, debug=False)
