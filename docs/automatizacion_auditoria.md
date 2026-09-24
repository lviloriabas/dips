# Cómo acercar la auditoría automática a la manual

Análisis del 23-sep-2026 con los 915 DIPs del Excel de entrada del histórico (628 Others con nombre), comparados con el veredicto de los auditores. Se probaron métodos con y sin IA para asociar el Fault Name a su referencia, y se estudió por qué el veredicto del programa no coincide con el del auditor.

## Conclusiones

1. **La asociación del Fault Name a su referencia está casi resuelta sin agentes.** Las reglas del catálogo, con tolerancia a errores de escritura y a siglas con puntos, aciertan 627 de 628 sin ninguna referencia equivocada. Los clasificadores y los embeddings no las superan en DIPs reales, y usados solos aceptan entre 19 y 72 referencias equivocadas.
2. **La mejor forma de confirmar la referencia técnica es la propia referencia técnica.** El número de tarea AMM o ECRA que el DIP tiene en ICAM se compara de forma exacta con la columna `REFERENCES` de la tabla. Es determinista y confirma a la vez la asociación y la referencia técnica (sección 3).
3. **Lo que separa al programa del auditor no es la IA, son los datos y los criterios.** Casi todas las discrepancias que el programa no marca dependen de datos que no están en el Excel (S/N, adjuntos, descripción completa, historial del deadline) o de criterios que no están escritos.
4. **Los auditores no aplican siempre el mismo criterio.** El mismo caso a veces se marca y a veces no, y las auditorías de julio marcaban menos que las de agosto. Por eso no se puede coincidir casi al 100% con el histórico tal como está. Sí se puede coincidir casi al 100% con un **criterio escrito y acordado**.
5. **Hay que medir de otra forma.** Responder siempre "OK" coincide con el auditor el 87.1% de las veces, porque solo el 13% de los DIPs tiene discrepancia. Lo que importa es cuántas discrepancias detecta el programa y cuántas falsas alarmas da.

## 1. Qué dice la investigación

