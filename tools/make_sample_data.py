"""Genera datos de ejemplo INVENTADOS para probar Cuadrador.

Empresa ficticia: "Maple Street Contracting". Todos los clientes, proveedores,
montos y descripciones son inventados. No hay ningún dato real aquí.

Crea en sample_data/:
  - bank.csv               movimientos del banco (una columna de monto)
  - bank_debit_credit.csv  los mismos movimientos, con columnas Debit y Credit
  - invoices.csv           facturas y pagos esperados (estilo QuickBooks)
  - expected.csv           la "hoja de respuestas": qué debe pasar con cada caso difícil

Uso:  python tools/make_sample_data.py
Usa una semilla fija, así que siempre genera exactamente los mismos archivos.
"""

import csv
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

SEED = 20260801
OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data"

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
    """Va juntando líneas de banco, facturas y casos esperados."""

    def __init__(self):
        self.rng = random.Random(SEED)
        self.bank = []        # cada línea: dict con date, description, amount
        self.invoices = []    # cada factura: dict con date, name, num, amount
        self.cases = []       # cada caso: dict con case, note, bank (lista de dicts), refs, expected
        self.used_amounts = set()
        self.next_inv = 5001
        self.next_check = 1040
        self.next_bill = 3001

    # ---------- ayudantes ----------

    def unique_amount(self, low, high):
        """Un monto al azar con centavos que no se haya usado antes (evita empates por accidente)."""
        while True:
            cents = self.rng.randint(low * 100, high * 100)
            amount = Decimal(cents) / 100
            if amount not in self.used_amounts:
                self.used_amounts.add(amount)
                return amount

    def random_day(self, first=date(2026, 7, 28), last=date(2026, 8, 24)):
        return first + timedelta(days=self.rng.randint(0, (last - first).days))

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

    def add_invoice(self, day, name, num, amount):
        self.invoices.append({"date": day, "name": name, "num": num, "amount": amount})

    def add_bank(self, day, description, amount):
        # El banco no muestra fechas después del cierre de mes
        line = {"date": min(day, date(2026, 8, 31)), "description": description, "amount": amount}
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
            self.add_invoice(day, name, ref, amount)
            line = self.add_bank(day, f"ACH CREDIT {self.bank_name(name)} PPD ID {self.ppd_id()}", amount)
            self.add_case(1, "Exact match: same amount, same date", [line], [ref], "Matched")

        # Caso 1 también con proveedores pagados por ACH el mismo día
        for _ in range(3):
            name = self.rng.choice(VENDORS)
            day, amount, ref = self.random_day(), -self.unique_amount(80, 3500), self.bill_ref()
            self.add_invoice(day, name, ref, amount)
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
            self.add_invoice(day, name, ref, amount)
            line = self.add_bank(day + timedelta(days=shift), desc, amount)
            self.add_case(2, f"Same amount, bank date {shift} day(s) later", [line], [ref], "Matched")

        # Caso 4a: número de cheque en la descripción ("CHECK 1042").
        # Algunos cheques tardan más de 5 días en cobrarse: el número de cheque basta.
        for _ in range(12):
            name = self.rng.choice(VENDORS)
            day, amount, ref = self.random_day(), -self.unique_amount(80, 3500), self.check_ref()
            self.add_invoice(day, name, ref, amount)
            line = self.add_bank(day + timedelta(days=self.rng.randint(1, 12)), f"CHECK {ref}", amount)
            self.add_case(4, f"Check number {ref} in bank description", [line], [ref], "Matched")

        # Caso 4b: número de factura en la descripción del depósito
        for _ in range(6):
            name = self.rng.choice(CUSTOMERS)
            day, amount, ref = self.random_day(), self.unique_amount(350, 6500), self.invoice_ref()
            self.add_invoice(day, name, ref, amount)
            number = ref.split("-")[1]
            line = self.add_bank(day + timedelta(days=self.rng.randint(0, 9)),
                                 f"ACH CREDIT {self.bank_name(name)} INV {number}", amount)
            self.add_case(4, f"Invoice number {number} in bank description", [line], [ref], "Matched")

    # ---------- casos difíciles (3, 5, 6, 7, 8, 9, 10) ----------

    def tricky(self):
        # Caso 3: nombre escrito distinto. Hay otra factura con el MISMO monto
        # (Riverside Lumber), así que solo el nombre sirve para decidir.
        amount = Decimal("-975.00")
        self.used_amounts.add(-amount)
        smith_ref, river_ref = self.bill_ref(), self.bill_ref()
        self.add_invoice(date(2026, 8, 10), "John Smith Plumbing LLC", smith_ref, amount)
        self.add_invoice(date(2026, 8, 11), "Riverside Lumber Supply", river_ref, amount)
        line = self.add_bank(date(2026, 8, 12), "ACH DEBIT J SMITH PLUMBING", amount)
        self.add_case(3, "Different spelling: 'J SMITH PLUMBING' vs 'John Smith Plumbing LLC'",
                      [line], [smith_ref], "Probable")
        self.add_case(7, "Unpaid bill with the same amount as the Smith payment", [], [river_ref],
                      "Unmatched invoice")

        # Caso 5: dos facturas con el MISMO monto y un depósito sin nombre: ambiguo
        amount = Decimal("1850.00")
        self.used_amounts.add(amount)
        ref_a, ref_b = self.invoice_ref(), self.invoice_ref()
        self.add_invoice(date(2026, 8, 17), "Oak Hollow Apartments", ref_a, amount)
        self.add_invoice(date(2026, 8, 18), "Sunnyside Daycare", ref_b, amount)
        line = self.add_bank(date(2026, 8, 19), "MOBILE DEPOSIT REF 553190", amount)
        self.add_case(5, "Two invoices with the same amount, deposit has no name: ambiguous",
                      [line], [ref_a, ref_b], "Review")

        # Caso 6: cargos y abonos del banco sin factura (comisiones, intereses, nómina, préstamo)
        extras = [
            (date(2026, 8, 3), "ONLINE TRANSFER TO SAVINGS XXXX0000", Decimal("-500.00")),
            (date(2026, 8, 5), "EQUIPMENT LOAN PAYMENT", Decimal("-1245.00")),
            # Mismo monto en dos fechas distintas: NO es un duplicado
            (date(2026, 8, 14), "PAYROLL TRANSFER", Decimal("-8450.00")),
            (date(2026, 8, 28), "PAYROLL TRANSFER", Decimal("-8450.00")),
            (date(2026, 8, 14), "WIRE TRANSFER FEE", Decimal("-25.00")),
            (date(2026, 8, 20), "MERCHANT SERVICES FEE", Decimal("-38.12")),
            (date(2026, 8, 26), "RETURNED ITEM FEE", Decimal("-12.00")),
            (date(2026, 8, 31), "MONTHLY SERVICE FEE", Decimal("-15.00")),
            (date(2026, 8, 31), "INTEREST PAYMENT", Decimal("1.87")),
        ]
        for day, desc, amount in extras:
            self.used_amounts.add(abs(amount))
            line = self.add_bank(day, desc, amount)
            self.add_case(6, f"Bank-only item: {desc.title()}", [line], [], "Unmatched in bank")

        # Caso 7: facturas que todavía no se han pagado (fin de mes)
        for day in (date(2026, 8, 25), date(2026, 8, 27), date(2026, 8, 28), date(2026, 8, 29)):
            name = self.rng.choice(CUSTOMERS)
            ref, amount = self.invoice_ref(), self.unique_amount(350, 6500)
            self.add_invoice(day, name, ref, amount)
            self.add_case(7, "Invoice not paid yet", [], [ref], "Unmatched invoice")

        # Caso 8: pago parcial (pagaron 3,000 de una factura de 4,200)
        ref = self.invoice_ref()
        self.used_amounts.update({Decimal("4200.00"), Decimal("3000.00")})
        self.add_invoice(date(2026, 8, 6), "Tall Pines Motel", ref, Decimal("4200.00"))
        line = self.add_bank(date(2026, 8, 9), "ACH CREDIT TALL PINES MOTEL", Decimal("3000.00"))
        self.add_case(8, "Partial payment: paid 3,000.00 of a 4,200.00 invoice", [line], [ref], "Review")

        # Caso 9: un solo pago que cubre dos facturas juntas (1,500.00 + 1,275.50)
        ref_a, ref_b = self.invoice_ref(), self.invoice_ref()
        self.used_amounts.update({Decimal("1500.00"), Decimal("1275.50"), Decimal("2775.50")})
        self.add_invoice(date(2026, 8, 4), "Birchwood HOA", ref_a, Decimal("1500.00"))
        self.add_invoice(date(2026, 8, 7), "Birchwood HOA", ref_b, Decimal("1275.50"))
        line = self.add_bank(date(2026, 8, 10), "ACH CREDIT BIRCHWOOD HOA", Decimal("2775.50"))
        self.add_case(9, "One payment covers two invoices (1,500.00 + 1,275.50)",
                      [line], [ref_a, ref_b], "Review")

        # Caso 10: movimiento duplicado. El original cuadra; la copia va a revisión.
        ref = self.bill_ref()
        self.used_amounts.add(Decimal("212.40"))
        self.add_invoice(date(2026, 8, 21), "Brightway Fuel", ref, Decimal("-212.40"))
        original = self.add_bank(date(2026, 8, 22), "POS PURCHASE BRIGHTWAY FUEL", Decimal("-212.40"))
        copy = self.add_bank(date(2026, 8, 22), "POS PURCHASE BRIGHTWAY FUEL", Decimal("-212.40"))
        self.add_case(10, "Original of a duplicated bank line", [original], [ref], "Matched")
        self.add_case(10, "Duplicated bank line (same date, description and amount)",
                      [copy], [], "Review")


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


