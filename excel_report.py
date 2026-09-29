"""Exporta el resultado del emparejamiento a un archivo Excel.

Hojas: Summary, Matched, Review, Unmatched bank, Unmatched invoices.
Los textos van en inglés porque el Excel es para los clientes (negocios de EE. UU.).
"""

from decimal import Decimal
from itertools import zip_longest

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

# Formato de dólares: negativos en rojo con signo menos
MONEY_FORMAT = '"$"#,##0.00;[Red]-"$"#,##0.00'
DATE_FORMAT = "mm/dd/yyyy"
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="2F5597")
MAX_COLUMN_WIDTH = 70

MATCH_HEADERS = ["Status", "Bank line", "Bank date", "Bank description", "Bank amount",
                 "Invoice #", "Invoice date", "Customer / vendor", "Invoice amount", "Reason"]


def match_rows(match):
    """Una fila por cada pareja banco/factura del grupo (un pago de 2 facturas ocupa 2 filas)."""
    rows = []
    for bank, invoice in zip_longest(match.bank, match.invoices):
        rows.append([
            match.status,
            bank.line if bank else None,
            bank.date if bank else None,
            bank.description if bank else None,
            bank.amount if bank else None,
            invoice.reference if invoice else None,
            invoice.date if invoice else None,
            invoice.description if invoice else None,
            invoice.amount if invoice else None,
            match.reason,
        ])
    return rows


def write_table(sheet, headers, rows):
    """Escribe encabezado + filas, da formato a fechas y dinero, y ajusta el ancho de columnas."""
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        sheet.append(row)
    sheet.freeze_panes = "A2"  # el encabezado queda fijo al bajar

    money_columns = {i for i, h in enumerate(headers) if "amount" in h.lower()}
    date_columns = {i for i, h in enumerate(headers) if "date" in h.lower()}
    for row in sheet.iter_rows(min_row=2):
        for i, cell in enumerate(row):
            if i in money_columns:
                cell.number_format = MONEY_FORMAT
            elif i in date_columns:
                cell.number_format = DATE_FORMAT
    autosize(sheet)


def autosize(sheet):
    """Ancho de cada columna según su texto más largo (con un tope)."""
    for column in sheet.columns:
        longest = 0
        for cell in column:
            if cell.value is None:
                continue
            if cell.number_format == MONEY_FORMAT:
                length = len(f"-${abs(cell.value):,.2f}")
            elif cell.number_format == DATE_FORMAT:
                length = 10
            else:
                length = len(str(cell.value))
            longest = max(longest, length)
        sheet.column_dimensions[column[0].column_letter].width = min(longest + 3, MAX_COLUMN_WIDTH)


def write_summary(sheet, result):
    sheet["A1"] = "Bank reconciliation"
    sheet["A1"].font = Font(bold=True, size=14)
    rows = [
        ("Matched", len(result.matched), None),
        ("Needs review", len(result.review), None),
        ("Not matched - bank lines", len(result.unmatched_bank), None),
        ("Not matched - invoices", len(result.unmatched_invoices), None),
        (None, None, None),
        ("Bank total", result.bank_total, MONEY_FORMAT),
        ("Invoices total", result.invoice_total, MONEY_FORMAT),
        ("Difference (bank - invoices)", result.difference, MONEY_FORMAT),
        (None, None, None),
        ("Not matched in bank, total", sum((t.amount for t in result.unmatched_bank), Decimal("0.00")), MONEY_FORMAT),
        ("Not matched invoices, total", sum((t.amount for t in result.unmatched_invoices), Decimal("0.00")), MONEY_FORMAT),
        ("Lines that could not be read", len(result.bad_lines), None),
    ]
    for offset, (label, value, number_format) in enumerate(rows, start=3):
        sheet.cell(row=offset, column=1, value=label)
        cell = sheet.cell(row=offset, column=2, value=value)
        if number_format:
            cell.number_format = number_format
        if label and label.startswith("Difference"):
            sheet.cell(row=offset, column=1).font = Font(bold=True)
            cell.font = Font(bold=True)

    # Si hubo líneas que no se pudieron leer, se listan abajo con su motivo
    if result.bad_lines:
        start = len(rows) + 5
        sheet.cell(row=start, column=1, value="Lines that could not be read").font = Font(bold=True)
        for offset, bad in enumerate(result.bad_lines, start=start + 1):
            file_name = "Bank" if bad.source == "bank" else "Invoices"
            sheet.cell(row=offset, column=1, value=f"{file_name} file, line {bad.line}")
            sheet.cell(row=offset, column=2, value=bad.reason)
            sheet.cell(row=offset, column=3, value=bad.raw)
    autosize(sheet)


def build_workbook(result):
    workbook = Workbook()
    write_summary(workbook.active, result)
    workbook.active.title = "Summary"

    write_table(workbook.create_sheet("Matched"), MATCH_HEADERS,
                [row for match in result.matched for row in match_rows(match)])
    write_table(workbook.create_sheet("Review"), MATCH_HEADERS,
                [row for match in result.review for row in match_rows(match)])
    write_table(workbook.create_sheet("Unmatched bank"),
                ["Bank line", "Date", "Description", "Amount"],
                [[t.line, t.date, t.description, t.amount] for t in result.unmatched_bank])
    write_table(workbook.create_sheet("Unmatched invoices"),
                ["Invoice line", "Date", "Customer / vendor", "Invoice #", "Amount"],
                [[t.line, t.date, t.description, t.reference, t.amount] for t in result.unmatched_invoices])
    return workbook


def save_report(result, destination):
    """Guarda el Excel. `destination` puede ser una ruta o un archivo en memoria (BytesIO)."""
    build_workbook(result).save(destination)
