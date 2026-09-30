# Auditor preliminar de DIPs

Audita los DIPs de un Excel (por defecto, de todos los tipos) con los datos de **ICAM** (solo lectura) y `DIPs References.xlsx`. Resultado por DIP: **POSIBLE DISCREPANCIA**, **REVISAR**, **SIN FUENTE** u **OK**, con el motivo. Reglas fijas, sin IA. Detalle en [docs/tecnico.md](docs/tecnico.md).

Cada fila de `DIPs References.xlsx` (Others, Powerplant y Structures) tiene en `config/catalogo_others.yaml` las palabras con que se reconoce en los DIPs. Una fila nueva sin entrada en ese archivo se usa igual: se reconoce por su referencia técnica o por las palabras de su DESCRIPTION (con la entrada se reconocen muchos más DIPs). Los DIPs que no están en la tabla salen **SIN FUENTE** y se revisan contra el plazo, el RIR y el vencimiento que dice su propia descripción. Para auditar solo algunos tipos use `--tipos-dip` (o `tipos_auditados` en `config/config.yaml`); los demás quedan **FUERA DE ALCANCE** (otro tipo de DIP) y no se revisan.

## Instalación

```bat
git clone https://github.com/lviloriabas/dips.git
cd dips
setup.bat
```

Si la PC tiene git, al abrir `auditar.bat`, `comparar.bat` o `filtrar.bat` el programa avisa cuando hay una versión más nueva en GitHub y pregunta si se actualiza.

## Uso

| Acción | Cómo | Resultado |
| --- | --- | --- |
| Auditar | Arrastrar el Excel sobre `auditar.bat` | `salidas/...xlsx`, filtrar `RESULTADO` |
| Auditar un solo DIP | `auditar.bat T40S0099V9C` (el barcode, sin Excel) | En consola: datos del DIP, resultado y hallazgos. No genera archivos |
| Comparar con la auditoría manual | Arrastrar `DIPs Audit (...).xlsx` sobre `comparar.bat` | `salidas/..._COMPARACION_...xlsx` (hojas **Resumen** y **Detalle por DIP**) |
| Filtrar DIPs pendientes de auditar | Arrastrar `DIPs Audit (...).xlsx` sobre `filtrar.bat` | `DIPs Audit (...) FILTERED.xlsx` junto al original: solo ACTV sin `DIP Open Audit User` y COMPLETE sin `DIP Closed Audit User` |
| Modo prueba | Poner el Excel en `pruebas/entrada/` (o usar `--prueba`) | `pruebas/salidas/PRUEBA_...xlsx` |