def write_files(builder):
    OUT_DIR.mkdir(exist_ok=True)

    # Ordenar por fecha. sort() es estable: el duplicado queda después del original.
    builder.bank.sort(key=lambda line: line["date"])
    builder.invoices.sort(key=lambda inv: inv["date"])

    # Número de línea en el archivo (la línea 1 es el encabezado)
    for index, line in enumerate(builder.bank):
        line["line"] = index + 2

    with open(OUT_DIR / "bank.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Description", "Amount"])
        for line in builder.bank:
            writer.writerow([us_date(line["date"]), line["description"], plain_amount(line["amount"])])

    with open(OUT_DIR / "bank_debit_credit.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Posting Date", "Description", "Debit", "Credit"])
        for line in builder.bank:
            debit = dollars(line["amount"]) if line["amount"] < 0 else ""
            credit = dollars(line["amount"]) if line["amount"] > 0 else ""
            writer.writerow([line["date"].isoformat(), line["description"], debit, credit])

    with open(OUT_DIR / "invoices.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Name", "Num", "Amount"])
        for inv in builder.invoices:
            writer.writerow([us_date(inv["date"]), inv["name"], inv["num"], quickbooks_amount(inv["amount"])])

    with open(OUT_DIR / "expected.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["case", "note", "bank_lines", "invoice_refs", "expected_status"])
        for case in sorted(builder.cases, key=lambda c: c["case"]):
            bank_lines = ";".join(str(line["line"]) for line in case["bank"])
            writer.writerow([case["case"], case["note"], bank_lines, ";".join(case["refs"]), case["expected"]])


def main():
    builder = SampleBuilder()
    builder.tricky()     # primero los difíciles, para reservar sus montos
    builder.routine()
    write_files(builder)
    print(f"Wrote {len(builder.bank)} bank lines, {len(builder.invoices)} invoices "
          f"and {len(builder.cases)} expected cases to {OUT_DIR}")


if __name__ == "__main__":
    main()
