"""Uso desde la terminal.

    python reconcile.py sample_data/bank.csv sample_data/books.csv
    python reconcile.py bank.csv books.csv --bank-balance 52,310.18 --book-balance 49,870.44
    python reconcile.py bank.csv books.csv --output mi_reporte.xlsx

El segundo archivo es el registro de la cuenta en los libros (o una lista de facturas).
Los saldos finales son opcionales. Si no se dan y junto al archivo del banco hay un
balances.json (como en los datos de ejemplo), se usan esos.

Imprime la conciliación y lo que hay que revisar, y guarda un Excel
(por defecto en output/reconciliation.xlsx).
"""

import argparse
import sys
from pathlib import Path

from excel_report import save_report
from formats import load_formats
from matcher import money, reconcile
from reader import parse_amount, read_transactions
from reconciliation import build_reconciliation, load_balances

DEFAULT_OUTPUT = Path("output") / "reconciliation.xlsx"


def reconcile_files(bank_file, books_file, bank_balance=None, book_balance=None,
                    bank_columns=None, books_columns=None):
    """Lee los dos archivos, los empareja y arma la conciliación. Devuelve (result, recon).

    Si no se da un mapeo de columnas, se prueban los formatos guardados en mappings/
    y luego los nombres de columna conocidos.
    """
    formats = load_formats()
    bank, bad_bank = read_transactions(bank_file, "bank", bank_columns, formats)
    books, bad_books = read_transactions(books_file, "books", books_columns, formats)
    result = reconcile(bank, books)
    result.bad_lines = bad_bank + bad_books
    return result, build_reconciliation(result, bank_balance, book_balance)


def print_reconciliation(recon):
    print("Bank reconciliation")
    print("-" * 56)
    for label, amount, kind in recon.lines():
        if label in ("Book ending balance", "Difference"):
            print()
        shown = money(amount) if amount is not None else "(not given)"
        print(f"  {label:<34}{shown:>18}")
    if not recon.is_complete:
        print("\n  Give both ending balances to get the difference "
              "(--bank-balance and --book-balance).")
    elif recon.is_balanced:
        print("\n  RECONCILED: the difference is $0.00.")
    else:
        print("\n  NOT RECONCILED: the difference is not $0.00.")
        for hint in recon.hints():
            print(f"  - {hint}")


def print_details(result, recon):
    print(f"\nMatched: {len(result.matched)}   Needs review: {len(result.review)}   "
          f"Not matched: {result.unmatched_count} "
          f"({len(result.bank_only)} bank only, {len(result.books_only)} books only)")

    if result.review:
        print("\nNEEDS REVIEW")
        for match in result.review:
            lines = ", ".join(f"bank line {t.line}" for t in match.bank) or "no bank line"
            print(f"  [{match.status}] {lines}: {match.reason}")
    if result.bank_only:
        print("\nIN THE BANK, NOT IN THE BOOKS")
        for t in result.bank_only:
            print(f"  line {t.line:>3}  {t.date:%m/%d/%Y}  {money(t.amount):>12}  {t.description}")
    if result.books_only:
        print("\nIN THE BOOKS, NOT IN THE BANK")
        for t in result.books_only:
            print(f"  {t.reference:>10}  {t.date:%m/%d/%Y}  {money(t.amount):>12}  {t.description}")
    if result.bad_lines:
        print("\nLINES THAT COULD NOT BE READ")
        for bad in result.bad_lines:
            print(f"  {bad.source} file, line {bad.line}: {bad.reason}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Reconcile a bank statement against the books.")
    parser.add_argument("bank", help="bank statement CSV file")
    parser.add_argument("books", help="books (account register) or invoice list CSV file")
    parser.add_argument("--bank-balance", help="ending balance on the bank statement")
    parser.add_argument("--book-balance", help="ending balance in the books")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT), help="Excel file to create")
    args = parser.parse_args(argv)

    try:
        bank_balance = parse_amount(args.bank_balance) if args.bank_balance else None
        book_balance = parse_amount(args.book_balance) if args.book_balance else None
        if bank_balance is None and book_balance is None:
            bank_balance, book_balance = load_balances(Path(args.bank).parent)
            if bank_balance is not None:
                print(f"(Ending balances taken from {Path(args.bank).parent / 'balances.json'})\n")
        result, recon = reconcile_files(args.bank, args.books, bank_balance, book_balance)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print_reconciliation(recon)
    print_details(result, recon)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_report(result, recon, output)
    print(f"\nExcel saved to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