Por defecto se audita **solo con el Excel** (menos reglas). Para leer en ICAM todos los DIPs del archivo, de cualquier tipo, ejecute el `.bat` en la consola con `--icam` (ver [Comandos](#comandos)); fuera del aviso de actualización, el programa no hace preguntas.

Con `--icam` se abre una ventana de Edge en ICAM: si pide sesión, iníciela ahí. El programa sigue apenas la sesión se inicia y se detiene apenas la página de inicio de sesión muestra un error. Al terminar la lectura, el programa cierra la ventana y todos los procesos de Edge que abrió; si una corrida anterior dejó alguno abierto, lo cierra al final de la siguiente. El Edge de uso diario no se toca.

## Comandos

```bat
auditar.bat "DIPs Audit (23SEP2026).xlsx" --icam
auditar.bat T40S0099V9C
auditar.bat "DIPs Audit (23SEP2026).xlsx" -f "2026-09-23 14:00"
auditar.bat "DIPs Audit (23SEP2026).xlsx" --categorias "Incorrect DIP Interval" RIR
auditar.bat "DIPs Audit (23SEP2026).xlsx" --excluir-categorias "Missing S/N"
auditar.bat "DIPs Audit (23SEP2026).xlsx" --tipos-dip Others
auditar.bat "DIPs Audit (23SEP2026).xlsx" --pendientes
comparar.bat "DIPs Audit (23SEP2026).xlsx" -i -e RIR
```

| Opción | Uso |
| --- | --- |
| `-i`, `--icam` | Leer en ICAM todos los DIPs del archivo (sin esta opción, solo el Excel: menos reglas) |
| `--no-cache` | Leer en ICAM todos los DIPs, aunque se hayan leído hace menos de 1 hora (por defecto se usa lo guardado en `data/icam.json`) |
| `--datos-icam RUTA` | Usar datos de ICAM ya extraídos (`data/icam.json` o CSV), sin leer ICAM |
| `--pendientes` | Auditar solo los DIPs ACTV sin `DIP Open Audit User` y COMPLETE sin `DIP Closed Audit User`. Antes crea `... FILTERED.xlsx` junto al original, como `filtrar.bat` (sin esta opción, se auditan todos) |
| `-j`, `--hoja NOMBRE` | Hoja a leer (por defecto, la que tiene `Fault Barcode`) |
| `-f`, `--fecha "AAAA-MM-DD HH:MM"` | Auditar a esa fecha y hora |
| `-n`, `--sin-excel` | Resultado solo en consola |
| `-c`, `--categorias TIPO ...` | Solo esos tipos de discrepancia (basta parte del nombre) |
| `-e`, `--excluir-categorias TIPO ...` | Todos menos esos tipos |
| `-t`, `--tipos-dip TIPO ...` | Auditar solo esos tipos de DIP (columna `Type DIP` / `Area`, p. ej. `Others`). Por defecto, todos |
| `-p`, `--prueba` | Forzar modo prueba |
| `-o`, `--salida RUTA` | Excel de resultado (solo `auditar`) |

Otros comandos (`.venv\Scripts\python -m dips_audit ...`):

| Comando | Uso |
| --- | --- |
| `categorias` | Lista los tipos de discrepancia |
| `referencias` | Muestra cómo se interpretó la tabla de referencias |
| `extraer-icam archivo.xlsx` / `--barcode X` | Solo leer ICAM |
| `abrir-icam` | Abrir el Edge de ICAM para iniciar sesión |
| `benchmark` | Medir contra los DIPs ya auditados ([ver](docs/tecnico.md#10-benchmark)) |

Pruebas: `.venv\Scripts\python -m pytest`

## Resultado

| `RESULTADO` | Qué hacer |
| --- | --- |
| POSIBLE DISCREPANCIA | Leer `HALLAZGOS` y decidir |
| REVISAR | La tabla da el TA o el RIR según el daño o el tipo ("DEPENDING ON...", "CONSULT REF."): verificarlo en el manual que indica el hallazgo |
| SIN FUENTE | El DIP no está en la tabla de referencias: verificarlo contra la fuente que cita (o agregar la referencia a la tabla) |
| OK | Hacer las verificaciones de `VERIFICACIÓN MANUAL` |

Otras columnas: `COMENTARIO SUGERIDO`, `AUDITORÍA` (APERTURA/CIERRE), `ESTADO APERTURA` / `ESTADO CIERRE`, `REFERENCIA ASOCIADA`, `REFERENCIA TÉCNICA DEL DIP`, `RIR EN ICAM`, `ADJUNTOS EN ICAM`, `AUDITORÍA MANUAL EN ICAM` (lo que anotó el auditor en cada marca: discrepancia y motivo, o sin discrepancia). El Excel de entrada no se modifica.

## Ajustes

| Qué | Dónde |
| --- | --- |
| Reglas activas y observaciones | `config/discrepancias.yaml` |
| Tolerancias, lectura de ICAM, manuales sin REV/fecha | `config/config.yaml` |
| Palabras clave de referencias Others | `config/catalogo_others.yaml` |
| TA, Parent Assembly, AMM/ECRA, RIR | `DIPs References.xlsx` |

Tras cambiar una regla, correr `benchmark` y comparar con la línea base.

## Problemas frecuentes

| Mensaje | Solución |
| --- | --- |
| "No se pudo iniciar sesión en ICAM: ..." | La página de inicio de sesión dio ese error (usuario o clave). Revisar y volver a arrastrar el archivo |
| "No se inició sesión en ICAM en 3 minutos" | Iniciar sesión en el Edge de ICAM y volver a arrastrar el archivo |
| "La sesión de ICAM venció" | Iniciar sesión de nuevo; lo ya leído queda guardado |
| "Permission denied" | Cerrar el Excel de salida |
| "Faltan columnas obligatorias" | Formato inesperado; ver [docs/tecnico.md](docs/tecnico.md#1-lectura-del-excel-de-entrada) |

## Documentos

- [tecnico.md](docs/tecnico.md): funcionamiento y reglas en detalle
- [proceso.md](docs/proceso.md): proceso en diagramas
- [comparacion_modos.md](docs/comparacion_modos.md): registro del modo con agente (eliminado)
