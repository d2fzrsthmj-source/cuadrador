"""Motor de emparejamiento: el corazón de Cuadrador.

Empareja cada línea del banco con los asientos de los LIBROS (el registro de la
cuenta que exporta QuickBooks; también sirve una lista de facturas), en rondas,
de la más segura a la menos segura:

  Paso 0: duplicados en el banco                                  -> "Review"
  Ronda 1: mismo monto + nº de cheque/factura en la descripción   -> "Matched"
  Ronda 2: mismo monto + fecha a ±5 días + un solo candidato      -> "Matched"
  Ronda 3: mismo monto + fecha cercana + nombre parecido          -> "Probable"
           (si el nombre no ayuda a decidir)                      -> "Review"
  Ronda 4: montos con dos dígitos invertidos (540 vs 450)         -> "Review"
  Ronda 5: lo que sobra: ¿varios asientos juntos? ¿pago parcial?  -> "Review"
  El resto: "Bank only" (solo en el banco) y "Books only" (solo en los libros).

Cada resultado guarda su MOTIVO en palabras simples (en inglés, porque es lo
que ve el cliente en la pantalla y en el Excel). Una misma línea nunca se usa
dos veces.

Cada resultado también dice si sus líneas "ya pasaron" por el banco (`cleared`):
eso decide qué entra en la conciliación estándar (ver reconciliation.py).
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Reglas del juego (fáciles de cambiar aquí)
DATE_WINDOW_DAYS = 5      # "fecha cercana" para rondas 2, 3 y 4
LOOSE_WINDOW_DAYS = 10    # ventana más amplia para pagos parciales y múltiples
MIN_NAME_SCORE = 0.6      # parecido mínimo de nombres (0 = nada, 1 = idéntico)
NAME_MARGIN = 0.15        # cuánto debe ganarle el mejor nombre al segundo

# Estados posibles
MATCHED = "Matched"
PROBABLE = "Probable"
REVIEW = "Review"
BANK_ONLY = "Bank only"
BOOKS_ONLY = "Books only"

# Palabras que el banco agrega y que no son parte del nombre
NOISE_WORDS = {
    "ACH", "CREDIT", "DEBIT", "DEPOSIT", "MOBILE", "PPD", "CCD", "WEB", "ID", "REF",
    "POS", "PURCHASE", "PAYMENT", "PMT", "ONLINE", "TRANSFER", "WIRE", "CHECK", "CHK",
    "INV", "INVOICE", "FROM", "TO", "LLC", "INC", "CO", "CORP", "CORPORATION", "LTD",
    "THE", "AND", "OF",
}


@dataclass
class Match:
    """Un resultado: líneas del banco + asientos de los libros + estado + motivo."""
    status: str
    bank: list
    books: list
    reason: str
    # True = es el mismo movimiento en banco y libros (ya pasó por el banco).
    # False = pendiente de que una persona decida; sus líneas siguen "abiertas".
    cleared: bool = False
    # Solo para dígitos invertidos: cuánto se desvía el banco de los libros
    discrepancy: object = None


@dataclass
class Result:
    """Todo lo que sale del emparejamiento."""
    matched: list = field(default_factory=list)       # Match con estado Matched
    review: list = field(default_factory=list)        # Match con estado Probable o Review
    bank_only: list = field(default_factory=list)     # Transaction del banco sin pareja
    books_only: list = field(default_factory=list)    # Transaction de los libros sin pareja
    bad_lines: list = field(default_factory=list)     # BadLine del lector (lo llena quien llama)

    @property
    def unmatched_count(self):
        return len(self.bank_only) + len(self.books_only)


# ---------- ayudantes de texto y dinero ----------

def money(amount):
    """Decimal -> '$1,234.50' o '-$975.00'."""
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


def plural(count, word, many=None):
    """plural(1, 'day') -> '1 day'; plural(2, 'book entry', 'book entries') -> '2 book entries'."""
    return f"{count} {word}" if count == 1 else f"{count} {many or word + 's'}"


def clean_name(text):
    """'ACH DEBIT J SMITH PLUMBING' -> 'J SMITH PLUMBING'; 'John Smith Plumbing LLC' -> 'JOHN SMITH PLUMBING'."""
    words = re.sub(r"[^A-Z0-9 ]", " ", text.upper()).split()
    return " ".join(w for w in words if w not in NOISE_WORDS and not any(c.isdigit() for c in w))


def name_similarity(bank_text, book_name):
    """Qué tan parecidos son dos nombres, de 0.0 a 1.0 (usa difflib)."""
    a, b = clean_name(bank_text), clean_name(book_name)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def numbers_in(text):
    """Los números enteros que aparecen en un texto: 'CHECK 1042' -> {1042}."""
    return {int(n) for n in re.findall(r"\d+", text)}


def reference_found(bank, entry):
    """Si el número de cheque/factura del asiento aparece en la línea del banco, lo devuelve; si no, None."""
    # Solo números de 3 o más cifras, para no confundir un '12' cualquiera
    ref_numbers = {int(n) for n in re.findall(r"\d{3,}", entry.reference)}
    hits = ref_numbers & (numbers_in(bank.description) | numbers_in(bank.reference))
    return min(hits) if hits else None


def is_transposition(a, b):
    """¿Dos montos son iguales salvo dos dígitos intercambiados? (540.00 y 450.00 -> True)."""
    x, y = f"{abs(a):.2f}", f"{abs(b):.2f}"
    if len(x) != len(y) or x == y:
        return False
    different = [i for i in range(len(x)) if x[i] != y[i]]
    if len(different) != 2:
        return False
    i, j = different
    return x[i] == y[j] and x[j] == y[i]


def days_apart(a, b):
    return abs((a.date - b.date).days)


def days_text(days):
    return "same date" if days == 0 else f"dates {plural(days, 'day')} apart"


def refs_text(entries):
    return ", ".join(e.reference or e.description for e in entries)


def entry_label(entry):
    """Cómo nombrar un asiento en un motivo: 'check 1043', 'INV-5003' o su nombre."""
    ref = entry.reference.strip()
    if ref.isdigit():
        return f"check {ref}"
    return ref or entry.description


def same_direction(a, b):
    """Los dos entran dinero o los dos salen."""
    return (a.amount > 0) == (b.amount > 0)


# ---------- el motor ----------

class Reconciler:
    """Lleva la cuenta de qué líneas ya se usaron y aplica las rondas en orden."""

    def __init__(self, bank, books):
        self.bank = sorted(bank, key=lambda t: (t.date, t.line))
        self.books = sorted(books, key=lambda t: (t.date, t.line))
        self.used = set()   # (source, line) de cada línea ya emparejada
        self.result = Result()

    # --- utilidades ---

    def is_free(self, t):
        return (t.source, t.line) not in self.used

    def free_bank(self):
        return [t for t in self.bank if self.is_free(t)]

    def free_books(self):
        return [t for t in self.books if self.is_free(t)]

    def add(self, status, bank, books, reason, cleared=False, discrepancy=None):
        """Guarda un resultado y marca sus líneas como usadas."""
        for t in bank + books:
            if not self.is_free(t):
                # Protección: nunca usar la misma línea dos veces
                raise RuntimeError(f"{t.source} line {t.line} was already used")
            self.used.add((t.source, t.line))
        match = Match(status, bank, books, reason, cleared, discrepancy)
        if status == MATCHED:
            self.result.matched.append(match)
        else:
            self.result.review.append(match)

    def book_candidates(self, bank, window=DATE_WINDOW_DAYS):
        """Asientos libres con el mismo monto y fecha cercana a esta línea del banco."""
        return [e for e in self.free_books()
                if e.amount == bank.amount and days_apart(bank, e) <= window]

    def bank_candidates(self, entry, window=DATE_WINDOW_DAYS):
        """Líneas del banco libres con el mismo monto y fecha cercana a este asiento."""
        return [b for b in self.free_bank()
                if b.amount == entry.amount and days_apart(b, entry) <= window]

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
            found = [(e, reference_found(b, e)) for e in self.free_books() if e.amount == b.amount]
            found = [(e, number) for e, number in found if number is not None]
            if len(found) == 1:
                entry, number = found[0]
                kind = "check" if entry.reference.strip().isdigit() else "reference"
                self.add(MATCHED, [b], [entry],
                         f"Same amount and {kind} {number} in the bank description", cleared=True)

    # --- ronda 2: monto + fecha cercana + un solo candidato ---

    def round_single_candidate(self):
        for b in self.free_bank():
            candidates = self.book_candidates(b)
            # Un solo candidato en los dos sentidos: este asiento tampoco tiene otra línea del banco
            if len(candidates) == 1 and len(self.bank_candidates(candidates[0])) == 1:
                entry = candidates[0]
                self.add(MATCHED, [b], [entry],
                         f"Same amount, {days_text(days_apart(b, entry))}, only possible match",
                         cleared=True)

    # --- ronda 3: varios candidatos, decide el nombre ---

    def round_similar_name(self):
        for b in self.free_bank():
            if not self.is_free(b):
                continue  # ya quedó en un grupo ambiguo de esta misma ronda
            candidates = self.book_candidates(b)
            if not candidates:
                continue
            scored = sorted(((name_similarity(b.description, e.description), e) for e in candidates),
                            key=lambda pair: pair[0], reverse=True)
            best_score, best = scored[0]
            runner_up = scored[1][0] if len(scored) > 1 else 0.0

            if best_score >= MIN_NAME_SCORE and best_score - runner_up >= NAME_MARGIN:
                self.add(PROBABLE, [b], [best],
                         f"Same amount, {days_text(days_apart(b, best))}, similar name "
                         f"('{b.description}' ~ '{best.description}', {best_score:.0%} alike); "
                         f"{plural(len(candidates), 'book entry', 'book entries')} had this amount", cleared=True)
            else:
                self.add_ambiguous(b, candidates)

    def add_ambiguous(self, bank, candidates):
        """Varios asientos y/o líneas del banco comparten monto y fechas: que decida una persona."""
        bank_lines = [bank]
        for e in candidates:
            for other in self.bank_candidates(e):
                if other not in bank_lines:
                    bank_lines.append(other)
        amount = money(bank.amount)
        if len(bank_lines) == 1:
            reason = (f"{len(candidates)} book entries with the same amount ({amount}) and close dates: "
                      f"{refs_text(candidates)}. Can't tell which one this is")
        else:
            reason = (f"{len(bank_lines)} bank lines and {plural(len(candidates), 'book entry', 'book entries')} share "
                      f"the amount {amount} with close dates. Can't tell which goes with which")
        self.add(REVIEW, bank_lines, candidates, reason)

    # --- ronda 4: dígitos invertidos ---

    def round_transposition(self):
        """Mismo movimiento, pero registrado con dos dígitos intercambiados ($540 como $450)."""
        for b in self.free_bank():
            options = []
            for e in self.free_books():
                if not same_direction(b, e) or not is_transposition(b.amount, e.amount):
                    continue
                by_reference = reference_found(b, e) is not None
                by_name = (days_apart(b, e) <= DATE_WINDOW_DAYS
                           and name_similarity(b.description, e.description) >= MIN_NAME_SCORE)
                if by_reference or by_name:
                    options.append(e)
            if len(options) == 1:
                entry = options[0]
                gap = b.amount - entry.amount
                self.add(REVIEW, [b], [entry],
                         f"Same transaction, but the amounts differ by {money(abs(gap))}: bank "
                         f"{money(b.amount)} vs books {money(entry.amount)} "
                         f"({entry_label(entry)}). Two digits look swapped "
                         f"when it was recorded", cleared=True, discrepancy=gap)

    # --- ronda 5: varios asientos juntos y pagos parciales ---

    def round_leftovers(self):
        for b in self.free_bank():
            if not self.find_multi_entry(b):
                self.find_partial(b)

    def find_multi_entry(self, bank):
        """¿Esta línea del banco es la suma exacta de dos asientos?"""
        nearby = [e for e in self.free_books()
                  if same_direction(bank, e) and days_apart(bank, e) <= LOOSE_WINDOW_DAYS]
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
                 f"One payment for 2 entries? {a.reference} ({money(a.amount)}) + "
                 f"{c.reference} ({money(c.amount)}) = {money(bank.amount)}")
        return True

    def find_partial(self, bank):
        """¿Esta línea del banco paga solo una parte de un asiento del mismo cliente?"""
        options = []
        for e in self.free_books():
            if not same_direction(bank, e) or abs(bank.amount) >= abs(e.amount):
                continue
            if days_apart(bank, e) > LOOSE_WINDOW_DAYS:
                continue
            score = name_similarity(bank.description, e.description)
            if score >= MIN_NAME_SCORE or reference_found(bank, e) is not None:
                options.append((score, e))
        if not options:
            return False
        _, entry = max(options, key=lambda p: p[0])
        short = abs(entry.amount) - abs(bank.amount)
        self.add(REVIEW, [bank], [entry],
                 f"Partial payment? Bank shows {money(bank.amount)} but {entry.reference} "
                 f"is {money(entry.amount)} ({money(short)} short)")
        return True

    # --- todo junto ---

    def run(self):
        self.find_duplicates()
        self.round_reference()
        self.round_single_candidate()
        self.round_similar_name()
        self.round_transposition()
        self.round_leftovers()
        self.result.bank_only = self.free_bank()
        self.result.books_only = self.free_books()
        self.result.matched.sort(key=lambda m: m.bank[0].date)
        return self.result


def reconcile(bank, books):
    """Empareja listas de Transaction del banco y de los libros. Devuelve un Result."""
    return Reconciler(bank, books).run()
