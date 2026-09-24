# Auditor preliminar de DIPs

Audita los DIPs del Excel de entrada con los datos de ICAM y la tabla de referencias. Entrega un Excel con el resultado de cada DIP: **DISCREPANCIA**, **POSIBLE DISCREPANCIA** u **OK**. El auditor confirma cada resultado.

Proceso en diagramas: [docs/proceso.md](docs/proceso.md).

## Instalación

```bat
git clone https://github.com/lviloriabas/dips-ai.git
cd dips-ai
setup.bat
```

`setup.bat` instala Python y las librerías, verifica Edge y `DIPs References.xlsx`, instala Ollama con el modelo local (opcional) y corre las pruebas. Se puede correr varias veces. Opciones: `-SinModelo`, `-ModeloLiviano`, `-Modelo NOMBRE`, `-SinPruebas`.

## Uso

1. `abrir_icam.bat`: abre ICAM en el Edge del programa. Iniciar sesión y dejar la ventana abierta.
2. Arrastrar el Excel de entrada sobre `auditar.bat`.
3. Abrir el Excel de salida en `salidas/` y filtrar la columna `RESULTADO`.

Sin sesión en ICAM, el programa avisa y termina.

| Opción de `auditar.bat` | Uso |
| --- | --- |
| `--sin-icam` | Auditar solo con el Excel de entrada |
| `--hoja NOMBRE` | Hoja a leer. Por defecto, la que tiene `Fault Barcode` y `Fault Name` |
| `--fecha AAAA-MM-DD` | Fecha de auditoría. Por defecto, hoy |
| `--icam RUTA` | Datos de ICAM ya leídos (`data/icam/`, JSON o CSV) |
| `--llm` | Modelo local. Experimental: no mejora el resultado ([detalle](docs/comparacion_modos.md)) |
| `--sin-excel` | Resultado solo en consola |

## Lectura de ICAM

Por barcode, con la sesión del Edge de ICAM:

1. Barcode Search (`POST /maintenix/servlet/ScanBarcode`) abre el DIP.
2. Se leen las pestañas Task Execution, Fault Information, Task Information, Scheduling e History.
3. RIR: se lee Follow-on Tasks con "Show Historical Tasks" (RIR cerrados) y la página de cada RIR vigente (Scheduling y Task Information).
4. Se guarda `data/icam/<barcode>.json`. Un DIP ya leído no se vuelve a leer.

| Control | Cómo |
| --- | --- |
| Solo lectura | Las únicas consultas a ICAM son la búsqueda y la lectura de las pestañas. No se abre ningún formulario de edición ni corre código de ICAM |
| Rapidez | Sin dibujar páginas ni descargar imágenes. 3 DIPs a la vez, pestañas en paralelo |
| Sin errores | Cada respuesta se valida (DIP, barcode y contenido). 3 reintentos por consulta. Un DIP incompleto no se guarda. Si la sesión vence, se detiene y lo leído queda guardado |

Solo leer ICAM: `.venv\Scripts\python -m dips_audit extraer-icam "entrada.xlsx"`. Probar un DIP: `extraer-icam --barcode T40S0099FC1`. Ajustes en la sección `icam` de `config/config.yaml`. `data/` y `.icam_perfil/` no se suben al repositorio.

## Qué revisa

| Regla | Si falla |
| --- | --- |
| Intervalo mayor que el TA de la referencia | CRÍTICA |
| Tipo de intervalo distinto (días, FH, FC) | CRÍTICA |
| Parent Assy distinto (AIRCRAFT / ENGINE) | CRÍTICA |
| Due date después del vencimiento del ítem | CRÍTICA |
| DIP activo vencido o cerrado fuera de plazo | CRÍTICA |
| Referencia técnica sin manual, REV o fecha de la REV | NO CRÍTICA |
| Referencia técnica de otra referencia de la tabla | NO CRÍTICA |
| Intervalo 0 o Usage Remaining mayor que el intervalo | NO CRÍTICA |
| DIP duplicado, S/N repetido o Deferral Reference distinto del ATA | NO CRÍTICA |
| RIR faltante (la tabla pide RIR) o con intervalo distinto | NO CRÍTICA |
| RIR sin un límite del T/A (p. ej. CYCLES y CDY) o en otro Parent Assembly | NO CRÍTICA |
| RIR con Start distinto del T/A | Revisar |
| Sin referencia en la tabla, sin intervalo, due date dudoso, tarea que la tabla no tiene | Revisar |

- La referencia se reconoce por palabras clave del Fault Name (`config/catalogo_others.yaml`), con errores de escritura (`FUNIGATION`) y siglas con puntos (`P.O.B`). Si el Fault Name no alcanza, se usa el número de tarea de la referencia técnica.
- La referencia técnica (manual + REV + fecha) se busca en la descripción y en el resto del DIP, en cualquier orden: `AMM TASK 12-15-21-200-801 … REV 28, 15-MAY-2026`.
- RIR: en ICAM son Follow-on Tasks ADHOC del DIP (las REQ, como el servicio de taller, no son RIR). El intervalo sale de la página del RIR o de la diferencia entre la tarea ACTV y la FORECAST (594 → 1394 CYCLES = 800 FC). La columna `RIR EN ICAM` muestra cada RIR con su intervalo.
- Attachments quedan como verificación manual. La columna `ADJUNTOS EN ICAM` muestra los attachments del DIP.
- La severidad de cada regla se cambia en `config/config.yaml`.

