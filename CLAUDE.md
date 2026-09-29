# Cuadrador

## Qué es
Conciliación bancaria automática para negocios pequeños. El usuario sube dos CSV:
los movimientos del banco y el registro de la cuenta en sus libros (exportado de
QuickBooks; también sirve una lista de facturas). Los empareja solo, arma la
conciliación en formato estándar y muestra ÚNICAMENTE lo que no
cuadra o hay que revisar.

Es un proyecto aparte de `~/hoja-ruta`. No tocar nada de ese proyecto.

## Al empezar y al terminar cada sesión
- AL EMPEZAR: leer `ESTADO.md` para saber dónde quedó el trabajo.
- AL TERMINAR: actualizar `ESTADO.md` (qué se hizo, qué falta, último commit, cómo arrancar).
- Las ideas que todavía no se construyen van en `IDEAS.md`.

## REGLA ABSOLUTA — DATOS
- NUNCA datos reales: ni estados de cuenta reales, ni nombres de clientes reales,
  ni números de cuenta. Todo es inventado, con empresas claramente ficticias.
- Si el usuario pide importar un archivo real, RECORDARLE esta regla y NO hacerlo.
- Los datos de ejemplo salen de `tools/make_sample_data.py` (semilla fija).

## Stack
- Python 3, librería estándar siempre que se pueda: csv, decimal, datetime, difflib.
- openpyxl para exportar a Excel.
- Flask para la pantalla web (solo localhost, nunca publicar en internet).
- pytest para las pruebas.
- NO pandas. Nada más sin explicárselo antes al usuario.
- El dinero SIEMPRE con `Decimal`, nunca con `float`.
- Los archivos subidos se procesan en memoria; nunca se guardan en disco.

## Cómo explicarle al usuario
- Sabe Python básico y un poco de Flask.
- Explicar cada archivo en lenguaje simple, en español.
- Comentarios del código en español; nombres de código (variables, funciones) en inglés.
- La interfaz web va en INGLÉS (los clientes son negocios de EE. UU.).
- Si algo se puede hacer simple o elegante, elegir lo simple.

## Forma de trabajar
- Un commit por paso.
- Nunca editar con un script y hacer commit en el mismo comando.
- No hacer push sin que el usuario lo pida.

## Comandos
- Activar entorno: `source venv/bin/activate`
- Pruebas: `pytest`
- Datos de ejemplo: `python tools/make_sample_data.py`
- Terminal: `python reconcile.py sample_data/bank.csv sample_data/books.csv`
- Ejemplo con error: `python reconcile.py sample_data_error/bank.csv sample_data_error/books.csv`
- Web: `python app.py` → http://127.0.0.1:5001 (el 5000 lo usa la app del bus)
