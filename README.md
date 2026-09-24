# Auditor preliminar de DIPs

Revisa los DIPs Others del Excel de entrada con los datos de **ICAM** y la **tabla de referencias** (`DIPs References.xlsx`). Entrega un Excel con el resultado de cada DIP: **POSIBLE DISCREPANCIA** u **OK**, y el motivo. El auditor confirma cada resultado.

- **No usa inteligencia artificial.** Todas las decisiones salen de reglas fijas y verificables.
- **Lee ICAM.** Por cada DIP abre su página en ICAM, solo para leer, con la sesión que usted inicia. No modifica nada en ICAM.

Explicación detallada de cada paso: [docs/tecnico.md](docs/tecnico.md).

## Instalación (una sola vez)

```bat
git clone https://github.com/lviloriabas/dips-ai.git
cd dips-ai
setup.bat
```

`setup.bat` instala Python y las librerías, verifica Edge y `DIPs References.xlsx`, y corre las pruebas. Se puede ejecutar de nuevo sin problema.

## Auditar

1. **Auditar:** arrastre el Excel de entrada (por ejemplo `DIPs Audit (23SEP2026).xlsx`) sobre `auditar.bat`. El programa abre una ventana de Edge en ICAM. La primera vez, o si la sesión venció, inicie sesión en esa ventana: el programa espera y sigue solo. Deje la ventana abierta para las próximas corridas.
2. El programa lee en ICAM los DIPs Others del archivo (unos 5 minutos para 380 DIPs) y los audita.
3. **Ver el resultado:** abra el Excel que se crea en `salidas/` y filtre la columna `RESULTADO`.

La fecha y hora de auditoría es el momento en que se ejecuta. Un DIP abierto (ACTV) recibe la **auditoría de apertura**; un DIP cerrado (COMPLETE), además, la **auditoría de cierre**.

## Comparar con la auditoría manual

Sirve para medir qué tan cerca está el programa de los auditores.

1. Arrastre el Excel `DIPs Audit (...)` sobre `comparar.bat`. Si hace falta, inicie sesión en ICAM en la ventana de Edge, como arriba.
2. Abra el Excel `..._COMPARACION_....xlsx` que se crea en `salidas/` (o en `pruebas/salidas/`, ver abajo).

El programa audita cada DIP a la misma fecha y hora en que lo auditó el auditor: la de apertura (`DIP Open - RT Audit Completed`) y la de cierre (`DIP Closed - RT Audit Completed`).

La hoja **Resumen** tiene tablas cortas, cada una responde una pregunta:

| Tabla | Pregunta |
| --- | --- |
| Qué se comparó | Cuántos DIPs y auditorías, cuántos se leyeron en ICAM |
| ¿El programa llega al mismo resultado que el auditor? | Sí / no |
| DIPs que el auditor dio sin discrepancia | Qué dijo el programa de esos DIPs (lo ideal: OK) |
| DIPs en que el auditor encontró discrepancia | Qué dijo el programa de esos DIPs (lo ideal: posible discrepancia) |
| Auditoría de apertura / de cierre | Resultado del programa en cada auditoría |
| Por qué el programa marca DIPs que el auditor dio sin discrepancia | Los motivos, por separado para apertura y cierre |
| Discrepancias encontradas por el auditor | Cada una, con lo que encontró el programa |

La hoja **Detalle por DIP** muestra, por barcode, lo que dijo el auditor, lo que dijo el programa y si coinciden.

## Pruebas con datos que no son reales

Para probar el programa sin que parezca una auditoría real, ponga el Excel en `pruebas/entrada/` y arrástrelo sobre `auditar.bat` o `comparar.bat`. El programa entra solo en **modo prueba**:

- guarda los datos de ICAM en `pruebas/icam/` (no en `data/icam/`);
- deja los resultados en `pruebas/salidas/`, con el prefijo `PRUEBA_`;
- lo indica en la consola y en el Excel ("PRUEBA: datos de prueba, no es una auditoría real").

Con un Excel de otra carpeta se puede forzar con `--prueba`. El contenido de `pruebas/` no se sube al repositorio.

## Cómo leer el resultado

| `RESULTADO` | Qué significa | Qué hacer |
| --- | --- | --- |
| POSIBLE DISCREPANCIA | Falló una regla, falta un dato o el DIP no está en la tabla de referencias | Leer `HALLAZGOS`: dice qué se encontró y qué corresponde. El auditor decide si es discrepancia |
| OK | No falló ninguna regla | Hacer las verificaciones de `VERIFICACIÓN MANUAL` |

Por ahora el programa no clasifica la discrepancia (crítica o no crítica) ni su tipo, porque esos criterios todavía no coinciden con el proceso de los auditores.

En la hoja **Auditoría** van primero las columnas del Excel de entrada, sin cambios, y al final las que agrega el programa (encabezado morado, celdas lila). Columnas útiles del programa:

| Columna | Contenido |
| --- | --- |
| `HALLAZGOS` | Cada hallazgo, marcado `[POSIBLE DISCREPANCIA]` u `[OBSERVACIÓN]`. Los de cierre dicen `[CIERRE]` |
| `COMENTARIO SUGERIDO` | Texto listo para copiar en el registro de la auditoría |
| `AUDITORÍA` | APERTURA o CIERRE |
| `ESTADO APERTURA` / `ESTADO CIERRE` | Resultado de cada auditoría por separado |
| `REFERENCIA ASOCIADA` / `TA SEGÚN REFERENCIA` | Fila de la tabla de referencias que corresponde al DIP |
| `REFERENCIA TÉCNICA DEL DIP` | La referencia cargada en ICAM, la cita encontrada y los adjuntos |
| `RIR EN ICAM` / `ADJUNTOS EN ICAM` | RIR y attachments leídos en ICAM |