- En textos de mantenimiento cortos, abreviados y con errores de escritura, **la calidad y la elección del registro pesan más que el modelo**. En un estudio con datos de GE Aerospace, pasar del reporte del cliente al del técnico mejoró el resultado más que cualquier cambio de arquitectura. Además, el 75% de los "errores" del clasificador eran inconsistencias entre el texto y la etiqueta ([arXiv 2609.16267](https://arxiv.org/html/2609.16267v1)).
- Estos textos requieren diccionarios de abreviaturas y términos del dominio ([MaintNet](https://aclanthology.org/2020.coling-demos.2/)). Es lo que hacen hoy el catálogo y los sinónimos de `dips_audit/texto.py`.
- Con pocos datos etiquetados, las alternativas livianas a un agente son los embeddings pequeños (66 a 123 ms por texto en CPU) ([modelos de embeddings en Ollama](https://www.morphllm.com/ollama-embedding-models), [EmbeddingGemma](https://arxiv.org/pdf/2509.20354)), los clasificadores few-shot como SetFit, que se entrenan en CPU en minutos ([SetFit](https://github.com/huggingface/setfit)), y la supervisión débil, que usa las reglas como etiquetadores ruidosos de un clasificador ([Snorkel](https://snorkel.ai/data-centric-ai/weak-supervision/)).
- ICAM (IFS Maintenix) calcula y guarda el deadline de cada tarea ([Task deadlines](https://docs.ifs.com/maintenix/Operator/enduser/Maintenance_Planning/c_task_deadlines.html)). Las versiones de IFS con API REST (OData) permitirían leerlo sin navegar la página ([IFS RESTful APIs](https://docs.ifs.com/techdocs/Foundation1/010_overview/240_integration/400_rest_apis/)); habría que confirmar con TI si la versión instalada lo permite.

## 2. Asociación del Fault Name: métodos probados

Las etiquetas salen de dos fuentes. En los 534 DIPs que asocian las reglas, la etiqueta es la asociación por reglas. Los 94 que las reglas no asocian se revisaron a mano: 3 tienen referencia Others (fumigación mal escrita, radomo y "P.O.B DUE DATE") y 91 no. La validación cruzada está **agrupada por nombre**: ningún DIP se evalúa con su mismo nombre en el entrenamiento, como pasa con un DIP nuevo. Los 46 casos del benchmark son en su mayoría inventados y sirven como prueba de vocabulario.

| Método | IA | Aciertos (628) | Referencias equivocadas | Con referencia entre los difíciles (3) | Casos inventados (46) | Costo por DIP en CPU |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Reglas (actual) | No | 625 | 0 | 0 | 20 | < 1 ms |
| **Reglas + tolerancia a errores de escritura y siglas** | No | **627** | **0** | 2 | 24 | 3 ms |
| TF-IDF de caracteres contra la tabla | No | 552 | 56 | 3 | 25 | < 1 ms |
| Vecino más parecido del histórico (TF-IDF) | No | 548 | 72 | 2 | 38 | < 1 ms |
| Clasificador lineal entrenado (TF-IDF) | Sí, liviana | 530 | 19 | 0 | 25 | < 1 ms |
| Híbrido: reglas + vecino TF-IDF + validación | Sí, liviana | 622 | 5 | 2 | 40 | 4 ms |
| Híbrido: reglas + clasificador + validación | Sí, liviana | 627 | 0 | 2 | 29 | 11 ms |
| Embeddings contra la tabla (embeddinggemma / nomic / bge-m3) | Sí, liviana | 500 / 568 / 545 | 28 / 52 / 53 | 2 / 3 / 1 | 31-32 | 66-123 ms |
| Híbrido: reglas + embeddings + validación | Sí, liviana | 627 | 0 | 2 | 25-26 | 70-125 ms |
| Agente (ministral-3:8b), 95 DIPs difíciles | Sí, pesada | - | 11 (+2 dudosas) | 1 | 44 | 20-40 s |

"Validación" significa que el intervalo del DIP debe ser compatible con el TA de la referencia sugerida. Si el DIP no tiene intervalo, la sugerencia no se acepta. Ese hueco dejó pasar 11 referencias equivocadas del agente en la corrida de los 915 DIPs, y **ya está corregido en `--llm`**.

Lecturas:

- **En los DIPs reales, nada supera a las reglas con tolerancia.** Los métodos aprendidos ganan solo en los casos inventados (sinónimos como `BRK` o `AIL`), y solo si se les agrega la validación.
- **Los embeddings son baratos, no costosos:** unos 70 ms por DIP en CPU, sin comparación con los 20 a 40 s del agente. Pero comparados contra la tabla confunden referencias parecidas, y no aportan si no se validan.
- El radomo ("NOSE INTERNAL INSPECTION") no lo resuelve ningún método determinista. Se agrega como sinónimo en el catálogo cuando los auditores lo confirmen.
- **Implementado:** las reglas ahora toleran errores de escritura y siglas con puntos. En los 915 DIPs cambian solo 4 asociaciones, las 4 nuevas y correctas (fumigación, POB y 2 filtros de combustible de Powerplant), sin cambiar ninguna existente.
- Recomendación: **reglas + tolerancia a errores de escritura y siglas** como método oficial. Como ayuda opcional, un vecino por embeddings o TF-IDF que solo *sugiera* la referencia en REVISAR, siempre con la validación estricta.

## 3. Confirmar la referencia técnica y el intervalo

- **Implementado** (`dips_audit/referencia_tecnica.py`). El dato sale de la columna `Technical References` del Excel de entrada, si la trae, o de un archivo de ICAM con `auditar --icam`. Un DIP sin el dato no se revisa; un DIP con el dato vacío no tiene referencia técnica. Severidades en `config/config.yaml`: `sin_referencia_tecnica` y `referencia_tecnica_equivocada` son NO CRÍTICA, y `referencia_tecnica_distinta` es REVISAR. Las filas cuya columna `REFERENCES` está vacía, como ELT, EMK o FAK, no se revisan. Varias filas comparten tarea, como las SMT con `05-00-00-750-801` o los cables con el ECRA `2700-0333C`: ahí la tarea confirma el tema, y el Fault Name decide la referencia.
- **Referencia técnica.** La tabla trae en `REFERENCES` la tarea AMM y el ECRA de cada fila (por ejemplo `AMM TASK 32-44-00-790-801; ECRA 3244-0178C`). El DIP trae en ICAM, en Task Information › Technical References, la referencia cargada. Con una expresión regular (`\d{2}-\d{2}-\d{2}-\d{3}-\d{3}` para AMM y `\d{4}-\d{4}[A-Z]?` para ECRA) se comparan de forma exacta:
  - Si coincide la tarea completa, la referencia técnica es correcta y además **confirma la asociación**, con más certeza que el nombre.
  - Si coincide solo capítulo-sección-tema (`12-15-21`), el tema es el mismo pero la tarea es otra: "referencia técnica distinta" (el caso T40S009DV6S de [analisis_icam_others.md](analisis_icam_others.md)).
  - Si falta, se aplica el criterio de adjuntos y referencia técnica que acuerden los auditores.
- **Intervalo.** Ya es determinista (TA por flota y condición en el catálogo). Lo que falta es el dato: 100 DIPs Others no traen intervalo en el Excel, y ICAM lo tiene en Scheduling. Además hay que ajustar los criterios de la sección 5, como los meses de calendario.

## 4. Por qué el programa no coincide con el auditor

De los 619 DIPs Others con veredicto, el programa coincide en 400 (64.6%). Los 219 desacuerdos se dividen así:

| Causa | DIPs | Qué lo resuelve |
| --- | ---: | --- |
| Auditor OK, programa REVISAR: sin referencia Others | 55 | Criterio: "sin referencia Others" como verificación manual, no como REVISAR |
| Auditor OK, programa REVISAR: sin intervalo en el Excel | 42 | Intervalo desde ICAM (Scheduling) |
| Auditor OK, programa REVISAR: sin referencia y sin intervalo | 32 | Las dos anteriores |
| Auditor OK, programa discrepancia (falsas alarmas) | 38 | Calibrar 3 filas de la tabla: amortiguador del tren principal (13), bleed PM sensor (9) y bleed FAMV (4) |
| Auditor OK, programa REVISAR: due date | 4 | Historial del deadline en ICAM |
| Auditor discrepancia, programa OK | 48 | Datos de ICAM y criterios escritos (sección 5) |

Las 48 discrepancias que no se marcan, según el comentario del auditor: 16 sin comentario, 10 de intervalo o due date, 9 de S/N, 7 de adjuntos o referencia técnica, y 6 de duplicados, RIR u otros. **Las 48 tienen referencia encontrada por las reglas**: ningún método de asociación, con o sin IA, cambia este número.

Un modelo entrenado con los hallazgos que se sacan del Excel, con validación cruzada, **no detecta ninguna** de las 80 discrepancias. Calibrar la severidad de cada hallazgo por referencia con el histórico baja las falsas alarmas de 38 a 3, pero también detecta menos: 5 en vez de 10. Con lo que trae el Excel no alcanza para imitar al auditor.

## 5. Criterios de los auditores y posibles discrepancias no marcadas

Algunos criterios se aplican de forma consistente y se pueden escribir como reglas. Otros cambian según el auditor o el mes. Julio marcaba menos: esas auditorías antiguas tienen discrepancias que no se registraron.

| Criterio | Marcadas | OK en julio | OK en agosto | Estado |
| --- | ---: | ---: | ---: | --- |
| Descontaminación hidráulica sin intervalo | 9 | 0 | 2 | Consistente: pasar a regla |
| Bleed control card con intervalo excedido | 5 | 0 | 1 | Consistente: ya es regla |
| Oxígeno de tripulación con intervalo menor al de su condición | 3 | 0 | 8 | Lo escriben en sus comentarios ("debe ser reemplazada en un plazo de 3 DAY"): confirmar |
| Re-tensión de cables a más de 6 meses de calendario | 3 | 6 | 2 | Julio no lo marcaba: confirmar y contar meses de calendario |
| Microbiano con intervalo menor a 4 días | 1 | 0 | 4 | Confirmar |
| ATA distinto al de la referencia (halón, extintor de agua, filtro de motor) | 8 | 5 | 12 | Inconsistente: decidir |
| Sin S/N en la descripción | 22 | 35 | 101 | Inconsistente (julio 8%, agosto 16%): decidir |
| Amortiguador del tren principal por encima de 10 FC | 0 | 2 | 11 | Nunca se marca: revisar el TA de la tabla |

- **23 DIPs** que el auditor dio OK cumplen un criterio consistente. Son posibles discrepancias no marcadas.
- Con los criterios que faltan decidir (S/N y ATA), son **159**.
- La lista, con el comentario del auditor y los hallazgos del programa, está en `salidas/posibles_discrepancias_no_marcadas.xlsx`. No se sube al repositorio.

## 6. Plan recomendado

Cada paso se mide con el benchmark, en detecciones y falsas alarmas, no solo en coincidencia.

1. **Reglas + tolerancia a errores de escritura y siglas** en el programa. Sin costo, y resuelve fumigación y POB. Pendiente de integrar: el prototipo ya se midió.
2. **Sesión de criterios con los auditores** para decidir los criterios "a confirmar" y "decidir" de la sección 5, y los TA de amortiguador MLG, bleed PM sensor y bleed FAMV. El resultado va a `config/config.yaml` (severidad por referencia) y al catálogo. Solo con las 3 filas se eliminan 26 de las 38 falsas alarmas.
3. **Revisar las posibles discrepancias** (23 fuertes y 136 a confirmar) y **reetiquetar el histórico** con el criterio acordado. Ese es el patrón para medir "casi 100%": el histórico actual mezcla criterios distintos.
4. **Datos de ICAM** (sección 7): intervalo y deadline, referencia técnica, adjuntos, S/N removido, RII y marca AUDITDIP. Cubre los 100 DIPs sin intervalo y la mayoría de las discrepancias que hoy no se ven.
5. **"Sin referencia Others"** pasa a un estado propio de verificación manual y deja de contar como REVISAR. Revisar además si esos DIPs corresponden a filas de Structures o Powerplant: por ejemplo, selladores o reparación de puerta abiertos como Others.

Estimación sobre los 619 DIPs, antes de ICAM, medida en la misma muestra y por lo tanto optimista:

| Paso | Coinciden | Detectadas (de 80) | Falsas alarmas |
| --- | ---: | ---: | ---: |
| Programa actual | 400 | 32 | 171 |
| + "sin referencia Others" como verificación manual | 481 | 26 | 84 |
| + intervalo desde ICAM (suponiendo que es correcto) | 507 | 10 | 42 |
| + 3 filas de la tabla calibradas | 532 | 9 | 16 |

Las falsas alarmas bajan de 171 a 16, pero las detecciones también bajan. Muchas de las "detecciones" actuales eran DIPs que quedaban en REVISAR por falta de datos, no errores encontrados por las reglas. Para subir las detecciones hacen falta los pasos 2 a 4: criterios escritos y datos de ICAM.

## 7. Extracción de ICAM

**Implementado:** el programa lee ICAM por barcode (`auditar.bat` con la sesión abierta en `abrir_icam.bat`). Ver [proceso.md](proceso.md). Lo que sigue quedó como referencia de la extracción manual.

La lista de barcodes, ordenada por prioridad, está en `salidas/barcodes_para_icam.csv`:

- **Prioridad 1 (71):** las 48 discrepancias que el programa no marca y las 23 posibles discrepancias fuertes.
- **Prioridad 2 (98):** DIPs sin intervalo en el Excel, sin contar los que ya están en prioridad 1.
- **Prioridad 3 (125):** posibles discrepancias a confirmar.
- **Prioridad 4 (335):** resto de los Others.
- **Prioridad 5 (286):** Structures y Powerplant.

Solo lectura: Barcode Search y pestañas, sin tocar ningún botón de edición (lista en [flujo_auditoria_icam.md](flujo_auditoria_icam.md)). Una fila por barcode, en un Excel o CSV con estas columnas:

| Columna | Pestaña de ICAM | Para qué |
| --- | --- | --- |
| `barcode` | - | Clave |
| `fault_status`, `fault_severity`, `deferral_class`, `deferral_reference` | Fault Information | Deferral Reference contra ATA |
| `found_on_date` | Fault Information | Inicio del plazo |
| `description` | Task Execution › Description | Condición, S/N, fecha de vencimiento del ítem, plazo declarado |
| `parent_assembly` | Task Information | Parent assy |
| `technical_references` | Task Information › Technical References | Tareas AMM y ECRA (todas, separadas por `;`) |
| `auditdip_marks` | Task Information › Technical References | `DIP OPEN/CLOSED - RT AUDIT COMPLETED` |
| `attachments` | Task Information › Attachments | Cantidad y nombres de archivo |
| `due_driver`, `due_interval`, `due_start`, `due_deadline`, `due_extension`, `usage_remaining` | Scheduling (una fila por límite; si hay dos, `due2_*`) | Intervalo, tipo, límites dobles y extensiones |
| `deadline_changes` | History | Cada "deadline has been modified from X to Y" con su fecha |
| `sn_removed`, `sn_installed`, `pn` | Task Execution › Part Requirements | Cruce de S/N |
| `rii_required`, `rii_done` | Task Execution › Labor | RIR/RII |
| `actual_end_date` | Details | Cierre dentro del plazo |

Con ese archivo se puede medir cuánto sube la detección con datos de ICAM. Para reconstruir lo que vio el auditor, el historial de cambios del deadline se cruza con la fecha de auditoría.

## Cómo se obtuvieron los números

Los scripts de los experimentos se corrieron fuera del repositorio, porque el histórico tiene nombres del personal:

- Asociación: 10 particiones agrupadas por nombre.
- Veredicto: 10 particiones estratificadas, y también calibración con julio y prueba con agosto.
- Embeddings: Ollama en CPU (`num_gpu=0`), en un Ryzen 5 3600.
- Agente: la corrida de los 915 DIPs en CPU de [comparacion_modos.md](comparacion_modos.md).
