"""La conciliación bancaria en el formato estándar que reconoce cualquier contador.

    Bank ending balance
    + Deposits in transit          (en los libros, todavía no en el banco: entra dinero)
    − Outstanding checks           (en los libros, todavía no en el banco: sale dinero)
    = Adjusted bank balance

    Book ending balance
    − Bank fees not recorded       (solo en el banco: comisiones)
    + Interest not recorded        (solo en el banco: intereses)
    ± Other bank-only items        (solo en el banco: todo lo demás)
    = Adjusted book balance

    Difference = ajustado del banco − ajustado de los libros (debe dar $0.00)

Qué cuenta como "pendiente": las líneas sin pareja y las de los casos en revisión
que todavía no se decidieron (Review). Los pares Matched y Probable ya pasaron por
el banco. Un par con dígitos invertidos también (es el mismo movimiento), así
que su diferencia de monto queda a la vista en "Difference".
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from matcher import money

ZERO = Decimal("0.00")
FEE_WORDS = ("FEE", "SERVICE CHARGE")
INTEREST_WORDS = ("INTEREST",)
MAX_HINT_LINES = 5


@dataclass
class Reconciliation:
    bank_balance: object            # Decimal o None si no se dio
    book_balance: object            # Decimal o None si no se dio
    deposits_in_transit: list = field(default_factory=list)
    outstanding_checks: list = field(default_factory=list)
    bank_fees: list = field(default_factory=list)
    interest: list = field(default_factory=list)
    other_bank: list = field(default_factory=list)
    pending_review: set = field(default_factory=set)    # (source, line) de casos en Review
    discrepancies: list = field(default_factory=list)   # Match con dígitos invertidos
    all_books: list = field(default_factory=list)       # para buscar pistas

    # --- totales (siempre positivos, salvo "otras partidas" que llevan su signo) ---

    @property
    def deposits_total(self):
        return sum((t.amount for t in self.deposits_in_transit), ZERO)

    @property
    def checks_total(self):
        return sum((abs(t.amount) for t in self.outstanding_checks), ZERO)

    @property
    def fees_total(self):
        return sum((abs(t.amount) for t in self.bank_fees), ZERO)

    @property
    def interest_total(self):
        return sum((t.amount for t in self.interest), ZERO)

    @property
    def other_total(self):
        return sum((t.amount for t in self.other_bank), ZERO)

    @property
    def is_complete(self):
        """Sin los dos saldos finales no se puede calcular la diferencia."""
        return self.bank_balance is not None and self.book_balance is not None

    @property
    def adjusted_bank(self):
        if self.bank_balance is None:
            return None
        return self.bank_balance + self.deposits_total - self.checks_total

    @property
    def adjusted_book(self):
        if self.book_balance is None:
            return None
        return self.book_balance - self.fees_total + self.interest_total + self.other_total

    @property
    def difference(self):
        if not self.is_complete:
            return None
        return self.adjusted_bank - self.adjusted_book

    @property
    def is_balanced(self):
        return self.difference == ZERO

    def is_pending(self, t):
        return (t.source, t.line) in self.pending_review

    def explain(self, t):
        """Por qué esta línea sin pareja está en la conciliación, en palabras simples."""
        if self.is_pending(t):
            return "Pending review (see Needs review)"
        if t.source == "books":
            if t.amount > 0:
                return "Deposit in transit: recorded in the books, not yet in the bank"
            return "Outstanding check or payment: recorded, not yet cleared by the bank"
        if is_fee(t):
            return "Bank fee not recorded in the books yet"
        if is_interest(t):
            return "Interest not recorded in the books yet"
        return "In the bank but not in the books: record it or investigate"

    # --- el formato estándar, como lista de renglones ---

    def lines(self):
        """Renglones del resumen: (texto, monto o None, tipo). Lo usan la terminal, la web y el Excel."""
        return [
            ("Bank ending balance", self.bank_balance, "balance"),
            ("+ Deposits in transit", self.deposits_total, "item"),
            ("− Outstanding checks", self.checks_total, "item"),
            ("= Adjusted bank balance", self.adjusted_bank, "total"),
            ("Book ending balance", self.book_balance, "balance"),
            ("− Bank fees not recorded", self.fees_total, "item"),
            ("+ Interest not recorded", self.interest_total, "item"),
            ("± Other bank-only items", self.other_total, "item"),
            ("= Adjusted book balance", self.adjusted_book, "total"),
            ("Difference", self.difference, "difference"),
        ]

    def sections(self):
        """Las partidas de cada renglón, para mostrarlas en detalle."""
        return [
            ("Deposits in transit", self.deposits_in_transit),
            ("Outstanding checks", self.outstanding_checks),
            ("Bank fees not recorded", self.bank_fees),
            ("Interest not recorded", self.interest),
            ("Other bank-only items", self.other_bank),
        ]

    # --- pistas cuando la diferencia no es cero ---

    def hints(self):
        difference = self.difference
        if difference is None or difference == ZERO:
            return []
        hints = []
        for match in self.discrepancies:
            hints.append(f"Likely cause: {match.reason}.")
        if self.discrepancies and sum((m.discrepancy for m in self.discrepancies), ZERO) == difference:
            hints.append("That explains the whole difference.")
            return hints

        cents = int(abs(difference) * 100)
        if cents % 9 == 0:
            hints.append(f"The difference ({money(abs(difference))}) is divisible by 9, the classic "
                         f"sign of two swapped digits in one amount.")
            suspects = [t for t in self.all_books if swap_changes_by(t.amount, abs(difference))]
            if suspects:
                listed = "; ".join(f"{t.reference or t.description} {money(t.amount)}"
                                   for t in suspects[:MAX_HINT_LINES])
                hints.append(f"Book entries where swapping two neighboring digits gives exactly "
                             f"that difference: {listed}.")

        same = [t for t in self.all_books if abs(t.amount) == abs(difference)]
        if same:
            listed = "; ".join(f"{t.reference or t.description} {money(t.amount)}" for t in same[:MAX_HINT_LINES])
            hints.append(f"Entries of exactly {money(abs(difference))} (missing or recorded twice?): {listed}.")
        return hints


def swap_changes_by(amount, gap):
    """¿Intercambiar dos dígitos vecinos de este monto lo cambia exactamente en `gap`?"""
    digits = f"{abs(amount):.2f}".replace(".", "")
    for i in range(len(digits) - 1):
        if digits[i] == digits[i + 1]:
            continue
        swapped = digits[:i] + digits[i + 1] + digits[i] + digits[i + 2:]
        if abs(int(swapped) - int(digits)) == int(gap * 100):
            return True
    return False


def is_fee(t):
    return t.amount < 0 and any(word in t.description.upper() for word in FEE_WORDS)


def is_interest(t):
    return t.amount > 0 and any(word in t.description.upper() for word in INTEREST_WORDS)


def build_reconciliation(result, bank_balance=None, book_balance=None):
    """Arma la conciliación a partir del resultado del emparejamiento y los saldos finales."""
    recon = Reconciliation(bank_balance, book_balance)
    open_bank = list(result.bank_only)
    open_books = list(result.books_only)
    for match in result.review:
        if match.discrepancy is not None:
            recon.discrepancies.append(match)
        if not match.cleared:
            open_bank += match.bank
            open_books += match.books
            recon.pending_review.update((t.source, t.line) for t in match.bank + match.books)

    for t in sorted(open_books, key=lambda t: (t.date, t.line)):
        (recon.deposits_in_transit if t.amount > 0 else recon.outstanding_checks).append(t)
    for t in sorted(open_bank, key=lambda t: (t.date, t.line)):
        if is_fee(t):
            recon.bank_fees.append(t)
        elif is_interest(t):
            recon.interest.append(t)
        else:
            recon.other_bank.append(t)

    for match in result.matched + result.review:
        recon.all_books += match.books
    recon.all_books += result.books_only
    return recon


def load_balances(folder):
    """Lee balances.json de una carpeta (los datos de ejemplo lo traen). Devuelve (banco, libros)."""
    path = Path(folder) / "balances.json"
    if not path.exists():
        return None, None
    data = json.loads(path.read_text())
    return Decimal(data["bank_ending_balance"]), Decimal(data["book_ending_balance"])
