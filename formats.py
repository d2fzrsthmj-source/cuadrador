"""Formatos de archivo guardados (mapeos de columnas).

Cada formato es un archivo mappings/<nombre>.json que dice qué columna del CSV
es la fecha, la descripción, el monto (o débito y crédito) y la referencia:

    {
      "name": "format_a",
      "description": "Single amount column, preamble lines before the header",
      "columns": {"date": "Txn Date", "description": "Narrative", "amount": "Net Amount"}
    }

Los nombres son genéricos a propósito ("format_a", "format_b"...): no inventamos
formatos de bancos reales porque no los conocemos con certeza.
"""

import json
import re
from pathlib import Path

MAPPINGS_DIR = Path(__file__).resolve().parent / "mappings"
FIELDS = ["date", "description", "amount", "debit", "credit", "reference"]
NAME_PATTERN = re.compile(r"^[a-z0-9_]{1,40}$")


def load_formats(folder=None):
    """Todos los formatos guardados: dict nombre -> {dato: nombre de columna}."""
    folder = Path(folder or MAPPINGS_DIR)
    formats = {}
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text())
        formats[data["name"]] = data["columns"]
    return formats


def validate_columns(columns):
    """Revisa que un mapeo tenga lo mínimo. Devuelve el mapeo limpio o lanza ValueError."""
    clean = {field: name.strip() for field, name in columns.items() if field in FIELDS and name and name.strip()}
    if "date" not in clean:
        raise ValueError("Choose which column is the date.")
    if "amount" not in clean and not ("debit" in clean or "credit" in clean):
        raise ValueError("Choose the amount column, or the debit and credit columns.")
    if "amount" in clean and ("debit" in clean or "credit" in clean):
        raise ValueError("Choose either one amount column or debit/credit columns, not both.")
    return clean


def save_format(name, columns, description="", folder=None):
    """Guarda un mapeo con un nombre (solo minúsculas, números y _). Devuelve la ruta."""
    name = name.strip().lower()
    if not NAME_PATTERN.match(name):
        raise ValueError("Format names can only use lowercase letters, numbers and _ (e.g. format_d).")
    folder = Path(folder or MAPPINGS_DIR)
    folder.mkdir(exist_ok=True)
    data = {"name": name, "description": description, "columns": validate_columns(columns)}
    path = folder / f"{name}.json"
    if path.exists():
        raise ValueError(f"A format called '{name}' already exists. Choose another name.")
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path
