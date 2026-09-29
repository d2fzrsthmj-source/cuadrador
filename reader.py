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

# Cuántas filas del principio revisamos buscando el encabezado
MAX_HEADER_SCAN = 30


@dataclass
class Transaction:
    """Una línea ya leída, sea del banco o de facturas."""
    source: str          # "bank" o "books"
    line: int            # número de línea en el archivo (la 1 es el encabezado)
    date: date
    amount: Decimal
    description: str     # en el banco: la descripción; en los libros: el nombre (cliente, proveedor...)
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


class UnknownColumns(ValueError):
    """No encontramos las columnas de fecha y monto. Guarda las columnas del archivo
    para que la pantalla web pueda preguntarle a la persona cuál es cuál."""

    def __init__(self, message, columns):
        super().__init__(message)
        self.columns = columns


def match_columns(header, column_map=None):
    """Decide qué columna de esta fila corresponde a cada dato.

    Sin `column_map`, usa los nombres conocidos (DEFAULT_COLUMNS).
    Con `column_map` (por ejemplo {"date": "Fecha Pago", "amount": "Importe"}) busca
    exactamente esos nombres, y TODOS tienen que estar en la fila.
    Devuelve un dict dato -> posición de la columna, o None si esta fila no sirve.
    """
    names = [h.strip().lower() for h in header]
    found = {}
    if column_map:
        for field, column in column_map.items():
            if column.strip().lower() not in names:
                return None
            found[field] = names.index(column.strip().lower())
    else:
        for field, aliases in DEFAULT_COLUMNS.items():
            for alias in aliases:
                if alias in names:
                    found[field] = names.index(alias)
                    break
    has_amount = "amount" in found or "debit" in found or "credit" in found
    return found if "date" in found and has_amount else None


def find_header(rows, column_map=None, formats=None):
    """Busca la fila del encabezado, aunque haya líneas de texto antes (nombre del banco, etc.).

    Prueba, en orden: el mapeo que nos dieron; si no hay, los formatos guardados
    (mappings/*.json) y luego los nombres conocidos. Devuelve
    (posición de la fila del encabezado, columnas, nombre del formato usado).
    """
    if column_map:
        attempts = [("custom", column_map)]
    else:
        attempts = list((formats or {}).items()) + [("standard", None)]
    for name, mapping in attempts:
        for index, (_, row) in enumerate(rows[:MAX_HEADER_SCAN]):
            columns = match_columns(row, mapping)
            if columns:
                return index, columns, name

    # No encontramos nada: armar un mensaje claro con las columnas que sí hay
    header = guess_header(rows)
    columns_text = ", ".join(h.strip() for h in header)
    date_aliases = set(DEFAULT_COLUMNS["date"])
    if any(cell.strip().lower() in date_aliases for _, row in rows[:MAX_HEADER_SCAN] for cell in row):
        message = f"Could not find an Amount column (or Debit/Credit columns). Columns in the file: {columns_text}"
    else:
        message = f"Could not find a date column. Columns in the file: {columns_text}"
    raise UnknownColumns(message, [h.strip() for h in header if h.strip()])


def guess_header(rows):
    """La fila más probable de encabezado: la primera con más celdas llenas."""
    candidates = rows[:MAX_HEADER_SCAN]
    widest = max(sum(1 for c in row if c.strip()) for _, row in candidates)
    return next(row for _, row in candidates if sum(1 for c in row if c.strip()) == widest)


def read_rows(source_file):
    """Todas las filas no vacías del CSV, cada una con su número de línea en el archivo."""
    reader = csv.reader(io.StringIO(_open_text(source_file)))
    rows = [(reader.line_num, row) for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("The file is empty.")
    return rows


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


def read_transactions(source_file, source, column_map=None, formats=None):
    """Lee un CSV y devuelve (transacciones, líneas_con_problema).

    `source` es "bank" o "books". `column_map` fuerza un mapeo de columnas;
    `formats` son los mapeos guardados que se prueban si no se da ninguno.
    Si no se encuentran las columnas de fecha y monto, lanza UnknownColumns
    (un ValueError): en ese caso el archivo entero no sirve tal como está.
    """
    rows = read_rows(source_file)
    header_index, columns, _ = find_header(rows, column_map, formats)

    transactions, bad_lines = [], []
    for line, row in rows[header_index + 1:]:
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
