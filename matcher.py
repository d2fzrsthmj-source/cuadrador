"""Motor de emparejamiento: el corazón de Cuadrador.

Empareja cada línea del banco con como máximo una factura, en rondas, de la más
segura a la menos segura:

  Paso 0: duplicados en el banco            -> "Review"
  Ronda 1: mismo monto + nº de cheque/factura en la descripción -> "Matched"
  Ronda 2: mismo monto + fecha a ±5 días + un solo candidato   -> "Matched"
  Ronda 3: mismo monto + fecha cercana + nombre parecido        -> "Probable"
           (si el nombre no ayuda a decidir)                    -> "Review"
  Ronda 4: lo que sobra: ¿pago de varias facturas? ¿pago parcial? -> "Review"
  El resto: "Unmatched in bank" y "Unmatched invoices".

Cada emparejamiento guarda su MOTIVO en palabras simples (en inglés, porque
es lo que ve el cliente en la pantalla y en el Excel).
Una misma línea nunca se usa dos veces.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

# Reglas del juego (fáciles de cambiar aquí)
DATE_WINDOW_DAYS = 5      # "fecha cercana" para rondas 2 y 3
LOOSE_WINDOW_DAYS = 10    # ventana más amplia para pagos parciales y múltiples
MIN_NAME_SCORE = 0.6      # parecido mínimo de nombres (0 = nada, 1 = idéntico)
NAME_MARGIN = 0.15        # cuánto debe ganarle el mejor nombre al segundo

# Estados posibles
MATCHED = "Matched"
PROBABLE = "Probable"
REVIEW = "Review"

# Palabras que el banco agrega y que no son parte del nombre
NOISE_WORDS = {
    "ACH", "CREDIT", "DEBIT", "DEPOSIT", "MOBILE", "PPD", "CCD", "WEB", "ID", "REF",
    "POS", "PURCHASE", "PAYMENT", "PMT", "ONLINE", "TRANSFER", "WIRE", "CHECK", "CHK",
    "INV", "INVOICE", "FROM", "TO", "LLC", "INC", "CO", "CORP", "CORPORATION", "LTD",
    "THE", "AND", "OF",
}


@dataclass
class Match:
    """Un resultado: líneas del banco + facturas + estado + motivo."""
    status: str
    bank: list
    invoices: list
    reason: str


@dataclass
class Result:
    """Todo lo que sale del emparejamiento."""
    matched: list = field(default_factory=list)             # Match con estado Matched
    review: list = field(default_factory=list)              # Match con estado Probable o Review
    unmatched_bank: list = field(default_factory=list)      # Transaction del banco sin pareja
    unmatched_invoices: list = field(default_factory=list)  # Transaction de facturas sin pareja
    bank_total: Decimal = Decimal("0.00")
    invoice_total: Decimal = Decimal("0.00")
    bad_lines: list = field(default_factory=list)           # BadLine del lector (lo llena quien llama)

    @property
    def unmatched_count(self):
        return len(self.unmatched_bank) + len(self.unmatched_invoices)

    @property
    def difference(self):
        """Total del banco menos total de facturas. Si todo cuadrara, sería 0."""
        return self.bank_total - self.invoice_total


# ---------- ayudantes de texto y dinero ----------

def money(amount):
    """Decimal -> '$1,234.50' o '-$975.00'."""
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def plural(count, word):
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def clean_name(text):
    """'ACH DEBIT J SMITH PLUMBING' -> 'J SMITH PLUMBING'; 'John Smith Plumbing LLC' -> 'JOHN SMITH PLUMBING'."""
    words = re.sub(r"[^A-Z0-9 ]", " ", text.upper()).split()
    return " ".join(w for w in words if w not in NOISE_WORDS and not any(c.isdigit() for c in w))


def name_similarity(bank_text, invoice_name):
    """Qué tan parecidos son dos nombres, de 0.0 a 1.0 (usa difflib)."""
    a, b = clean_name(bank_text), clean_name(invoice_name)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def numbers_in(text):
    """Los números enteros que aparecen en un texto: 'CHECK 1042' -> {1042}."""
    return {int(n) for n in re.findall(r"\d+", text)}


def reference_found(bank, invoice):
    """Si el número de cheque/factura aparece en la línea del banco, lo devuelve; si no, None."""
    # Solo números de 3 o más cifras, para no confundir un '12' cualquiera
    ref_numbers = {int(n) for n in re.findall(r"\d{3,}", invoice.reference)}
    hits = ref_numbers & (numbers_in(bank.description) | numbers_in(bank.reference))
    return min(hits) if hits else None


def days_apart(a, b):
    return abs((a.date - b.date).days)


def days_text(days):
    return "same date" if days == 0 else f"dates {plural(days, 'day')} apart"


def refs_text(invoices):
    return ", ".join(i.reference or i.description for i in invoices)


# ---------- el motor ----------

class Reconciler:
    """Lleva la cuenta de qué líneas ya se usaron y aplica las rondas en orden."""

    def __init__(self, bank, invoices):
        self.bank = sorted(bank, key=lambda t: (t.date, t.line))
        self.invoices = sorted(invoices, key=lambda t: (t.date, t.line))
        self.used = set()   # (source, line) de cada línea ya emparejada
        self.result = Result(
            bank_total=sum((t.amount for t in bank), Decimal("0.00")),
            invoice_total=sum((t.amount for t in invoices), Decimal("0.00")),
        )

    # --- utilidades ---

    def is_free(self, t):
        return (t.source, t.line) not in self.used

    def free_bank(self):
        return [t for t in self.bank if self.is_free(t)]

    def free_invoices(self):
        return [t for t in self.invoices if self.is_free(t)]

    def add(self, status, bank, invoices, reason):
        """Guarda un resultado y marca sus líneas como usadas."""
        for t in bank + invoices:
            if not self.is_free(t):
                # Protección: nunca usar la misma línea dos veces
                raise RuntimeError(f"{t.source} line {t.line} was already used")
            self.used.add((t.source, t.line))
        match = Match(status, bank, invoices, reason)
        if status == MATCHED:
            self.result.matched.append(match)
        else:
            self.result.review.append(match)

    def invoice_candidates(self, bank, window=DATE_WINDOW_DAYS):
        """Facturas libres con el mismo monto y fecha cercana a esta línea del banco."""
        return [i for i in self.free_invoices()
                if i.amount == bank.amount and days_apart(bank, i) <= window]

    def bank_candidates(self, invoice, window=DATE_WINDOW_DAYS):
        """Líneas del banco libres con el mismo monto y fecha cercana a esta factura."""
        return [b for b in self.free_bank()
                if b.amount == invoice.amount and days_apart(b, invoice) <= window]

    # --- paso 0: duplicados ---

    def find_duplicates(self):
        seen = {}
        for b in self.bank:
            key = (b.date, b.description.strip().upper(), b.amount, b.reference)
            if key in seen:
                self.add(REVIEW, [b], [],
                         f"Possible duplicate of bank line {seen[key].line} "
                         f"(same date, description and amount)")
            else:
                seen[key] = b

    # --- ronda 1: monto + número de cheque o factura ---

    def round_reference(self):
        for b in self.free_bank():
            found = [(i, reference_found(b, i)) for i in self.free_invoices() if i.amount == b.amount]
            found = [(i, number) for i, number in found if number is not None]
            if len(found) == 1:
                invoice, number = found[0]
                kind = "check" if invoice.reference.strip().isdigit() else "invoice"
                self.add(MATCHED, [b], [invoice],
                         f"Same amount and {kind} {number} in the bank description")

    # --- ronda 2: monto + fecha cercana + un solo candidato ---

    def round_single_candidate(self):
        for b in self.free_bank():
            candidates = self.invoice_candidates(b)
            # Un solo candidato en los dos sentidos: esta factura tampoco tiene otra línea del banco
            if len(candidates) == 1 and len(self.bank_candidates(candidates[0])) == 1:
                invoice = candidates[0]
                self.add(MATCHED, [b], [invoice],
                         f"Same amount, {days_text(days_apart(b, invoice))}, only possible match")

    # --- ronda 3: varios candidatos, decide el nombre ---

    def round_similar_name(self):
        for b in self.free_bank():
            if not self.is_free(b):
                continue  # ya quedó en un grupo ambiguo de esta misma ronda
            candidates = self.invoice_candidates(b)
            if not candidates:
                continue
            scored = sorted(((name_similarity(b.description, i.description), i) for i in candidates),
                            key=lambda pair: pair[0], reverse=True)
            best_score, best = scored[0]
            runner_up = scored[1][0] if len(scored) > 1 else 0.0

            if best_score >= MIN_NAME_SCORE and best_score - runner_up >= NAME_MARGIN:
                self.add(PROBABLE, [b], [best],
                         f"Same amount, {days_text(days_apart(b, best))}, similar name "
                         f"('{b.description}' ~ '{best.description}', {best_score:.0%} alike); "
                         f"{plural(len(candidates), 'invoice')} had this amount")
            else:
                self.add_ambiguous(b, candidates)

    def add_ambiguous(self, bank, candidates):
        """Varias facturas y/o líneas del banco comparten monto y fechas: que decida una persona."""
        bank_lines = [bank]
        for i in candidates:
            for other in self.bank_candidates(i):
                if other not in bank_lines:
                    bank_lines.append(other)
        amount = money(bank.amount)
        if len(bank_lines) == 1:
            reason = (f"{len(candidates)} invoices with the same amount ({amount}) and close dates: "
                      f"{refs_text(candidates)}. Can't tell which one this pays")
        else:
            reason = (f"{len(bank_lines)} bank lines and {plural(len(candidates), 'invoice')} share "
                      f"the amount {amount} with close dates. Can't tell which goes with which")
        self.add(REVIEW, bank_lines, candidates, reason)

    # --- ronda 4: pagos que cubren varias facturas y pagos parciales ---

    def round_leftovers(self):
        for b in self.free_bank():
            if not self.find_multi_invoice(b):
                self.find_partial(b)

    def find_multi_invoice(self, bank):
        """¿Esta línea del banco es la suma exacta de dos facturas?"""
        nearby = [i for i in self.free_invoices()
                  if (i.amount > 0) == (bank.amount > 0) and days_apart(bank, i) <= LOOSE_WINDOW_DAYS]
        pairs = []
        for x in range(len(nearby)):
            for y in range(x + 1, len(nearby)):
                a, c = nearby[x], nearby[y]
                if a.amount + c.amount == bank.amount:
                    score = (name_similarity(bank.description, a.description)
                             + name_similarity(bank.description, c.description))
                    pairs.append((score, a, c))
        if not pairs:
            return False
        _, a, c = max(pairs, key=lambda p: p[0])
        self.add(REVIEW, [bank], [a, c],
                 f"One payment for 2 invoices? {a.reference} ({money(a.amount)}) + "
                 f"{c.reference} ({money(c.amount)}) = {money(bank.amount)}")
        return True

    def find_partial(self, bank):
        """¿Esta línea del banco paga solo una parte de una factura del mismo cliente?"""
        options = []
        for i in self.free_invoices():
            same_direction = (i.amount > 0) == (bank.amount > 0)
            if not same_direction or abs(bank.amount) >= abs(i.amount):
                continue
            if days_apart(bank, i) > LOOSE_WINDOW_DAYS:
                continue
            score = name_similarity(bank.description, i.description)
            if score >= MIN_NAME_SCORE or reference_found(bank, i) is not None:
                options.append((score, i))
        if not options:
            return False
        _, invoice = max(options, key=lambda p: p[0])
        short = abs(invoice.amount) - abs(bank.amount)
        self.add(REVIEW, [bank], [invoice],
                 f"Partial payment? Bank shows {money(bank.amount)} but {invoice.reference} "
                 f"is {money(invoice.amount)} ({money(short)} short)")
        return True

    # --- todo junto ---

    def run(self):
        self.find_duplicates()
        self.round_reference()
        self.round_single_candidate()
        self.round_similar_name()
        self.round_leftovers()
        self.result.unmatched_bank = self.free_bank()
        self.result.unmatched_invoices = self.free_invoices()
        self.result.matched.sort(key=lambda m: m.bank[0].date)
        return self.result


def reconcile(bank, invoices):
    """Empareja listas de Transaction del banco y de facturas. Devuelve un Result."""
    return Reconciler(bank, invoices).run()
