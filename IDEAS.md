# Ideas (todavía NO se construyen)

Cosas que se harán más adelante. Anotarlas aquí, no construirlas sin que el usuario lo pida.

## Pendientes grandes
- **Leer PDF** de estados de cuenta (necesitaría una librería nueva: explicarla antes).
- **Login**, solo si algún día deja de ser únicamente local.
- **Versión en español** de la pantalla, los motivos y el Excel (hoy todo va en inglés).
- **Varias cuentas bancarias**: conciliar varias cuentas en una misma corrida, con
  traspasos entre ellas.

## Mejoras al motor
- Permitir que la persona **resuelva** en la pantalla lo que está en "Review"
  (aceptar un pago parcial, elegir una de las combinaciones, descartar un duplicado)
  y recalcular la conciliación con esa decisión.
- Buscar el caso inverso de las combinaciones: UN asiento de los libros que el banco
  muestra partido en varias líneas.
- Usar la fecha de cierre del estado de cuenta: un asiento de los libros con fecha
  POSTERIOR al cierre no debería contarse como depósito en tránsito ni como cheque pendiente.
- Cheques pendientes muy viejos (más de 90 días): marcarlos aparte ("stale checks").
- Un caso ambiguo de un asiento contra dos líneas del banco sin nombre: hoy va entero
  a "Review"; se podría sugerir cuál es la más probable por la fecha.
- Las ventanas de fecha (±5 y ±10 días) y el parecido mínimo de nombres (60 %) están
  fijos en `matcher.py`; podrían configurarse desde la pantalla.

## Formatos de archivo
- Poder borrar o renombrar formatos guardados desde la pantalla (hoy solo se crean).
- Guardar la conciliación del mes para que el saldo inicial del mes siguiente se revise solo.
- Aceptar archivos de Excel (.xlsx) además de CSV (openpyxl ya lo permite; falta decidirlo).

## Presentación
- Capturas de la pantalla de columnas y del Excel para el README.
- Nombre de la empresa y fecha del estado de cuenta en el encabezado del reporte.
