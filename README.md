# Auditor preliminar de DIPs

Audita los DIPs de un Excel (por defecto, de todos los tipos) con los datos de **ICAM** (solo lectura) y `DIPs References.xlsx`. Resultado por DIP: **POSIBLE DISCREPANCIA**, **REVISAR**, **SIN FUENTE EN DIPS REFERENCES**, **OK** o **CORREGIDO EN CIERRE**, con el motivo. Reglas fijas, sin IA. Detalle en [docs/tecnico.md](docs/tecnico.md).

La tabla online de `DIPs References.xlsx` (Others, Powerplant y Structures) determina las referencias vigentes. Se pueden agregar, eliminar o renombrar filas sin editar el programa: las nuevas se reconocen por su referencia técnica o las palabras de DESCRIPTION; las eliminadas dejan de usarse. `config/catalogo_others.yaml` aporta sinónimos y reglas adicionales para las filas que siguen existiendo. Si cambia un TA, sus variantes locales anteriores dejan de aplicarse; un TA condicional nuevo que no se pueda interpretar queda para revisión manual. Los DIPs que no están en la tabla salen **SIN FUENTE EN DIPS REFERENCES** y se revisan contra el plazo, el RIR y el vencimiento que dice su propia descripción. Para auditar solo algunos tipos use `--tipos-dip` (o `tipos_auditados` en `config/config.yaml`); los demás quedan **FUERA DE ALCANCE** (otro tipo de DIP) y no se revisan.

## Instalación

```bat
git clone https://github.com/lviloriabas/dips.git
cd dips
setup.bat
```

Ejecute `setup.bat` como usuario normal, sin permisos de administrador. Usa CPython
3.12 de 64 bits (x64); si falta, lo instala solo para su usuario desde python.org.
Las librerías se descargan precompiladas, sin instalar Visual C++ Build Tools.
Si el intento anterior dejó un `.venv` incompatible, vuelva a ejecutar `setup.bat`:
lo conserva en `.venv-incompatible-...` y crea uno nuevo con la versión correcta.

Si la PC tiene git, al abrir `auditar.bat`, `comparar.bat` o `filtrar.bat` el programa avisa cuando hay una versión más nueva en GitHub y pregunta si se actualiza.

## Uso

| Acción | Cómo | Resultado |
| --- | --- | --- |
| Auditar | Arrastrar el Excel sobre `auditar.bat` | `salida/...xlsx`, filtrar `RESULTADO` |
| Auditar un solo DIP | `auditar.bat T40S0099V9C` (el barcode, sin Excel) | En consola: datos del DIP, resultado y hallazgos. No genera archivos |
| Comparar con la auditoría manual | Arrastrar `DIPs Audit (...).xlsx` sobre `comparar.bat` | `salida/..._COMPARACION_...xlsx` (hojas **Resumen** y **Detalle por DIP**) |
| Filtrar DIPs pendientes de auditar | Arrastrar `DIPs Audit (...).xlsx` sobre `filtrar.bat` | `filtered/DIPs Audit (...) FILTERED.xlsx`, dentro de la carpeta del original: ACTV, ACTIVE, OPEN, IN WORK o PAUSE sin `DIP Open Audit User` y COMPLETE sin `DIP Closed Audit User` |
| Modo prueba | Poner el Excel en `pruebas/entrada/` (o usar `--prueba`) | `pruebas/salida/PRUEBA_...xlsx` |

