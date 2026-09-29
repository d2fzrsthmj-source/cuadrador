# Estado del proyecto

_Última actualización: 2026-09-28_

## Qué quedó hecho (pasos 1 a 7 del plan)
1. Esqueleto: git, venv, requirements.txt, CLAUDE.md, ESTADO.md, IDEAS.md, .gitignore.
2. `tools/make_sample_data.py`: datos inventados de "Maple Street Contracting"
   (60 líneas de banco, 57 facturas) con los 10 casos difíciles y la hoja de
   respuestas `sample_data/expected.csv`. Semilla fija: siempre sale igual.
3. `reader.py`: lee los CSV (fechas MM/DD/YYYY y YYYY-MM-DD, montos con $, comas,
   paréntesis, columnas Debit/Credit, nombres de columnas flexibles o mapeo propio).
   Las líneas rotas se separan con su motivo.
4. `matcher.py`: el motor por rondas (duplicados → número de cheque/factura →
   candidato único → nombre parecido → parciales / varias facturas). Cada resultado
   lleva su motivo. Nunca usa una línea dos veces.
5. Pruebas: 66 en verde (`pytest`), una por cada caso difícil y varias del lector.
6. `reconcile.py` + `excel_report.py`: resumen en la terminal y Excel con hojas
   Summary, Matched, Review, Unmatched bank, Unmatched invoices.
7. `app.py` + `templates/`: pantalla web en inglés, solo en 127.0.0.1, archivos en memoria.

Resultado con los datos de ejemplo: 46 cuadran, 5 para revisar, 14 no cuadran
(9 del banco, 5 facturas), diferencia -$31,341.62 (sobre todo nómina y préstamo,
que no están en la lista de facturas).

## Decisiones tomadas por mi cuenta (revisar si no convencen)
- Signos: en facturas, positivo = nos pagan (cliente), negativo = pagamos (proveedor).
- "Diferencia" = total del banco menos total de facturas.
- "Probable" (ronda 3) se cuenta y se muestra junto con "Review".
- Motivos, resumen de terminal y Excel en inglés, igual que la pantalla.
- Pagos parciales y de varias facturas usan una ventana de ±10 días.

## Qué falta
- Nada del plan original. Lo siguiente posible está en IDEAS.md.
- No hay repositorio en GitHub todavía (no se ha hecho push).

## Último commit
Ver `git log --oneline -1` (paso 7 + este cierre).

## Cómo arrancarlo
```bash
cd ~/cuadrador
source venv/bin/activate
pytest                                                            # pruebas
python reconcile.py sample_data/bank.csv sample_data/invoices.csv # terminal + Excel en output/
python app.py                                                     # web: http://127.0.0.1:5000
```
