"""Genera datos de ejemplo INVENTADOS para probar Cuadrador.

Empresa ficticia: "Maple Street Contracting". Todos los clientes, proveedores,
montos y descripciones son inventados. No hay ningún dato real aquí.

Crea dos juegos de datos:

  sample_data/             cuadra perfecto (diferencia $0.00, salvo lo que hay que revisar)
    bank.csv               movimientos del banco (una columna de monto)
    bank_debit_credit.csv  los mismos movimientos, con columnas Debit y Credit
    books.csv              el registro de la cuenta en los libros (estilo QuickBooks)
    bank.xlsx, books.xlsx  los mismos datos en Excel (fechas y montos como celdas de Excel)
    balances.json          saldo final del banco y de los libros
    expected.csv           la "hoja de respuestas": qué debe pasar con cada caso difícil
    formats/format_*.csv   el mismo estado de cuenta en 3 formatos distintos (ver mappings/),
                           con líneas de texto antes del encabezado

  sample_data_error/       lo mismo, pero con un error escondido en los libros:
                           un cheque de $540.00 registrado como $450.00 (dígitos invertidos)

Uso:  python tools/make_sample_data.py
Usa una semilla fija, así que siempre genera exactamente los mismos archivos.
"""

import copy
import csv
import io
import json
import random
import re
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

SEED = 20260801
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "sample_data"
ERROR_DIR = ROOT / "sample_data_error"

STATEMENT_START = date(2026, 8, 1)
STATEMENT_END = date(2026, 8, 31)
# Saldo inicial igual en banco y libros (la conciliación de julio quedó cuadrada)
OPENING_BALANCE = Decimal("48250.00")

# Clientes ficticios (nos pagan: montos positivos)
CUSTOMERS = [
    "Harbor View Dental", "Bluebird Bakery", "Lakeside Vet Clinic",
    "Copper Kettle Diner", "Pinecone Property Mgmt", "Willow Creek Chapel",
    "Fox Run Townhomes", "Maple Leaf Laundromat", "Gray Owl Bookshop",
    "Quiet Brook Inn",
]
# Proveedores ficticios (les pagamos: montos negativos)
VENDORS = [
    "Quick Fix Electric", "Northside Concrete Co", "Evergreen Tool Rental",
    "Summit Roofing Supply", "Metro Waste Hauling", "Clearpane Glass Inc",
    "Red Barn Hardware",
]