## Resultado

| `RESULTADO` | Significa |
| --- | --- |
| DISCREPANCIA | Falló una regla, crítica o no crítica. `HALLAZGOS` indica lo encontrado y lo que corresponde |
| POSIBLE DISCREPANCIA | Falta un dato o la referencia no está en la tabla. Revisar a mano |
| OK | No falló ninguna regla. Quedan las verificaciones manuales |

Hojas del Excel de salida:

| Hoja | Contenido |
| --- | --- |
| Dashboard | Indicadores y gráficos: % de DISCREPANCIA, POSIBLE DISCREPANCIA y OK; DIPs por tipo; tipos de discrepancia; referencias con más discrepancias |
| Resumen | Archivo, fecha, conteo por estado y por tipo de discrepancia |
| Auditoría | Un DIP por fila: `RESULTADO`, `ESTADO IA`, `HALLAZGOS`, `COMENTARIO SUGERIDO`, referencia, TA, `REFERENCIA TÉCNICA DEL DIP`, `RIR EN ICAM`, `ADJUNTOS EN ICAM` y las columnas del Excel de entrada |
| Hallazgos | Un hallazgo por fila, con severidad |

El Excel de entrada no se modifica.

## Benchmark

| Modo | Comando | Tarda |
| --- | --- | --- |
| Sin modelo | `benchmark_sin_modelo.bat` | 1 s |
| Con modelo | `benchmark_con_modelo.bat` (necesita Ollama) | 15 min en CPU |

Audita 50 DIPs Others ya auditados (`benchmark/dips_auditados.xlsx`, copia anónima del histórico) y 46 Fault Names de prueba (`benchmark/casos_modelo_local.yaml`). Compara con la línea base de su modo (`benchmark/linea_base_<modo>.json`): si un indicador empeora, lo avisa y termina con código 2. Si el cambio es intencional, copiar el JSON del resultado sobre la línea base. Resultados en `benchmark/resultados/<modo>/`.

Resultado actual (Ryzen 5 3600, sin GPU): `sin_modelo/2026-09-23_234440.md` y `con_modelo/2026-09-24_000003.md`.

| Indicador | Sin modelo | Con modelo |
| --- | ---: | ---: |
| Coincide con el auditor | 40 de 50 | 40 de 50 |
| OK del auditor con discrepancia del programa | 3 de 44 | 3 de 44 |
| OK del auditor en Revisar | 3 de 44 | 3 de 44 |
| Discrepancias del auditor que el programa marca | 2 de 6 | 2 de 6 |
| Fault Names de prueba bien asociados | 24 de 46 | 44 de 46 |
| Referencias equivocadas aceptadas | 0 | 0 |
| Tiempo | 1 s | 15 min (20 s por consulta, 5.3 GB de RAM) |

- La muestra tiene solo 6 discrepancias; cada una vale 17 puntos. Con los 915 DIPs del histórico, el modelo cambia 7 DIPs y los 7 a peor ([docs/comparacion_modos.md](docs/comparacion_modos.md)).
- Las discrepancias que no se marcan dependen sobre todo de datos de ICAM (referencia técnica, S/N, attachments) y de criterios por acordar ([docs/automatizacion_auditoria.md](docs/automatizacion_auditoria.md)).
- Regenerar la muestra (requiere el histórico en la carpeta del proyecto): `.venv\Scripts\python -m dips_audit anonimizar`. Después, correr los dos modos y copiar los resultados como línea base.

## Configuración

| Archivo | Contenido |
| --- | --- |
| `DIPs References.xlsx` | Tabla de referencias: TA, Parent Assy, AMM/ECRA |
| `config/catalogo_others.yaml` | Palabras clave de cada referencia Others e intervalos por flota o condición |
| `config/config.yaml` | Severidades, tolerancias, ICAM y modelo local |

`python -m dips_audit referencias` muestra cómo se leyó la tabla y avisa si falta una fila Others en el catálogo.

## Documentos

| Documento | Tema |
| --- | --- |
| [proceso.md](docs/proceso.md) | Proceso en diagramas |
| [automatizacion_auditoria.md](docs/automatizacion_auditoria.md) | Cómo acercar el programa al auditor: métodos probados y plan |
| [comparacion_modos.md](docs/comparacion_modos.md) | Con y sin modelo local, 915 DIPs |
| [analisis_modelo_local.md](docs/analisis_modelo_local.md) | Análisis del modelo local |
| [analisis_icam_others.md](docs/analisis_icam_others.md), [flujo_auditoria_icam.md](docs/flujo_auditoria_icam.md) | ICAM: datos y flujo del auditor |

Pruebas: `.venv\Scripts\python -m pytest`.
