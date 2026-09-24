# ¿Hace falta el modelo local? Análisis de los dos modos del auditor

Análisis del 23-sep-2026. Compara el auditor en sus dos modos:

- **Sin modelo local**: solo reglas deterministas (Python). Es `auditar.bat` y `benchmark_sin_modelo.bat`.
- **Con modelo local**: las mismas reglas más `ministral-3:8b` en Ollama. Es `auditar.bat --llm` y `benchmark_con_modelo.bat`.

## Conclusión

Para la fase 1 (DIPs Others auditados desde el Excel de entrada), **el modo sin modelo alcanza**. El modelo no cambió el resultado de ningún DIP, ni en la muestra del benchmark ni en el histórico completo. Su única contribución real se puede lograr con reglas, sin costo.

| | Sin modelo | Con modelo |
| --- | ---: | ---: |
| DIPs Others del histórico cuyo estado cambia (de 528) | - | **0** |
| Referencias correctas sugeridas en esos 528 DIPs | 0 | 1 |
| Referencias equivocadas aceptadas | 0 | 0 |
| Tiempo por consulta en CPU (i7-1265U) | - | 39 s |
| Memoria adicional | 0 | 5.3 GB (de 16 GB) |
| Instalación adicional | nada | Ollama y 6 GB de modelo |
| Mismo resultado en cualquier equipo | sí | no (1 de 46 casos cambia entre CPU y GPU) |

**Actualización con los 915 DIPs del Excel original, en CPU** ([comparacion_modos.md](comparacion_modos.md)): el modelo aceptó 14 referencias, de las cuales 1 es correcta, 11 equivocadas y 2 dudosas. También convirtió 7 DIPs que el auditor dio OK en discrepancias falsas: generadores de oxígeno de pasajeros sin intervalo en el Excel. Cuando falta el intervalo, la validación de intervalo no puede descartar la sugerencia. En GPU, con los 528 DIPs que sí tienen intervalo, esos mismos generadores se habían rechazado. Sin modelo, la auditoría de los 915 DIPs tarda 2.4 s; con modelo, 30 min.

