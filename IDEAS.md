# Ideas (todavía NO se construyen)

Cosas que se harán más adelante. Anotarlas aquí, no construirlas sin que el usuario lo pida.

## Del plan original
- **Resolver pagos parciales y pagos múltiples.** Hoy solo se detectan y van a "Review".
  Idea: permitir marcar un pago parcial como "aceptado" y dejar el saldo pendiente como
  factura abierta; buscar combinaciones de 3 o más facturas (hoy solo pares).
- **Recordar los mapeos de columnas por banco.** Hoy `read_transactions(..., column_map=...)`
  acepta un mapeo, pero hay que pasarlo cada vez. Guardar un mapeo por banco
  (p. ej. un archivo JSON con el nombre del banco) y elegirlo en la pantalla.
- **Leer PDF** de estados de cuenta (necesitaría una librería nueva: explicarla antes).
- **Diseño visual** de la pantalla web (hoy es mínima a propósito).
- **Login** (solo si algún día deja de ser únicamente local).
- **README para enseñar a clientes** cómo exportar sus CSV y leer los resultados.

## Anotadas durante la construcción
- Algunos bancos ponen líneas de texto ANTES del encabezado del CSV. Hoy el lector toma
  la primera fila no vacía como encabezado; habría que buscar la fila que tenga "Date".
- Un caso ambiguo de una factura contra dos líneas del banco sin nombre: hoy va entero
  a "Review"; se podría sugerir cuál es la más probable por la fecha.
- Pagos "de más" (overpayment): hoy solo se detecta el pago de menos.
- Mostrar los motivos también en español (hoy van en inglés, igual que la pantalla).
- Las ventanas de fecha (±5 días, ±10 días) y el parecido mínimo de nombres (60 %)
  están fijos en `matcher.py`; podrían ser configurables desde la pantalla.