class SampleBuilder:
    """Va juntando líneas de banco, asientos de los libros y casos esperados."""

    def __init__(self):
        self.rng = random.Random(SEED)
        self.bank = []        # cada línea: dict con date, description, amount
        self.books = []       # cada asiento: dict con date, name, num, amount
        self.cases = []       # cada caso: dict con case, note, bank (lista de dicts), refs, expected
        self.used_amounts = set()
        self.next_inv = 5001
        self.next_check = 1040
        self.next_bill = 3001
        self.transposed = None   # el asiento que en sample_data_error se registra mal

    # ---------- ayudantes ----------

    def unique_amount(self, low, high):
        """Un monto al azar con centavos que no se haya usado antes (evita empates por accidente)."""
        while True:
            cents = self.rng.randint(low * 100, high * 100)
            amount = Decimal(cents) / 100
            if amount not in self.used_amounts:
                self.used_amounts.add(amount)
                return amount

    def reserve(self, *amounts):
        """Aparta montos fijos para que ningún monto al azar coincida con ellos."""
        self.used_amounts.update(abs(Decimal(a)) for a in amounts)

    def random_day(self):
        return STATEMENT_START + timedelta(days=self.rng.randint(0, 23))

    def invoice_ref(self):
        ref = f"INV-{self.next_inv}"
        self.next_inv += 1
        return ref

    def check_ref(self):
        ref = str(self.next_check)
        self.next_check += 1
        return ref

    def bill_ref(self):
        ref = f"BILL-{self.next_bill}"
        self.next_bill += 1
        return ref

    def add_book(self, day, name, num, amount):
        entry = {"date": day, "name": name, "num": num, "amount": Decimal(amount)}
        self.books.append(entry)
        return entry

    def add_bank(self, day, description, amount):
        # El banco no muestra fechas después del cierre del estado de cuenta
        line = {"date": min(day, STATEMENT_END), "description": description, "amount": Decimal(amount)}
        self.bank.append(line)
        return line

    def add_case(self, case, note, bank_lines, refs, expected):
        self.cases.append({"case": case, "note": note, "bank": bank_lines,
                           "refs": refs, "expected": expected})

    @staticmethod
    def bank_name(name):
        """Así escribe el banco los nombres: mayúsculas y cortado a 18 letras."""
        return name.upper()[:18].strip()

    def ppd_id(self):
        return str(self.rng.randint(1000000, 9999999))

    # ---------- casos normales (1, 2 y 4) ----------

    def routine(self):
        # Caso 1: mismo monto y misma fecha (depósitos de clientes)
        for _ in range(8):
            name = self.rng.choice(CUSTOMERS)
            day, amount, ref = self.random_day(), self.unique_amount(350, 6500), self.invoice_ref()
            self.add_book(day, name, ref, amount)
            line = self.add_bank(day, f"ACH CREDIT {self.bank_name(name)} PPD ID {self.ppd_id()}", amount)
            self.add_case(1, "Exact match: same amount, same date", [line], [ref], "Matched")

        # Caso 1 también con proveedores pagados por ACH el mismo día
        for _ in range(3):
            name = self.rng.choice(VENDORS)
            day, amount, ref = self.random_day(), -self.unique_amount(80, 3500), self.bill_ref()
            self.add_book(day, name, ref, amount)
            line = self.add_bank(day, f"ACH DEBIT {self.bank_name(name)}", amount)
            self.add_case(1, "Exact match: same amount, same date", [line], [ref], "Matched")

        # Caso 2: mismo monto, fecha corrida de 1 a 5 días
        for i in range(16):
            shift = self.rng.randint(1, 5)
            if i < 12:
                name = self.rng.choice(CUSTOMERS)
                day, amount, ref = self.random_day(), self.unique_amount(350, 6500), self.invoice_ref()
                # Algunos depósitos no traen nombre (depósito móvil de un cheque)
                if self.rng.random() < 0.3:
                    desc = f"MOBILE DEPOSIT REF {self.rng.randint(100000, 999999)}"
                else:
                    desc = f"ACH CREDIT {self.bank_name(name)} PPD ID {self.ppd_id()}"
            else:
                name = self.rng.choice(VENDORS)
                day, amount, ref = self.random_day(), -self.unique_amount(80, 3500), self.bill_ref()
                desc = f"ACH DEBIT {self.bank_name(name)}"
            self.add_book(day, name, ref, amount)
            line = self.add_bank(day + timedelta(days=shift), desc, amount)
            self.add_case(2, f"Same amount, bank date {shift} day(s) later", [line], [ref], "Matched")

        # Caso 4a: número de cheque en la descripción ("CHECK 1042").
        # Algunos cheques tardan más de 5 días en cobrarse: el número de cheque basta.
        for _ in range(12):
            name = self.rng.choice(VENDORS)
            day, amount, ref = self.random_day(), -self.unique_amount(80, 3500), self.check_ref()
            self.add_book(day, name, ref, amount)
            line = self.add_bank(day + timedelta(days=self.rng.randint(1, 12)), f"CHECK {ref}", amount)
            self.add_case(4, f"Check number {ref} in bank description", [line], [ref], "Matched")

        # Caso 4b: número de factura en la descripción del depósito
        for _ in range(6):
            name = self.rng.choice(CUSTOMERS)
            day, amount, ref = self.random_day(), self.unique_amount(350, 6500), self.invoice_ref()
            self.add_book(day, name, ref, amount)
            number = ref.split("-")[1]
            line = self.add_bank(day + timedelta(days=self.rng.randint(0, 6)),
                                 f"ACH CREDIT {self.bank_name(name)} INV {number}", amount)
            self.add_case(4, f"Invoice number {number} in bank description", [line], [ref], "Matched")

    # ---------- movimientos de la cuenta que no son facturas ----------

    def account_activity(self):
        """Nómina, préstamo, traspasos y comisiones que la empresa SÍ registró en sus libros."""
        recorded = [
            (date(2026, 8, 3), "ONLINE TRANSFER TO SAVINGS XXXX0000", "Transfer to savings", "TRF-0803", "-500.00"),
            (date(2026, 8, 5), "EQUIPMENT LOAN PAYMENT", "Equipment loan", "LOAN-08", "-1245.00"),
            # Mismo monto en dos fechas distintas: NO es un duplicado
            (date(2026, 8, 14), "PAYROLL TRANSFER", "Payroll", "PR-0814", "-8450.00"),
            (date(2026, 8, 28), "PAYROLL TRANSFER", "Payroll", "PR-0828", "-8450.00"),
            (date(2026, 8, 14), "WIRE TRANSFER FEE", "Bank fee - wire", "FEE-0814", "-25.00"),
            (date(2026, 8, 20), "MERCHANT SERVICES FEE", "Merchant services fee", "FEE-0820", "-38.12"),
        ]
        for day, bank_text, book_name, ref, amount in recorded:
            self.reserve(amount)
            self.add_book(day, book_name, ref, amount)
            line = self.add_bank(day, bank_text, amount)
            self.add_case(1, f"Recorded in the books: {book_name}", [line], [ref], "Matched")

    # ---------- casos difíciles (3, 5, 6, 7, 8, 9, 10, 11) ----------

    def tricky(self):
        # Caso 3: nombre escrito distinto. Hay otro pago con el MISMO monto
        # (Riverside Lumber), así que solo el nombre sirve para decidir.
        self.reserve("975.00")
        smith_ref, river_ref = self.bill_ref(), self.bill_ref()
        self.add_book(date(2026, 8, 10), "John Smith Plumbing LLC", smith_ref, "-975.00")
        self.add_book(date(2026, 8, 11), "Riverside Lumber Supply", river_ref, "-975.00")
        line = self.add_bank(date(2026, 8, 12), "ACH DEBIT J SMITH PLUMBING", "-975.00")
        self.add_case(3, "Different spelling: 'J SMITH PLUMBING' vs 'John Smith Plumbing LLC'",
                      [line], [smith_ref], "Probable")
        self.add_case(7, "Payment recorded, not yet in the bank (same amount as the Smith payment)",
                      [], [river_ref], "Books only")

        # Caso 5: dos depósitos con el MISMO monto y uno sin nombre en el banco: ambiguo
        self.reserve("1850.00")
        ref_a, ref_b = self.invoice_ref(), self.invoice_ref()
        self.add_book(date(2026, 8, 17), "Oak Hollow Apartments", ref_a, "1850.00")
        self.add_book(date(2026, 8, 18), "Sunnyside Daycare", ref_b, "1850.00")
        line = self.add_bank(date(2026, 8, 19), "MOBILE DEPOSIT REF 553190", "1850.00")
        self.add_case(5, "Two book entries with the same amount, deposit has no name: ambiguous",
                      [line], [ref_a, ref_b], "Review")

        # Caso 6: cargos y abonos del banco que la empresa NO registró todavía
        not_recorded = [
            (date(2026, 8, 26), "RETURNED ITEM FEE", "-12.00"),
            (date(2026, 8, 31), "MONTHLY SERVICE FEE", "-15.00"),
            (date(2026, 8, 31), "INTEREST PAYMENT", "1.87"),
        ]
        for day, desc, amount in not_recorded:
            self.reserve(amount)
            line = self.add_bank(day, desc, amount)
            self.add_case(6, f"Bank-only item, not recorded yet: {desc.title()}", [line], [], "Bank only")

        # Caso 7a: depósitos registrados que el banco aún no refleja (deposits in transit)
        for day in (date(2026, 8, 28), date(2026, 8, 29), date(2026, 8, 31)):
            name = self.rng.choice(CUSTOMERS)
            ref, amount = self.invoice_ref(), self.unique_amount(350, 6500)
            self.add_book(day, name, ref, amount)
            self.add_case(7, "Deposit in transit: recorded, not yet in the bank", [], [ref], "Books only")

        # Caso 7b: cheques emitidos que el banco todavía no cobró (outstanding checks)
        for day in (date(2026, 8, 26), date(2026, 8, 28), date(2026, 8, 31)):
            name = self.rng.choice(VENDORS)
            ref, amount = self.check_ref(), -self.unique_amount(80, 3500)
            self.add_book(day, name, ref, amount)
            self.add_case(7, "Outstanding check: written, not yet cashed", [], [ref], "Books only")

        # Caso 8: pago parcial (llegaron 3,000 de un cobro registrado por 4,200)
        ref = self.invoice_ref()
        self.reserve("4200.00", "3000.00")
        self.add_book(date(2026, 8, 6), "Tall Pines Motel", ref, "4200.00")
        line = self.add_bank(date(2026, 8, 9), "ACH CREDIT TALL PINES MOTEL", "3000.00")
        self.add_case(8, "Partial payment: 3,000.00 received of 4,200.00", [line], [ref], "Review")

        # Caso 9: un solo depósito que cubre dos asientos juntos (1,500.00 + 1,275.50)
        ref_a, ref_b = self.invoice_ref(), self.invoice_ref()
        self.reserve("1500.00", "1275.50", "2775.50")
        self.add_book(date(2026, 8, 4), "Birchwood HOA", ref_a, "1500.00")
        self.add_book(date(2026, 8, 7), "Birchwood HOA", ref_b, "1275.50")
        line = self.add_bank(date(2026, 8, 10), "ACH CREDIT BIRCHWOOD HOA", "2775.50")
        self.add_case(9, "One deposit covers two entries (1,500.00 + 1,275.50)",
                      [line], [ref_a, ref_b], "Probable")

        # Caso 10: movimiento duplicado. El original cuadra; la copia va a revisión.
        ref = self.bill_ref()
        self.reserve("212.40")
        self.add_book(date(2026, 8, 21), "Brightway Fuel", ref, "-212.40")
        original = self.add_bank(date(2026, 8, 22), "POS PURCHASE BRIGHTWAY FUEL", "-212.40")
        duplicate = self.add_bank(date(2026, 8, 22), "POS PURCHASE BRIGHTWAY FUEL", "-212.40")
        self.add_case(10, "Original of a duplicated bank line", [original], [ref], "Matched")
        self.add_case(10, "Duplicated bank line (same date, description and amount)",
                      [duplicate], [], "Review")

        # El cheque de $540.00 que en sample_data_error/ se registra como $450.00
        self.reserve("540.00", "450.00")
        ref = self.check_ref()
        self.transposed = self.add_book(date(2026, 8, 12), "Red Barn Hardware", ref, "-540.00")
        line = self.add_bank(date(2026, 8, 17), f"CHECK {ref}", "-540.00")
        self.add_case(4, f"Check number {ref} in bank description", [line], [ref], "Matched")

        # Caso 11: pago de más (el cliente pagó 1,000.00 por un cobro registrado de 900.00)
        ref = self.invoice_ref()
        self.reserve("900.00", "1000.00", "100.00")
        self.add_book(date(2026, 8, 13), "Cedar Hill Kennels", ref, "900.00")
        line = self.add_bank(date(2026, 8, 15), "ACH CREDIT CEDAR HILL KENNELS", "1000.00")
        self.add_case(11, "Overpayment: 1,000.00 received for 900.00 recorded", [line], [ref], "Review")


