"""Lector de archivos CSV.

Lee el CSV del banco o el de facturas y convierte cada línea a una forma única
(`Transaction`): fecha, monto (Decimal, positivo = entra dinero, negativo = sale),
descripción y referencia.

Las líneas que no se pueden leer NO detienen el programa: se guardan aparte como
`BadLine`, con el motivo explicado.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Nombres de columna que reconocemos para cada dato (en minúsculas).
# Se usa el primero que aparezca en el archivo.
DEFAULT_COLUMNS = {
    "date": ["date", "posting date", "post date", "posted date", "transaction date", "trans date"],
    "description": ["description", "transaction description", "memo", "details",
                    "payee", "name", "customer", "vendor", "customer/vendor"],
    "amount": ["amount", "transaction amount", "amount ($)"],
    "debit": ["debit", "debits", "debit amount", "withdrawal", "withdrawals"],
    "credit": ["credit", "credits", "credit amount", "deposit", "deposits"],
    "reference": ["num", "no.", "number", "ref", "reference", "check number", "check #",
                  "check no", "invoice", "invoice #", "invoice number", "invoice no", "doc number"],
}

# Formatos de fecha que aceptamos (los comunes en EE. UU.)
DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y"]

CENT = Decimal("0.01")


@dataclass
class Transaction:
    """Una línea ya leída, sea del banco o de facturas."""
    source: str          # "bank" o "invoice"
    line: int            # número de línea en el archivo (la 1 es el encabezado)
    date: date
    amount: Decimal
    description: str     # en el banco: la descripción; en facturas: el cliente o proveedor
    reference: str = ""  # número de cheque o de factura, si lo hay


@dataclass
class BadLine:
    """Una línea que no se pudo leer, con el motivo."""
    source: str
    line: int
    reason: str
    raw: str


def parse_date(text):
    """Convierte '08/05/2026' o '2026-08-05' en un objeto date. Si no puede, lanza ValueError."""
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Can't read the date '{text}'")


def parse_amount(text):
    """Convierte un monto escrito como texto en Decimal.

    Acepta '$1,234.50', '-975.00', '(975.00)' y '-$975.00'.
    Devuelve None si la celda está vacía. Lanza ValueError si no es un número.
    """
    original = text
    text = text.strip().replace("$", "").replace(",", "").replace(" ", "")
    if text == "":
        return None
    negative = False
    # Paréntesis = negativo, como en los reportes contables: (975.00)
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Can't read the amount '{original.strip()}'")
    # Decimal acepta 'NaN' o 'Infinity'; eso no es dinero
    if not amount.is_finite():
        raise ValueError(f"Can't read the amount '{original.strip()}'")
    if negative:
        amount = -amount
    return amount.quantize(CENT)


def find_columns(header, column_map=None):
    """Decide qué columna del archivo corresponde a cada dato.

    `column_map` permite forzar nombres, por ejemplo {"date": "Fecha Pago"}.
    Devuelve un dict dato -> posición de la columna.
    """
    names = [h.strip().lower() for h in header]
    found = {}
    for field, aliases in DEFAULT_COLUMNS.items():
        if column_map and field in column_map:
            aliases = [column_map[field].strip().lower()]
        for alias in aliases:
            if alias in names:
                found[field] = names.index(alias)
                break

    columns_text = ", ".join(h.strip() for h in header)
    if "date" not in found:
        raise ValueError(f"Could not find a date column. Columns in the file: {columns_text}")
    if "amount" not in found and not ("debit" in found or "credit" in found):
        raise ValueError(f"Could not find an Amount column (or Debit/Credit columns). "
                         f"Columns in the file: {columns_text}")
    return found


def _cell(row, columns, field):
    """El texto de una celda, o '' si la columna no existe o la fila es corta."""
    index = columns.get(field)
    if index is None or index >= len(row):
        return ""
    return row[index]


def _row_amount(row, columns):
    """El monto de la fila: de la columna Amount, o Credit menos Debit."""
    if "amount" in columns:
        amount = parse_amount(_cell(row, columns, "amount"))
        if amount is None:
            raise ValueError("The amount is empty")
        return amount
    debit = parse_amount(_cell(row, columns, "debit"))
    credit = parse_amount(_cell(row, columns, "credit"))
    if debit is None and credit is None:
        raise ValueError("Both Debit and Credit are empty")
    # Algunos bancos escriben los débitos con signo menos y otros sin él: usamos abs()
    return abs(credit or Decimal("0.00")) - abs(debit or Decimal("0.00"))


def _open_text(source_file):
    """Acepta una ruta (str/Path) o un archivo ya abierto; devuelve texto."""
    if isinstance(source_file, (str, Path)):
        # utf-8-sig quita la marca invisible (BOM) que pone Excel al guardar CSV
        with open(source_file, encoding="utf-8-sig", newline="") as f:
            return f.read()
    content = source_file.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig", errors="replace")
    return content


def read_transactions(source_file, source, column_map=None):
    """Lee un CSV y devuelve (transacciones, líneas_con_problema).

    `source` es "bank" o "invoice". Si falta una columna esencial (fecha o monto),
    lanza ValueError: en ese caso el archivo entero no sirve.
    """
    reader = csv.reader(io.StringIO(_open_text(source_file)))

    # El encabezado es la primera fila que no esté vacía
    header = None
    for row in reader:
        if any(cell.strip() for cell in row):
            header = row
            break
    if header is None:
        raise ValueError("The file is empty.")
    columns = find_columns(header, column_map)

    transactions, bad_lines = [], []
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue  # línea en blanco: se ignora sin avisar
        line = reader.line_num
        try:
            transactions.append(Transaction(
                source=source,
                line=line,
                date=parse_date(_cell(row, columns, "date")),
                amount=_row_amount(row, columns),
                description=_cell(row, columns, "description").strip(),
                reference=_cell(row, columns, "reference").strip(),
            ))
        except ValueError as error:
            bad_lines.append(BadLine(source, line, str(error), ",".join(row)))
    return transactions, bad_lines

