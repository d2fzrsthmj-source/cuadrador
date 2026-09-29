"""Pantalla web mínima (Flask). Solo corre en esta computadora.

    python app.py      ->  abrir http://127.0.0.1:5000

Los archivos subidos se leen en memoria y NUNCA se guardan en disco.
El Excel de resultados también vive en memoria, solo mientras el programa corre.
La interfaz está en inglés porque los clientes son negocios de EE. UU.
"""

import io
import secrets
from collections import OrderedDict

from flask import Flask, abort, render_template, request, send_file

from excel_report import save_report
from matcher import money
from reconcile import reconcile_files

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024   # máximo 5 MB por envío
app.jinja_env.filters["money"] = money

# Excels ya generados, en memoria: código al azar -> bytes del archivo.
# Guardamos solo los últimos pocos para no llenar la memoria.
REPORTS = OrderedDict()
MAX_REPORTS = 20


@app.get("/")
def upload_form():
    return render_template("upload.html")


@app.post("/reconcile")
def reconcile_upload():
    bank_file = request.files.get("bank")
    invoice_file = request.files.get("invoices")
    if not bank_file or not bank_file.filename or not invoice_file or not invoice_file.filename:
        return render_template("upload.html", error="Please choose both CSV files."), 400

    try:
        # .stream se lee directo en memoria; no se guarda en ninguna carpeta
        result = reconcile_files(bank_file.stream, invoice_file.stream)
    except ValueError as error:
        return render_template("upload.html", error=str(error)), 400

    excel = io.BytesIO()
    save_report(result, excel)
    token = secrets.token_urlsafe(16)
    REPORTS[token] = excel.getvalue()
    while len(REPORTS) > MAX_REPORTS:
        REPORTS.popitem(last=False)   # se borra el más viejo

    return render_template("results.html", result=result, token=token,
                           bank_name=bank_file.filename, invoice_name=invoice_file.filename)


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