# ---------- escribir archivos ----------

def us_date(day):
    return day.strftime("%m/%d/%Y")


def plain_amount(amount):
    """1234.5 -> '1,234.50' y -975 -> '-975.00' (estilo banco)."""
    return f"{amount:,.2f}"


def dollars(amount):
    """Siempre positivo con signo de dólar: '$1,234.50'."""
    return f"${abs(amount):,.2f}"


def quickbooks_amount(amount):
    """Negativos entre paréntesis, como algunos reportes contables: '(975.00)'."""
    return f"({abs(amount):,.2f})" if amount < 0 else f"{amount:,.2f}"


def write_bank(folder, bank):
    with open(folder / "bank.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Description", "Amount"])
        for line in bank:
            writer.writerow([us_date(line["date"]), line["description"], plain_amount(line["amount"])])


def write_bank_debit_credit(folder, bank):
    with open(folder / "bank_debit_credit.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Posting Date", "Description", "Debit", "Credit"])
        for line in bank:
            debit = dollars(line["amount"]) if line["amount"] < 0 else ""
            credit = dollars(line["amount"]) if line["amount"] > 0 else ""
            writer.writerow([line["date"].isoformat(), line["description"], debit, credit])


# Líneas de texto que algunos bancos ponen ANTES del encabezado (todo ficticio)
PREAMBLE = [
    ["Example Community Bank (fictional)"],
    ["Account: Business Checking ending in 0000"],
    ["Statement period: 08/01/2026 - 08/31/2026"],
    [],
]