El Excel de entrada no se modifica.

## Qué revisa

Si falla cualquiera de estas reglas, el DIP queda en **POSIBLE DISCREPANCIA**.

**Apertura** (todo DIP):

- Intervalo mayor que el TA de la tabla, o tipo de intervalo distinto (días, FH, FC).
- Parent Assembly distinto del de la tabla (avión o motor).
- Due date posterior al vencimiento del ítem, o que no coincide con apertura + intervalo.
- DIP vencido a la hora de la auditoría.
- Sin referencia técnica: no está cargada en ICAM, no hay captura adjunta y no se cita en la descripción.
- Referencia técnica de otro ítem de la tabla, o una tarea que la tabla no tiene.
- Intervalo 0, o Usage Remaining mayor que el intervalo.
- DIP duplicado, S/N repetido, o Deferral Reference distinto del ATA.
- RIR que pide la tabla y no está, o con otro intervalo.
- DIP que no está en la tabla de referencias, o que coincide con varias.

**Cierre** (DIP COMPLETE):

- Cerrado después del due date (con 5 h de tolerancia: el cierre viene en UTC).
- Cerrado después del due date original, con el deadline extendido.
- La acción correctiva no cita el manual (se acepta si remite a otra tarea o si no hubo trabajo).
- S/N removido distinto del S/N de la descripción.

El MGM no cuenta como referencia técnica. Las citas de AMM, SRM y task card no necesitan revisión ni fecha (se puede cambiar en `config/config.yaml`, `referencia_tecnica.revision_opcional`). Referencias técnicas de otros manuales sin revisión o sin fecha, intervalos menores que el de la tabla y DIPs cerrados sin attachments se anotan como **observación**: aparecen en `HALLAZGOS`, pero no cambian el resultado.

## Ajustes

| Qué cambiar | Dónde |
| --- | --- |
| Qué reglas se revisan y cuáles son solo observación | `config/discrepancias.yaml` |
| Tolerancias (días, horas del cierre), lectura de ICAM | `config/config.yaml` |
| Manuales que no necesitan REV ni fecha en la cita (AMM, SRM, task card) | `config/config.yaml` (`referencia_tecnica`) |
| Palabras con las que se reconoce cada referencia Others | `config/catalogo_others.yaml` |
| TA, Parent Assembly, AMM/ECRA y RIR de cada ítem | `DIPs References.xlsx` |

Después de cambiar una regla, ejecute `.venv\Scripts\python -m dips_audit benchmark` y compare con la línea base (ver [docs/tecnico.md](docs/tecnico.md#10-benchmark)).

## Opciones de `auditar.bat`

| Opción | Uso |
| --- | --- |
| `--sin-icam` | Auditar solo con el Excel, sin leer ICAM (menos reglas) |
| `--hoja NOMBRE` | Hoja a leer. Por defecto, la que tiene `Fault Barcode` y `Fault Name` |
| `--fecha "AAAA-MM-DD HH:MM"` | Auditar como si fuera esa fecha y hora |
| `--sin-excel` | Mostrar el resultado solo en la consola |
| `--categorias TIPO ...` | Revisar solo esos tipos de discrepancia. Basta una parte del nombre: `"technical reference"` toma Missing e Incorrect Technical Reference |
| `--excluir-categorias TIPO ...` | Revisar todos menos esos tipos |

Ejemplos en consola:

```
auditar.bat "DIPs Audit (23SEP2026).xlsx" --sin-icam
auditar.bat "DIPs Audit (23SEP2026).xlsx" --categorias "Incorrect DIP Interval" RIR
auditar.bat "DIPs Audit (23SEP2026).xlsx" --excluir-categorias "Missing S/N"
```

Los nombres de los tipos: `.venv\Scripts\python -m dips_audit categorias`. `comparar.bat` acepta las mismas dos opciones. El filtro vale solo para esa ejecución; para desactivar un tipo siempre, use `config/discrepancias.yaml`.

## Problemas frecuentes

| Mensaje | Solución |
| --- | --- |
| "No hay sesión iniciada en ICAM" | El programa esperó 10 minutos sin que se iniciara sesión. Inicie sesión en la ventana de Edge de ICAM y vuelva a arrastrar el archivo |
| "La sesión de ICAM venció" | Inicie sesión de nuevo en esa ventana. Lo ya leído queda guardado |
| "Permission denied" al guardar | Cierre el Excel de salida si está abierto |
| "Faltan columnas obligatorias" | El Excel no tiene el formato esperado; ver [docs/tecnico.md](docs/tecnico.md#1-lectura-del-excel-de-entrada) |

## Documentos

| Documento | Tema |
| --- | --- |
| [tecnico.md](docs/tecnico.md) | Cómo funciona cada parte, en detalle |
| [proceso.md](docs/proceso.md) | Proceso en diagramas |
| [comparacion_modos.md](docs/comparacion_modos.md) | Registro: el auditor con y sin agente (modelo local), y por qué se eliminó |

Pruebas: `.venv\Scripts\python -m pytest`.