Recomendación: usar el modo sin modelo como modo oficial y dejar el modelo como opción experimental (`--llm`), sin instalarlo en los equipos del departamento (`setup.bat -SinModelo`). Conviene revisarlo de nuevo si el auditor empieza a leer texto libre, como attachments, comentarios u otros tipos de DIP (ver [sección 7](#7-cuándo-volver-a-evaluar-el-modelo)).

## 1. Qué hace el modelo y qué no puede hacer

El modelo no es un agente: no navega, no decide pasos y no usa herramientas. Es **una sola consulta de clasificación** con respuesta cerrada. Recibe el Fault Name, el intervalo y 6 referencias candidatas, y debe elegir una o responder NINGUNA.

Por diseño, su alcance es muy limitado:

1. Solo se consulta cuando las reglas no encuentran la referencia del DIP: 11% de los DIPs del histórico.
2. Lo que sugiere se valida con reglas: debe compartir una palabra distintiva con el Fault Name y el intervalo debe ser compatible con el TA.
3. Todo DIP que pasa por el modelo queda en **REVISAR**, igual que sin modelo. El modelo nunca marca OK ni discrepancia.

Por lo tanto, **el modelo no puede cambiar si el programa coincide o no con el auditor**. Sin modelo, un DIP sin referencia queda en REVISAR. Con modelo también queda en REVISAR, con o sin referencia sugerida. Lo único que puede aportar es ahorrarle al auditor la búsqueda de la referencia en esos DIPs.

## 2. Resultado de los dos modos en el benchmark (50 DIPs)

Resultados en `benchmark/resultados/sin_modelo/2026-09-23_175657.md` y `benchmark/resultados/con_modelo/2026-09-23_152638.md`.

| Indicador | Sin modelo | Con modelo |
| --- | ---: | ---: |
| Coincide con el auditor (OK o discrepancia) | 42 de 50 | 42 de 50 |
| OK del auditor que el programa marca con discrepancia | 3 de 44 | 3 de 44 |
| OK del auditor que el programa deja en REVISAR | 3 de 44 | 3 de 44 |
| Discrepancias del auditor que el programa marca | 4 de 6 | 4 de 6 |
| DIPs consultados al modelo | - | 5 (respondió NINGUNA en los 5) |
| Casos: con referencia, asociados a la correcta | 0 de 26 | 24 de 26 |
| Casos: sin referencia, quedan sin referencia | 20 de 20 | 20 de 20 |
| Casos: referencia equivocada aceptada | 0 de 46 | 0 de 46 |
| Tiempo total | 1 s | 33 min |

En la auditoría los dos modos son idénticos. La diferencia aparece solo en los 46 casos de `benchmark/casos_modelo_local.yaml`, que se escribieron para medir al modelo. La sección 4 explica por qué esos casos exageran su aporte.

## 3. En el histórico completo (528 DIPs Others)

La muestra del benchmark tiene solo 5 DIPs sin referencia, así que se repitió la comparación con **todos** los DIPs Others del histórico que tienen veredicto e intervalo. Son 528 DIPs auditados entre el 13-jul y el 21-ago-2026: 464 OK, 53 con discrepancia no crítica y 11 críticas.

- Las reglas asocian **468 de 528** (88.6%). Quedan 60 sin referencia, que en el modo con modelo se le consultan.
- De esos 60, **solo 2 tienen referencia Others** en `DIPs References.xlsx`: `DIP FUNIGATION DATE` (fumigación, con error de escritura) y `DIP - NOSE INTERNAL INSPECTION` (radomo). Los otros 58 son estructuras, puertas de acceso de tanques, motores, generadores de oxígeno de pasajeros, rodillos de carga, etc. No tienen referencia Others, así que la respuesta correcta para ellos es "ninguna".

Resultado de cada método sobre esos 60 DIPs:

| Método | Referencias correctas (de 2) | Referencias equivocadas aceptadas (de 58) | DIPs cuyo estado cambia (de 528) |
| --- | ---: | ---: | ---: |
| Solo reglas (modo sin modelo) | 0 | 0 | - |
| Modelo local (modo con modelo) | 1 (fumigación) | 0 | **0** |
| Más parecido (alternativa sin modelo del benchmark) | 2 | **12** | **6** (discrepancias falsas) |
| Reglas con tolerancia a errores de escritura (prototipo, sección 5) | 1 (fumigación) | 0 | 0 |

En los indicadores frente al auditor, la auditoría completa con modelo da exactamente lo mismo que sin modelo: 384 de 528 coinciden, 16 de 64 discrepancias marcadas, 38 falsas discrepancias y 58 REVISAR de más, en los dos modos.

**El aporte real del modelo es 1 referencia bien sugerida en 528 DIPs (0.2%), y ese DIP queda en REVISAR igual.**

Volumen esperado: el histórico tiene 16.5 DIPs Others por día de auditoría (máximo 100 en un día). Con 11% sin referencia, serían unas 2 consultas por día y 11 en el peor día. En CPU eso son unos 2 minutos por día y 8 en el peor día. El tiempo no es el problema: el problema es que el modelo no aporta.

## 4. Por qué los 46 casos exageran el aporte del modelo

En los casos del benchmark, el modelo resuelve bien 44 de 46 y el modo sin modelo solo 20. Pero:

- **25 de los 26 casos con referencia son inventados** (`CREW 02 BOTLE LOW`, `BRK 4 PIN FLUSH`, `KIT MEDICO DE EMERGENCIA...`). Solo `DIP - NOSE INTERNAL INSPECTION` aparece en el histórico, y **ese caso real el modelo lo falla** (responde NINGUNA).
- 14 de los 20 casos sin referencia sí son reales, y en esos el modelo y las reglas coinciden: todos quedan sin referencia.
- Los casos inventados miden sinónimos, abreviaturas y español. En 528 DIPs reales eso casi no aparece: el único caso resoluble fue un error de escritura.

Los casos siguen siendo útiles para ajustar el modelo si algún día se usa, pero no sirven para decidir si hace falta. Para eso vale el histórico real.

## 5. Alternativas deterministas

**"Más parecido" no sirve.** Es la alternativa sin modelo que compara el benchmark con modelo: elige la referencia con más palabras en común y la valida igual que al modelo. En los casos parecía casi tan buena (43 de 46, con 2 errores). En los datos reales acepta **12 referencias equivocadas de 58**. Por ejemplo, asocia "PASSENGER OXYGEN GENERATOR" (7 DIPs) a la botella portátil de oxígeno y "CARGO CEILING SHROUD" al extintor de carga. Con la referencia equivocada, 6 de esos generadores pasan de REVISAR a una discrepancia no crítica que no existe. La validación por palabra distintiva es débil cuando la palabra en común es OXYGEN o CARGO. El programa no la usa, y así debe seguir.

**Reglas con tolerancia a errores de escritura (prototipo).** Aplica las mismas palabras clave del catálogo, pero acepta una palabra de 5 letras o más si es al menos 85% parecida (`FUNIGATION` ≈ `FUMIGATION`). También valida el intervalo contra el TA. Resultados:

- En los 468 DIPs que ya asocian las reglas, no cambia ninguna asociación.
- De los 60 sin referencia, asocia bien fumigación, igual que el modelo, y no acepta ninguna equivocada.
- En los 46 casos resuelve 4 casos más con referencia. No resuelve sinónimos (`BRK` = brake), que se pueden agregar a los sinónimos de `dips_audit/texto.py` o al catálogo cuando aparezcan en datos reales.

Con esto, el modo sin modelo iguala al modelo en los datos reales, sin costo y con un resultado explicable. El prototipo no está integrado al programa todavía.

## 6. Costos y riesgos del modelo

- **Recursos:** 5.3 GB de RAM de los 16 GB del equipo, 25 s de carga y 39 s por consulta en CPU. Los equipos del departamento no tienen GPU.
- **Instalación y mantenimiento:** Ollama como servicio, 6 GB de descarga y actualizaciones del modelo. Cada versión nueva del modelo o de Ollama obliga a medir de nuevo con el benchmark.
- **Reproducibilidad:** incluso con temperatura 0, el mismo modelo dio una respuesta distinta en CPU y en GPU. Con `DIP-EMERGENCY LOCATER TRANSMITER BATERY`, eligió ELT portátil en CPU y ELT fijo en GPU. Las reglas dan el mismo resultado en cualquier equipo.
- **Explicación al auditor:** una regla se puede mostrar ("contiene FUMIGATION"). La justificación del modelo es texto generado, que puede sonar convincente sin ser la razón real.

## 7. Cuándo volver a evaluar el modelo

El modelo tendría sentido si el auditor empieza a leer texto libre que las reglas no cubren bien:

- attachments, referencias técnicas o PDFs de ICAM (hoy son verificación manual);
- comentarios o descripciones largas;
- otros tipos de DIP (Structures, Powerplant) con vocabulario más variado.

Criterio para adoptarlo: en DIPs **reales**, el modo con modelo debe cambiar el resultado frente al auditor, o sugerir bien la referencia en una fracción relevante de DIPs (por ejemplo, más de 1%), sin aceptar referencias equivocadas y ganándole a las reglas con tolerancia. Para medirlo, corra los dos benchmarks con una muestra más grande (`anonimizar --cantidad 0`).

## 8. Dónde está el margen de mejora (y el modelo no ayuda)

El histórico completo muestra que el cuello de botella no es encontrar la referencia:

- **Discrepancias del auditor que no se marcan: 48 de 64.** Las 48 tienen referencia encontrada por las reglas, así que el modelo no interviene en ninguna. Por el comentario del auditor, 16 no tienen comentario, 10 son de intervalo o due date, 9 de S/N, 7 de attachments y el resto son duplicados, RIR u otros.
- **Falsas discrepancias: 38 de 464 OK.** Se deben a `intervalo_excedido` (23), `tipo_intervalo_incorrecto` (8), `duplicado` (6) y otros. Es calibración de la tabla y las reglas; por ejemplo, amortiguadores MAX y extintor de agua abierto en horas.
- **REVISAR de más: 58 de 464 OK.** 54 son DIPs sin referencia Others, en los que el modelo también responde NINGUNA. Se resuelven completando la tabla o revisando si corresponden a Structures o Powerplant.

**Cuidado con la muestra de 50:** en ella el programa marca 4 de 6 discrepancias (67%), pero en el histórico completo marca **16 de 64 (25%)**. Antes de presentar la tasa de detección, conviene ampliar la muestra del benchmark.

## Cómo se obtuvieron los números

- Muestra de 50: `benchmark_sin_modelo.bat` y `benchmark_con_modelo.bat`. El modo con modelo se midió en un i7-1265U sin GPU.
- Histórico completo: copia anónima de todos los Others con veredicto e intervalo (`anonimizar --cantidad 0`), auditada con los dos modos. Las respuestas del modelo sobre los 60 DIPs sin referencia se obtuvieron en GPU (RTX 3070), con la misma configuración. El tiempo por consulta en CPU es el del benchmark. Estos archivos no se suben porque el histórico no está en el repositorio.
- Qué DIPs tienen referencia: se revisaron uno por uno los 60 Fault Names contra `DIPs References.xlsx`, junto con las etiquetas de `benchmark/casos_modelo_local.yaml`.