def check_number(line):
    """'CHECK 1043' -> '1043'; cualquier otra descripción -> ''."""
    return line["description"].split()[1] if line["description"].startswith("CHECK ") else ""


def write_format_samples(folder, bank):
    """El mismo estado de cuenta en los 3 formatos de ejemplo de mappings/."""
    folder.mkdir(exist_ok=True)

    # format_a: una columna de monto y el número de cheque aparte
    with open(folder / "format_a.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(PREAMBLE)
        writer.writerow(["Txn Date", "Narrative", "Serial No", "Net Amount"])
        for line in bank:
            writer.writerow([us_date(line["date"]), line["description"], check_number(line),
                             plain_amount(line["amount"])])

    # format_b: columnas separadas para lo que sale y lo que entra
    with open(folder / "format_b.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(PREAMBLE)
        writer.writerow(["Value Date", "Details", "Ref No", "Money Out", "Money In"])
        for line in bank:
            out = f"{abs(line['amount']):.2f}" if line["amount"] < 0 else ""
            into = f"{line['amount']:.2f}" if line["amount"] > 0 else ""
            writer.writerow([line["date"].isoformat(), line["description"], check_number(line), out, into])

    # format_c: fecha con otro nombre y año de 2 cifras; negativos entre paréntesis
    with open(folder / "format_c.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(PREAMBLE[:2])
        writer.writerow(["Effective Dt", "Payee Info", "Amt"])
        for line in bank:
            amount = f"(${abs(line['amount']):,.2f})" if line["amount"] < 0 else f"${line['amount']:,.2f}"
            writer.writerow([line["date"].strftime("%m/%d/%y"), line["description"], amount])


def write_books(folder, books):
    with open(folder / "books.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Name", "Num", "Amount"])
        for entry in books:
            writer.writerow([us_date(entry["date"]), entry["name"], entry["num"],
                             quickbooks_amount(entry["amount"])])


# Fecha fija para los archivos de Excel: así el .xlsx sale idéntico cada vez
FIXED_TIMESTAMP = datetime(2026, 9, 1)


def save_xlsx_reproducible(workbook, path):
    """Guarda un .xlsx siempre igual, byte por byte.

    Un .xlsx es un zip; openpyxl anota dentro la hora actual (en las propiedades y en
    cada archivo del zip). Fijamos esas fechas para que git no vea cambios al regenerar.
    """
    workbook.properties.created = FIXED_TIMESTAMP
    workbook.properties.modified = FIXED_TIMESTAMP
    buffer = io.BytesIO()
    workbook.save(buffer)
    with zipfile.ZipFile(buffer) as original, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as copy_zip:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == "docProps/core.xml":
                # openpyxl pone la hora actual en "modified" al guardar: la reemplazamos
                stamp = FIXED_TIMESTAMP.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
                data = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*", rb"\g<1>" + stamp, data)
            fixed = zipfile.ZipInfo(item.filename, date_time=FIXED_TIMESTAMP.timetuple()[:6])
            fixed.compress_type = zipfile.ZIP_DEFLATED
            copy_zip.writestr(fixed, data)


def write_excel(folder, name, header, rows):
    """Una hoja con encabezado y filas. Las fechas van como fechas de Excel y los montos como números."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = name
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    for cell in sheet["A"][1:]:
        cell.number_format = "mm/dd/yyyy"
    save_xlsx_reproducible(workbook, folder / f"{name}.xlsx")


def write_balances(folder, bank, books):
    """Saldo final = saldo inicial + todos los movimientos del mes."""
    bank_end = OPENING_BALANCE + sum(line["amount"] for line in bank)
    book_end = OPENING_BALANCE + sum(entry["amount"] for entry in books)
    data = {
        "statement_date": STATEMENT_END.isoformat(),
        "bank_ending_balance": f"{bank_end:.2f}",
        "book_ending_balance": f"{book_end:.2f}",
    }
    (folder / "balances.json").write_text(json.dumps(data, indent=2) + "\n")


def write_expected(folder, cases):
    with open(folder / "expected.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case", "note", "bank_lines", "book_refs", "expected_status"])
        for case in sorted(cases, key=lambda c: c["case"]):
            bank_lines = ";".join(str(line["line"]) for line in case["bank"])
            writer.writerow([case["case"], case["note"], bank_lines, ";".join(case["refs"]), case["expected"]])


def write_files(builder):
    # Ordenar por fecha. sort() es estable: el duplicado queda después del original.
    builder.bank.sort(key=lambda line: line["date"])
    builder.books.sort(key=lambda entry: entry["date"])

    # Número de línea en el archivo del banco (la línea 1 es el encabezado)
    for index, line in enumerate(builder.bank):
        line["line"] = index + 2

    OUT_DIR.mkdir(exist_ok=True)
    write_bank(OUT_DIR, builder.bank)
    write_bank_debit_credit(OUT_DIR, builder.bank)
    write_books(OUT_DIR, builder.books)
    write_excel(OUT_DIR, "bank", ["Date", "Description", "Amount"],
                [[line["date"], line["description"], line["amount"]] for line in builder.bank])
    write_excel(OUT_DIR, "books", ["Date", "Name", "Num", "Amount"],
                [[e["date"], e["name"], e["num"], e["amount"]] for e in builder.books])
    write_balances(OUT_DIR, builder.bank, builder.books)
    write_expected(OUT_DIR, builder.cases)
    write_format_samples(OUT_DIR / "formats", builder.bank)

    # El juego con error: mismo banco, pero un asiento de los libros con dígitos invertidos
    books_with_error = copy.deepcopy(builder.books)
    for entry in books_with_error:
        if entry["num"] == builder.transposed["num"]:
            entry["amount"] = Decimal("-450.00")   # debía ser -540.00
    ERROR_DIR.mkdir(exist_ok=True)
    write_bank(ERROR_DIR, builder.bank)
    write_books(ERROR_DIR, books_with_error)
    write_balances(ERROR_DIR, builder.bank, books_with_error)


def main():
    builder = SampleBuilder()
    builder.tricky()     # primero los difíciles, para reservar sus montos
    builder.account_activity()
    builder.routine()
    write_files(builder)
    print(f"Wrote {len(builder.bank)} bank lines, {len(builder.books)} book entries "
          f"and {len(builder.cases)} expected cases to {OUT_DIR.name}/ and {ERROR_DIR.name}/")


if __name__ == "__main__":
    main()
