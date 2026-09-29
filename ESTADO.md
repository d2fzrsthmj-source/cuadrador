# Estado del proyecto

_Última actualización: 2026-09-29_

**Publicado en GitHub:** https://github.com/d2fzrsthmj-source/cuadrador (rama `main`).

## Qué quedó hecho

### Pasos 1 a 7 (primera sesión)
Esqueleto, datos inventados, lector de CSV, motor por rondas, pruebas, terminal + Excel
y pantalla web mínima.

### Pasos 8 a 13 (segunda sesión)
8. **Conciliación contra los LIBROS.** El segundo archivo es el registro de la cuenta
   (`books.csv`); una lista de facturas sigue sirviendo. `reconciliation.py` arma el
   formato estándar (saldos, depósitos en tránsito, cheques pendientes, comisiones e
   intereses no registrados, otras partidas, diferencia) y da pistas si la diferencia
   no es cero (dígitos invertidos, divisible entre 9).
   Dos juegos de datos: `sample_data/` (cuadra en $0.00) y `sample_data_error/`
   ($540.00 registrado como $450.00: diferencia -$90.00, el programa lo señala).
9. **Varios asientos, parciales y pagos de más.** Combinaciones de hasta 3 asientos
   (una sola posible → Probable; varias → Review con las opciones), pago parcial con
   saldo pendiente y pago de más.
10. **Formatos de banco.** Encuentra el encabezado aunque haya líneas de texto antes.
    Formatos guardados en `mappings/format_a|b|c.json` (nombres genéricos, no de bancos
    reales). Si no reconoce las columnas, la web pregunta cuál es cuál y puede guardar
    el formato con un nombre.
11. **Pantalla profesional** en el puerto **5001**: conciliación arriba (verde si $0.00,
    rojo si no), luego Review y lo que no cuadra con su motivo, y al final lo que cuadró,
    plegado. Botones "Try with sample data" y "Try the example with an error".
    Solo acepta .csv, 5 MB máximo, mensajes claros, se imprime bien.
    El Excel gana la hoja "Reconciliation" lista para imprimir.
12. **README en inglés** para clientes y portafolio, con 3 capturas en `docs/`
    (solo datos inventados).
13. **Revisión final:** 115 pruebas en verde; los dos ejemplos corren de principio a fin
    en la terminal y en la web; historial y archivos revisados (sin datos reales,
    claves ni rutas personales).

### Resultados con los datos de ejemplo
- `sample_data/`: 53 cuadran, 6 para revisar, 10 sin pareja. **Diferencia $0.00.**
- `sample_data_error/`: **diferencia -$90.00**, causa señalada: cheque 1043,
  banco -$540.00 vs libros -$450.00.

## Decisiones tomadas por mi cuenta (revisar si no convencen)
- **Qué cuenta como "ya pasó por el banco":** los pares Matched y Probable, y el par de
  dígitos invertidos (es el mismo movimiento con distinto monto; por eso su diferencia
  queda a la vista). Todo lo que está en Review queda como partida pendiente dentro del
  formato estándar, marcado "pending review". Así la diferencia da $0.00 cuando todo
  está explicado, aunque haya casos por decidir.
- **Comisiones e intereses** se reconocen por palabras en la descripción del banco
  (FEE, SERVICE CHARGE, INTEREST). Lo demás que solo está en el banco va a
  "Other bank-only items".
- **Outstanding checks** incluye cualquier pago registrado que el banco no ha cobrado
  (cheques y pagos ACH).
- **Saldos finales:** opcionales. En la terminal, si no se dan, se leen de
  `balances.json` junto al archivo del banco (los datos de ejemplo lo traen).
- **Estados:** "Bank only" y "Books only" reemplazan a "Unmatched in bank/invoices".
- **Botones de ejemplo:** también responden a GET (solo leen los datos inventados),
  para poder tomar capturas.
- **Formatos guardados desde la web** van a `mappings/` y se versionan con git
  (solo son nombres de columnas, no datos).
- **Autor de los commits:** nombre "Adrian Martinez" (decidido por el usuario) y el
  correo privado de GitHub `331432424+d2fzrsthmj-source@users.noreply.github.com`,
  configurado solo para este repo. Antes del push se verificó que todos los commits
  (autor y committer) ya usaban ese correo; no hizo falta reescribir el historial.

## Qué falta
- Lo que sigue está en `IDEAS.md` (PDF, login, versión en español, varias cuentas...).
- Nada del plan. El repositorio ya está publicado (ver abajo).

## Último commit
Ver `git log --oneline -1`. Publicado hasta el paso 14 (`5c4beda`) y este cambio de ESTADO.md.

## Cómo arrancarlo
```bash
cd ~/cuadrador
source venv/bin/activate
pytest                                                                        # pruebas
python reconcile.py sample_data/bank.csv sample_data/books.csv                # cuadra en $0.00
python reconcile.py sample_data_error/bank.csv sample_data_error/books.csv    # -$90.00 explicado
python tools/make_sample_data.py                                              # regenerar datos
python app.py                                                                 # web: http://127.0.0.1:5001
```

## GitHub
Publicado el 2026-09-29 por SSH en `git@github.com:d2fzrsthmj-source/cuadrador.git`
(repositorio público). `main` sigue a `origin/main`. Para subir cambios nuevos:
```bash
git push
```
`.gitignore` deja fuera venv/, cachés, output/, *.xlsx, tmp/, uploads/, .env,
archivos del sistema y de editores, y registros.