Por defecto se audita **solo con el Excel** (menos reglas). Para leer en ICAM todos los DIPs del archivo, de cualquier tipo, ejecute el `.bat` en la consola con `--icam` (ver [Comandos](#comandos)); fuera del aviso de actualización, el programa no hace preguntas.

Con `--icam` se abre una ventana de Edge en ICAM: si pide sesión, iníciela ahí. El programa sigue apenas la sesión se inicia y se detiene apenas la página de inicio de sesión muestra un error. Al terminar la lectura, el programa cierra la ventana y todos los procesos de Edge que abrió; si una corrida anterior dejó alguno abierto, lo cierra al final de la siguiente. El Edge de uso diario no se toca.

## Comandos

```bat
auditar.bat "DIPs Audit (23SEP2026).xlsx" --icam
auditar.bat "DIPs Audit (23SEP2026).xlsx" --referencias "referencias.pdf"
auditar.bat "DIPs Audit (23SEP2026).xlsx" --referencias "https://copaairlines.sharepoint.com/.../doc2.aspx?..."
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
| `--referencias XLSX/PDF/URL` | Usar otra tabla de referencias local o un enlace de SharePoint. El PDF debe contener texto seleccionable y las nueve columnas de `References` en una misma tabla |
| `--no-cache` | Leer en ICAM todos los DIPs, aunque se hayan leído hace menos de 1 hora (por defecto se usa lo guardado en `data/icam.json`) |
| `--datos-icam RUTA` | Usar datos de ICAM ya extraídos (`data/icam.json` o CSV), sin leer ICAM |
| `--pendientes` | Auditar solo los DIPs ACTV, ACTIVE, OPEN, IN WORK o PAUSE sin `DIP Open Audit User` y COMPLETE sin `DIP Closed Audit User`. Antes crea `filtered/... FILTERED.xlsx` dentro de la carpeta del original, como `filtrar.bat` (sin esta opción, se auditan todos) |
| `-j`, `--hoja NOMBRE` | Hoja a leer (por defecto, la que tiene `Fault Barcode`) |
| `-f`, `--fecha "AAAA-MM-DD HH:MM"` | Auditar a esa fecha y hora |
| `-n`, `--sin-excel` | Resultado solo en consola |
| `-c`, `--categorias TIPO ...` | Solo esos tipos de discrepancia (basta parte del nombre) |
| `-e`, `--excluir-categorias TIPO ...` | Todos menos esos tipos |
| `-t`, `--tipos-dip TIPO ...` | Auditar solo esos tipos de DIP (columna `Type DIP` / `Area`, p. ej. `Others`). Por defecto, todos |
| `-p`, `--prueba` | Forzar modo prueba |
| `-o`, `--salida RUTA` | Excel de resultado (solo `auditar`) |

El programa consulta `referencias_sharepoint` en cada corrida real que usa referencias,
incluso si ya hay una copia local. Las referencias e ICAM se abren en pestañas de una
misma ventana de Edge, que se conserva durante toda la corrida; si Microsoft pide iniciar
sesión, la persona lo hace allí. `abrir-icam` también sincroniza las referencias. Al
terminar, incluso ante errores, se cierra Edge del programa. Las sesiones quedan guardadas
en `.icam_perfil/`.

Cada descarga se valida y se compara con las copias locales. Solo si cambió se sustituye
la copia de `data/` y se actualiza `DIPs References.xlsx` (o la ruta de `referencias`, si
tiene el mismo formato). Si el archivo principal está bloqueado, se avisa y se usa la
descarga validada de `data/`.
Si SharePoint no está disponible, se usa esa copia; si aún no existe, se usa
`DIPs References.xlsx`. La consola avisa del fallo, de la copia utilizada y de su fecha.
Si ninguna copia es válida, la auditoría se detiene con un mensaje. `--referencias`
permite elegir un XLSX/PDF local o un enlace distinto; para trabajar siempre con un
archivo local, deje `referencias_sharepoint` vacío. El modo prueba y el benchmark usan
la referencia local, salvo que se indique otra con `--referencias`.

La revisión de referencia técnica y la exigencia de attachments aplican a los DIPs
diferidos **desde el 9 de julio de 2026**, según `Defer Dt`. Los anteriores quedan exentos
de esos controles. Si falta la fecha de diferimiento, esos
hallazgos no se infieren. En DIPs COMPLETE, se lee la acción correctiva de ICAM para
contrastar la referencia y los S/N citados.

Se reconocen etiquetas como `S/N2` y `P/N2` por separado. Los squibs se revisan por P/N:
el extractor consulta la página de la parte y sus análogos en ICAM. Si no puede confirmar
esa lista, deja la comprobación pendiente. Un lote (Batch No) no se compara como serial.
Los remanentes RIR claramente fuera del intervalo se señalan para revisar su configuración;
se compara cada valor en su unidad, tanto en Excel como en ICAM.

Otros comandos (`.venv\Scripts\python -m dips_audit ...`):

| Comando | Uso |
| --- | --- |
| `categorias` | Lista los tipos de discrepancia |
| `validar-reglas` | Comprueba el archivo de reglas y detecta códigos mal escritos |
| `referencias` | Muestra cómo se interpretó la tabla de referencias |
| `extraer-icam archivo.xlsx` / `--barcode X` | Solo leer ICAM |
| `abrir-icam` | Abrir Edge, actualizar las referencias y cerrar el navegador |
| `benchmark` | Medir contra los DIPs ya auditados ([ver](docs/tecnico.md#10-benchmark)) |

Pruebas: `.venv\Scripts\python -m pytest`

## Resultado

| `RESULTADO` | Qué hacer |
| --- | --- |
| POSIBLE DISCREPANCIA | Leer `HALLAZGOS` y decidir |
| REVISAR | La tabla da el TA o el RIR según el daño o el tipo ("DEPENDING ON...", "CONSULT REF."): verificarlo en el manual que indica el hallazgo |
| SIN FUENTE EN DIPS REFERENCES | El DIP no está en la tabla de referencias: verificarlo contra la fuente que cita (o agregar la referencia a la tabla) |
| OK | Hacer las verificaciones de `VERIFICACIÓN MANUAL` |
| CORREGIDO EN CIERRE | Discrepancia de apertura con cierre OK. Hacer las verificaciones de `VERIFICACIÓN MANUAL` |

Otras columnas: `COMENTARIO SUGERIDO`, `AUDITORÍA` (APERTURA/CIERRE), `ESTADO APERTURA` / `ESTADO CIERRE`, `REFERENCIA ASOCIADA`, `REFERENCIA TÉCNICA DEL DIP`, `RIR EN ICAM`, `ADJUNTOS EN ICAM`, `AUDITORÍA MANUAL EN ICAM` (lo que anotó el auditor en cada marca: discrepancia y motivo, o sin discrepancia). El Excel de entrada no se modifica.

En DIPs **COMPLETE**, una apertura con **POSIBLE DISCREPANCIA** y un cierre **OK** da
**CORREGIDO EN CIERRE**. Si la apertura también era OK, el resultado sigue como **OK**.
En los demás casos, `RESULTADO` corresponde a `ESTADO CIERRE`. `ESTADO APERTURA` y
los hallazgos marcados `[APERTURA]` conservan ese historial. El comentario sugerido
y los conteos de discrepancias en consola corresponden a la auditoría actual.

`COMENTARIO SUGERIDO` está redactado para ICAM: indica qué dato del DIP se debe
verificar o corregir y conserva los valores relevantes, sin mencionar el Excel de auditoría.

Los DIPs que mencionan **BOROSCOPE** o **BORESCOPE** en el nombre, la descripción
o sus notas se siguen **solo por RIR, sin T/A**. No se exige ni se valida el intervalo,
el Start o el plazo del T/A. Se revisa que exista el RIR y se valida contra la tabla
o el periodo que declare la descripción; si faltan datos, queda para verificación manual.

La excepción son los DIPs que piden el boroscope dentro de un plazo, por ejemplo «perform a
boroscope in the next 25FH or 10FC», y lo siguen con los deadlines del TA en Scheduling,
sin RIR. Esos no son discrepancia: se auditan como cualquier DIP con TA, y el TA se
compara con la tabla o con el plazo que declara la descripción.

## Ajustes

| Qué | Dónde |
| --- | --- |
| Reglas activas y detalles adicionales | `config/discrepancias.yaml` |
| Tolerancias, lectura de ICAM, manuales sin REV/fecha | `config/config.yaml` |
| Palabras clave de referencias Others | `config/catalogo_others.yaml` |
| TA, Parent Assembly, AMM/ECRA, RIR | `DIPs References.xlsx`, un PDF de la misma tabla o el enlace de SharePoint |

Para cambiar una regla, siga la [guía de configuración](docs/configurar_reglas.md). Después ejecute `validar-reglas` y `benchmark` para comprobar el archivo y comparar los resultados con la línea base.

## Problemas frecuentes

| Mensaje | Solución |
| --- | --- |
| "No se pudo iniciar sesión en ICAM: ..." | La página de inicio de sesión dio ese error (usuario o clave). Revisar y volver a arrastrar el archivo |
| "No se inició sesión en ICAM en 3 minutos" | Iniciar sesión en el Edge de ICAM y volver a arrastrar el archivo |
| "La sesión de ICAM venció" | Iniciar sesión de nuevo; lo ya leído queda guardado |
| "Permission denied" | Cerrar el Excel de salida |
| "Microsoft Visual C++ 14.0 or greater is required" | Actualizar el proyecto y volver a ejecutar `setup.bat` como usuario normal. Configura Python 3.12 x64 y descarga paquetes precompilados |
| "Faltan columnas obligatorias" | Formato inesperado; ver [docs/tecnico.md](docs/tecnico.md#1-lectura-del-excel-de-entrada) |

## Documentos

- [tecnico.md](docs/tecnico.md): funcionamiento y reglas en detalle
- [configurar_reglas.md](docs/configurar_reglas.md): cambios frecuentes en las reglas, paso a paso
- [proceso.md](docs/proceso.md): proceso en diagramas
- [comparacion_modos.md](docs/comparacion_modos.md): registro del modo con agente (eliminado)
