"""Uso desde la terminal.

    python reconcile.py bank.csv invoices.csv
    python reconcile.py bank.csv invoices.csv --output mi_reporte.xlsx

Imprime un resumen y lo que hay que revisar, y guarda un Excel
(por defecto en output/reconciliation.xlsx).
"""

import argparse
import sys
from pathlib import Path

from excel_report import save_report
from matcher import money, reconcile
from reader import read_transactions

DEFAULT_OUTPUT = Path("output") / "reconciliation.xlsx"


def reconcile_files(bank_file, invoice_file):
    """Lee los dos archivos y los empareja. Acepta rutas o archivos abiertos."""
    bank, bad_bank = read_transactions(bank_file, "bank")
    invoices, bad_invoices = read_transactions(invoice_file, "invoice")
    result = reconcile(bank, invoices)
    result.bad_lines = bad_bank + bad_invoices
    return result


def print_summary(result):
    print("Bank reconciliation")
    print("-" * 50)
    print(f"  Matched:        {len(result.matched):>4}")
    print(f"  Needs review:   {len(result.review):>4}")
    print(f"  Not matched:    {result.unmatched_count:>4}   "
          f"({len(result.unmatched_bank)} bank lines, {len(result.unmatched_invoices)} invoices)")
    print(f"  Difference:     {money(result.difference)}   (bank total - invoices total)")
    if result.bad_lines:
        print(f"  Could not read: {len(result.bad_lines):>4} lines")

    if result.review:
        print("\nNEEDS REVIEW")
        for match in result.review:
            lines = ", ".join(f"bank line {t.line}" for t in match.bank)
            print(f"  [{match.status}] {lines}: {match.reason}")
    if result.unmatched_bank:
        print("\nIN THE BANK, NO INVOICE")
        for t in result.unmatched_bank:
            print(f"  line {t.line:>3}  {t.date:%m/%d/%Y}  {money(t.amount):>12}  {t.description}")
    if result.unmatched_invoices:
        print("\nINVOICES NOT FOUND IN THE BANK")
        for t in result.unmatched_invoices:
            print(f"  {t.reference:>10}  {t.date:%m/%d/%Y}  {money(t.amount):>12}  {t.description}")
    if result.bad_lines:
        print("\nLINES THAT COULD NOT BE READ")
        for bad in result.bad_lines:
            print(f"  {bad.source} file, line {bad.line}: {bad.reason}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Match bank lines with invoices.")
    parser.add_argument("bank", help="bank CSV file")
    parser.add_argument("invoices", help="invoices / expected payments CSV file")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT), help="Excel file to create")
    args = parser.parse_args(argv)

    try:
        result = reconcile_files(args.bank, args.invoices)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print_summary(result)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_report(result, output)
    print(f"\nExcel saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
