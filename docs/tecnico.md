# Cómo funciona el auditor de DIPs

Este documento explica, paso a paso, qué hace el programa con cada DIP y por qué. Está escrito para quien necesita entender o ajustar el programa. Para usarlo alcanza con el [README](../README.md).

## Resumen

El programa hace lo mismo que un auditor, en este orden:

1. **Lee el Excel de entrada** (por ejemplo `DIPs Audit (23SEP2026).xlsx`) y ordena sus datos.
2. **Lee cada DIP en ICAM**: referencia técnica, adjuntos, intervalos, RIR, acción correctiva e historial.
3. **Reconoce qué ítem es cada DIP** y busca su fila en la tabla de referencias (`DIPs References.xlsx`).
4. **Aplica las reglas de apertura** y, si el DIP está cerrado, **las de cierre**.
5. **Da un resultado** por DIP (POSIBLE DISCREPANCIA, SIN FUENTE u OK) con los motivos.
6. **Escribe un Excel nuevo** en `salidas/`. El de entrada no se toca.

**¿Usa inteligencia artificial?** No. Todo lo deciden reglas escritas en el código y en los archivos de configuración, y cada hallazgo dice qué dato lo produjo. Hubo un agente opcional (un modelo de lenguaje local) para sugerir la referencia de los DIPs que no se reconocen; no mejoró el resultado y se eliminó ([comparacion_modos.md](comparacion_modos.md)).

---

## 1. Lectura del Excel de entrada

Archivo: `dips_audit/cargador.py`.

El programa busca, entre las primeras 20 filas de cada hoja, una fila que tenga las columnas `Fault Barcode` y `Fault Name`. Esa es la fila de encabezados, así que el Excel puede traer títulos arriba.

**Nombres de columna.** Cada dato se reconoce por varios nombres posibles, sin importar mayúsculas. Por ejemplo, la fecha de apertura puede llamarse `Found On Date` (formato actual) o `Fault Found on Date` (formato anterior), y la de cierre `Complete Dt` o `Completed Date`. Si falta una columna obligatoria (barcode, nombre, intervalo, tipo de intervalo, estado o avión), el programa lo dice y se detiene.

**Limpieza de datos:**

| Situación | Qué hace |
| --- | --- |
| El mismo barcode en dos filas | Audita la primera y avisa cuántas omitió |
| Fechas con día y mes invertidos por Excel (9-jul guardado como 7-sep) | Las corrige solo si la fecha corregida es coherente con el due date, y lo anota |
| Espacios raros, celdas con un espacio, textos con saltos de línea | Se limpian |
| Tipo de intervalo escrito de varias formas (`CDY`, `DAYS`, `HOURS`, `HRS`, `CYCLES`, `LANDINGS`) | Se lleva a cuatro unidades: días, horas de vuelo (FH), ciclos (FC) y meses |
| Flota del avión | Sale del Task Parent Assy (`Boeing 737-8V3` → NG-800, `737-9 MAX9` → MAX). Si el DIP está en un motor, se toma la flota de otro DIP del mismo avión |
| Columnas `Rir Barcode`, `Rir Name`, `Rir Driver Interval`, `Rir Driver Type` | Dan el RIR activo del DIP cuando no se lee ICAM |

Las columnas de la auditoría manual (`DIP Open - RT Audit Completed`, `DIP Discrepancy Found`, etc.) no se usan para auditar, solo para comparar (sección 9).

---

## 2. Lectura de ICAM

Archivos: `dips_audit/extractor_icam.py` (cómo se lee) y `dips_audit/icam.py` (cómo se interpreta).

**Cómo entra a ICAM.** El programa abre un Edge aparte, con su propio perfil (`.icam_perfil/`), directo en ICAM, o usa esa ventana si ya está abierta. El usuario inicia sesión ahí. El programa usa esa sesión, igual que si alguien navegara: nunca escribe usuario ni contraseña. Si no hay sesión, avisa y revisa la ventana cada medio segundo: sigue apenas aparece ICAM con Barcode Search, y se detiene apenas la página de inicio de sesión muestra un error (`selector_error_sesion`; por defecto, los mensajes de Keycloak y de Microsoft) o se cierra la ventana. Si nadie inicia sesión, se detiene a los `espera_sesion_minutos` (3 por defecto). `python -m dips_audit abrir-icam` abre la ventana sin auditar.

**Qué lee de cada DIP.** Busca el barcode con Barcode Search y lee cinco pestañas:

| Pestaña | Datos que se usan |
| --- | --- |
| Task Execution | Descripción, acción correctiva, S/N removido e instalado |
| Fault Information | Estado, severidad, Deferral Reference, Follow-on Tasks (RIR) |
| Task Information | Parent Assembly, fecha real de cierre, Technical References, marcas de auditoría (AUDITDIP), Attachments |
| Scheduling | Intervalos del T/A, inicio, deadline, extensión y uso restante |
| History | Cambios de deadline y notas del diferimiento |

Además lee las RIR cerradas ("Show Historical Tasks") y la página de cada RIR vigente.

**Solo lectura.** Las únicas consultas son la búsqueda y la lectura de las pestañas. El HTML se muestra en una página aislada, sin red y sin los scripts de ICAM. No se abre ningún formulario ni se pulsa ningún botón.

**Detalle importante.** ICAM entrega las pestañas y sus tablas ocultas y las muestra con sus scripts. Como aquí los scripts no corren, el programa las hace visibles antes de copiar el texto. Sin ese paso se perdían las referencias técnicas, los adjuntos y los intervalos.

**Qué se lee y dónde se guarda.** Con `--icam` se leen todos los DIPs del archivo, de cualquier tipo, en cada corrida, aunque ya se hayan leído antes. Así la auditoría usa siempre los datos actuales, por ejemplo la acción correctiva y los adjuntos del cierre. Cada DIP leído se guarda en `data/icam/<barcode>.json` (en modo prueba, en `pruebas/icam/`; ver sección 9), que no se sube al repositorio porque tiene nombres del personal. Para auditar de nuevo con esos datos sin volver a leer ICAM: `--datos-icam data/icam`.

**Rapidez y errores.** Lee 3 DIPs a la vez y las pestañas en paralelo: unos 5 minutos para 380 DIPs. Cada respuesta se valida (que sea la página del DIP pedido y que la pestaña traiga contenido) y cada consulta se reintenta 3 veces. Un DIP incompleto no se guarda. Si la sesión vence a mitad de camino, lo leído queda guardado.

---

## 3. Cómo se reconoce cada DIP (variabilidad de nombres)

Archivos: `dips_audit/texto.py`, `dips_audit/asociacion.py`, `dips_audit/referencias.py` y `config/catalogo_others.yaml`.

Este es el paso más delicado. El `Fault Name` lo escribe el técnico a mano y la tabla de referencias usa sus propias descripciones. El mismo ítem aparece de muchas formas:

| Tabla de referencias | Así aparece en los DIPs |
| --- | --- |
| `CREW OXYGEN BOTTLE PRESSURE` | "BOTTLE CREW OXYGEN 850 PSI", "LINE-18 (CREW OXYGEN BOTTLE WITH LOW PRESSURE)", "DURING SERVICE VISIT 2 WAS FOUND CREW OXY WITH 900 PSI", "DURING OVERNIGHT CABIN CHECK WAS FOUND CREW OXIGEN LESS THAN 1000 PSI" |
| `FIRST AID KIT LESS THAN 130 DAYS DUE DATE` | "DIP - FAK", "DIP-FWD CABIN FIRT AID KIT", "DIP - AFT BIN FIRST AID KIT S/N CA025 DUE DATE 30-SEP-2026.", "FWD FAK with les than 130 days to due Date" |
| `CABIN PORTABLE OXYGEN BOTTLE (POB)` | "DIP-PORTABLE OXYGEN BOTTLE (POB)", "DIP- FORWARD PAX CABIN POB", "DIP-forward Pax Cabin POB 1", "FWD POB" |

(Ejemplos reales del Excel del 23-sep-2026.)

Para manejar esa variedad, el programa trabaja en capas: primero limpia el texto, después busca palabras clave, después tolera errores de escritura y, por último, usa el número de tarea técnica.

### 3.1 Limpieza del texto

Antes de comparar nada, todo texto (del DIP y del catálogo) pasa por la misma limpieza (`normalizar` en `texto.py`):

1. **Mayúsculas y sin acentos:** "Oxígeno" → "OXIGENO".
2. **Siglas con puntos:** "P.O.B" → "POB", "E.L.T." → "ELT".
3. **Signos a espacios:** guiones, barras, paréntesis y comas se vuelven espacios. "DIP-CREW/OXY" → "DIP CREW OXY".
4. **Errores y sinónimos frecuentes** vistos en el histórico. Algunos ejemplos:

| Se escribe | Se lee como |
| --- | --- |
| FIRT, FIRTS | FIRST |
| OXIGEN, OXIGENO, OXY, O2 | OXYGEN |
| EXTINTOR, EXTINGUIHSER, FIRE EXT | EXTINGUISHER |
| CERTIFICADO, CERTICATE | CERTIFICATE |
| TIRES, TYRE | TIRE |
| BREAK | BRAKE |
| LIFE VEST, LIVEVEST, LIFE JACKET | LIFEVEST |
| AID KID | AID KIT |
| ELT2, FAK1, MLG3 | ELT 2, FAK 1, MLG 3 |

La lista completa está en `_SINONIMOS` de `texto.py`. Agregar un error nuevo es agregar una línea.

### 3.2 Palabras clave del catálogo

Cada ítem Others tiene una entrada en `config/catalogo_others.yaml` (hoy 45). La entrada dice qué palabras debe tener el nombre del DIP para ser ese ítem:

```yaml
- id: OXIGENO_TRIPULACION
  nombre: Botella de oxígeno de tripulación (presión baja)
  referencias: ["CREW OXYGEN BOTTLE PRESSURE"]     # fila de DIPs References.xlsx
  requiere: [[OXYGEN], [CREW, FLIGHT COMPARTMENT, FLIGHT DECK, COCKPIT]]
  excluir: [PORTABLE, HYDRO, POB, MASK, MASKS]
```

- **`requiere`**: grupos de palabras. El nombre debe tener **al menos una frase de cada grupo**. Aquí: OXYGEN, y además CREW o COCKPIT o FLIGHT DECK… El orden y las palabras de más no importan: "DIP - LOW PRESSURE CREW OXYGEN BOTTLE" también coincide.
- **`excluir`**: si aparece alguna de estas palabras, no es este ítem. "CREW PORTABLE OXYGEN BOTTLE" no es la botella de tripulación sino la portátil (POB).
- Las frases se comparan como **palabras completas**: "ELT" no coincide dentro de "BELT".

**Si coinciden varias entradas**, gana la más específica: la que exige más grupos de palabras y frases más largas. Si empatan pero llevan a las mismas verificaciones (mismo TA, mismo Parent Assembly), da igual cuál se elija. Si empatan y son distintas, el DIP queda **SIN FUENTE** por **ambiguo**, con las candidatas en el hallazgo.

### 3.3 Errores de escritura

Si ninguna entrada coincide exacto, se vuelve a intentar tolerando errores de escritura, con dos cuidados:

- Solo en **palabras de 5 letras o más** y con al menos **85 % de parecido**: "FUNIGATION" se lee como "FUMIGATION" y "EXTINGUSHER" como "EXTINGUISHER".
- En **siglas y palabras cortas no hay tolerancia**, porque un cambio de letra es otra cosa: ELT y EMK son ítems distintos.

Si así coincide una sola entrada, se acepta y se anota como **observación**: "'FUNIGATION' se leyó como 'FUMIGATION'". Así el auditor ve qué se interpretó.

### 3.4 Por la referencia técnica o la descripción

Muchos Fault Names no dicen qué ítem es ("AFT PASSENGER CABIN LESS THAN 130 DAYS FOR DUE DATE", "DIP// Battery Due Date"), pero la descripción sí. Si el nombre no alcanza, se prueba en este orden:

1. **La referencia técnica cargada en ICAM.** Si su número de tarea (AMM, EC/RA, JIC, SRM) está en una sola entrada del catálogo, el DIP se asocia a esa entrada. Si varias lo comparten pero llevan a las mismas verificaciones (la AMM 12-15-31-610-802 está en MAIN LANDING GEAR SHOCK STRUT y en el amortiguador genérico), se elige la más específica.
2. **La descripción**, con las mismas palabras clave del catálogo ("...WAS FOUND FIRST AID KIT..." → FAK), sin tolerar errores de escritura. No se acepta si la descripción cita una tarea que no es la de esa referencia, porque el DIP sigue otra fuente: una muestra nueva de combustible por la SUBTASK 28-10-00-280-056 (10 días) no es FUEL MICROBIAL GROWTH (AMM 28-10-00-200-802, 4 días).
3. **La tarea citada en la descripción** ("IAW EC/RA 2500-0538C" → LIFEVEST DOOR LATCH DAMAGED).

Las task cards JIC de la descripción no cuentan: son la tarea donde se encontró la falla. Cada asociación así se anota como observación ("identificada por la descripción, no por el Fault Name") para que el auditor la confirme.

### 3.5 Cuando no se reconoce: SIN FUENTE

El DIP queda **SIN FUENTE**: no está en la tabla de referencias, así que no hay contra qué auditar el intervalo, el Parent Assembly ni la referencia técnica. No es una posible discrepancia. Las reglas que no dependen de la tabla (DIP vencido, cierre tarde, S/N repetido, due date contra el T/A) se siguen aplicando, y si alguna falla el DIP queda en posible discrepancia. Para ayudar, el hallazgo muestra las filas más parecidas de la tabla, de cualquier tipo. Si se parece mucho a una fila de Powerplant o Structures, se anota que quizá se abrió con el tipo equivocado.

En la auditoría del 23-sep-2026, 120 de 363 DIPs quedaron sin fuente. No es un problema de nombres: son ítems que **la tabla de referencias no tiene**, como generadores de oxígeno (unos 70), instalación de software 46 NFS, sensores de proximidad de flaps y slats, cables de spoiler, chequeos de presión de llantas o re-torque de puertas de tanque. Para cubrirlos hay que agregar la fila a la tabla y su entrada al catálogo.

### 3.6 Variabilidad en la tabla de referencias

La tabla también se escribe a mano, así que se interpreta con cuidado (`referencias.py`):

| Situación en la tabla | Qué hace el programa |
| --- | --- |
| TA simple: "3 DAYS", "60 DAYS OR 500 FH" | Lo convierte en límites comparables (uno o dos) |
| TA en meses | 1 mes = entre 30 y 31 días, más 1 día de tolerancia |
| "UNTIL DUE DATE" | El DIP debe ir en días y su due date no puede pasar el vencimiento que dice la descripción |
| TA condicional: por flota, por presión ("IF…", "DEPENDING…") | No se adivina. El catálogo define las variantes en `intervalos` (p. ej. oxígeno de tripulación: 3 días, 1 día o 1 ciclo según la presión) |
| Parent Assy con asterisco | Acepta avión o motor (se transfiere al robar el motor): la diferencia queda como observación |

Al cargar, el programa verifica que cada referencia del catálogo exista **con el texto exacto** en la columna DESCRIPTION de la tabla; si no existe, se detiene con un mensaje claro. También avisa si hay una fila Others en la tabla que ninguna entrada del catálogo cubre. Para ver todo esto: `.venv\Scripts\python -m dips_audit referencias`.

### 3.7 Variabilidad en las referencias técnicas

Las referencias técnicas tampoco tienen un formato único. El programa reconoce (`referencia_tecnica.py`):

| Dato | Formatos aceptados |
| --- | --- |
| Manual | AMM, SWPM, SRM, FIM, IPC, CMM, EC, ECRA, EC/RA, EA, JIC, TASK CARD… (AMM, SRM y task card no necesitan REV ni fecha: `referencia_tecnica.revision_opcional` en `config.yaml`) |
| Número AMM | `12-15-21-210-801`; se ignora el sufijo de efectividad (`-F00`) |
| Número EC/RA | `2901-0036C`, `EC/RA #: 2901-0036C`, `ECRA 2901-0036C R4` |
| Revisión y fecha | "REV 85, 15-MAY-2026", "REV.90 DATE 15JUN2026", "Rev No. / Date : 90 / 15 Jun 2026", "REV 92 JUN 15/26", "REV05, 11/SEP/2026", "15-MAY-2026 REV 28" |

Y descarta lo que parece referencia pero no lo es:

- **La task card donde se encontró la falla.** Muchas descripciones empiezan con "DURING TASK CARD B737-25-1-0005-U-JIC…". Esa es la tarea de inspección, no la referencia del DIP, y se ignora.
- **El MGM** (manual general de mantenimiento): no es referencia técnica. Un DIP que solo cita el MGM queda sin referencia técnica, y el hallazgo lo aclara.
- **Marcadores de ICAM:** "REFERENCE REQUIRED" (el campo está vacío) y las marcas "DIP OPEN / CLOSED - RT AUDIT COMPLETED".
- **Fechas de vencimiento del ítem** ("Battery Due: 31-JAN-2027"): una fecha solo cuenta como fecha de revisión si está junto a "REV".

Al comparar con la tabla, una tarea **del mismo capítulo-sección-tema** pero con otro número (AMM 12-15-21-**200**-801 cuando la tabla dice 12-15-21-**210**-801) se anota como observación: el auditor la acepta.

### 3.8 Cómo agregar un nombre o un ítem nuevo

1. Si es un error de escritura frecuente, agréguelo a `_SINONIMOS` en `dips_audit/texto.py`.
2. Si es un ítem nuevo, agregue la fila a `DIPs References.xlsx` y una entrada en `config/catalogo_others.yaml` con `requiere` (y `excluir` si se confunde con otro).
3. Ejecute `python -m dips_audit referencias` para ver cómo quedó y `.venv\Scripts\python -m dips_audit benchmark` para verificar que nada empeoró.

---

## 4. Auditoría de apertura

Archivos: `dips_audit/reglas.py` y `dips_audit/auditor.py`. Se aplica a todo DIP.

| Qué se revisa | Cómo |
| --- | --- |
| Intervalo | Se compara con el TA de la tabla (o la variante que corresponda a la flota o la presión). Mayor o en otra unidad → posible discrepancia; menor → observación |
| Due date | Debe ser el Start del T/A en ICAM más el intervalo (1 día de tolerancia); sin ICAM, la apertura más el intervalo. El FDR, por ejemplo, se abre con 23 días desde una semana después de la apertura: vence a los 30 días de la tabla. En ítems con vencimiento (UNTIL DUE DATE) no se cuenta por intervalo: el due date no puede pasar la fecha que dice la descripción |
| DIP vencido | Un DIP abierto con due date anterior al **momento de la auditoría** (día y hora) es crítico. Un due date sin hora vence al final del día |
| Usage Remaining | Mayor que el intervalo se anota como observación: pasa cuando el T/A empieza después de la apertura, y los auditores lo aceptan |
| Parent Assembly | Avión o motor, según la tabla |
| ATA y Deferral Reference | El Deferral Reference debe empezar con el ATA del DIP |
| Referencia técnica | Ver abajo |
| S/N | Si la tabla lo pide, debe estar en la descripción. Un S/N repetido en otro DIP abierto del mismo avión se marca |
| RIR | Si la tabla pide RIR, debe existir en Follow-on Tasks con el intervalo correcto, en el mismo Parent Assembly y con el mismo inicio que el T/A (ver abajo) |
| Duplicados | Mismo avión, mismo ítem, misma posición (FWD/AFT, LH/RH, #1/#2; también la de la descripción: el squib LEFT y el RIGHT de la misma botella no son duplicados), S/N compatibles (del nombre y la descripción) y abiertos a la vez según la fecha de cierre. Si uno de los dos ya estaba cerrado a la hora de la auditoría, el duplicado ya se corrigió: observación |

**Referencia técnica en la apertura.** Se acepta cualquiera de estas tres evidencias, que es lo que acepta el auditor:

1. la referencia cargada en ICAM (Technical References);
2. una captura adjunta (Attachments);
3. la referencia citada en la descripción.

Si no hay ninguna, es posible discrepancia. Si la cita no trae la revisión o su fecha, se anota como observación. Este criterio se calibró con la auditoría del 23-sep-2026: 153 de 154 aperturas sin discrepancia tenían referencia cargada o captura adjunta. Sin datos de ICAM no se marca, porque no se sabe si hay captura: queda como verificación manual.

**RIR (inspecciones repetitivas).** Archivo: `dips_audit/rir.py`. En ICAM, las RIR son Follow-on Tasks del DIP de clase ADHOC; las de clase REQ (por ejemplo, el servicio de taller) no son RIR. La página de Fault Information trae dos tablas: las tareas abiertas y las históricas (cerradas o canceladas). Se leen las dos, y también la página de cada RIR vigente.

| Qué se revisa | Si falla |
| --- | --- |
| La tabla pide RIR y el DIP abierto no tiene ninguna | Posible discrepancia. Si el DIP ya está cerrado y no se ve ninguna, queda para verificar en "Show Historical Tasks" |
| El intervalo de la RIR es distinto del de la tabla | Posible discrepancia |
| El T/A tiene dos límites (p. ej. CYCLES y CDY) y la RIR solo uno | Posible discrepancia |
| La RIR está en otro Parent Assembly (avión en vez de motor) | Posible discrepancia |
| La RIR empieza en otra fecha que el T/A | Posible discrepancia |

El intervalo de la RIR sale de su página en ICAM (Scheduling). Si no se pudo leer, se calcula como la diferencia entre la RIR vigente y la siguiente (594 → 1394 CYCLES = 800 FC). Sin ICAM, se usa el RIR activo de las columnas `Rir …` del Excel. La columna `RIR EN ICAM` muestra cada RIR con su intervalo.

Hoy la tabla de referencias pide RIR solo en dos ítems Others: **freno de parqueo** (1 día) y **DPI** (100 FH). En la auditoría del 23-sep-2026 no hubo DIPs de esos ítems, así que las reglas de RIR no se aplicaron. El único DIP Others con RIR en ICAM (T40S009GU3N, NLG steering cover) corresponde a un ítem que la tabla no tiene.

---

## 5. Auditoría de cierre

Se aplica además a los DIPs COMPLETE.

| Qué se revisa | Cómo |
| --- | --- |
| Fecha de cierre | En un DIP cerrado, `Usage Remaining` es lo que le quedaba al cerrarlo (ICAM): negativo es cierre tarde. Sin ese dato, `Complete Dt` (o la fecha real de cierre de ICAM) no puede pasar el due date, con 5 horas de tolerancia (`tolerancias.horas_cierre`), porque el cierre viene en UTC y el due date en hora de Panamá (UTC-5). Si la acción correctiva dice que el trabajo se hizo en otra tarea, queda para verificar la fecha en esa tarea |
| Deadline extendido | Si el due date es posterior al original (`Orig Fault Due Date`) y el DIP cerró después del original, queda en posible discrepancia para verificar el sustento de la extensión |
| Acción correctiva | Sin acción correctiva es posible discrepancia. Si no cita el manual, se anota como observación (el 23-sep-2026 los auditores lo aceptaron). No se anota si la acción remite a otra tarea ("CLOSED IN REFERENCE BARCODE T40S009H0DK"): la referencia está en esa tarea. Tampoco si no hubo trabajo ("OPEN BY MISTAKE", "PREVIOUSLY ACCOMPLISHED", "NO FURTHER ACTION REQUIRED"). En ambos casos queda una nota para verificar |
| S/N removido | Si es distinto del S/N de la descripción, observación (suelen ser nomenclaturas distintas del mismo kit) |
| Attachments | Sin adjuntos se anota como observación |
| Cambios de deadline | Si el historial muestra cambios, se listan para verificar |

---

## 6. Resultado de cada DIP

El programa da **tres resultados**:

| Resultado | Cuándo |
| --- | --- |
| POSIBLE DISCREPANCIA | Falló al menos una regla o falta un dato |
| SIN FUENTE | El DIP no está en la tabla de referencias y no falló ninguna regla que no dependa de la tabla. Se verifica contra la fuente que cita el DIP |
| OK | No falló ninguna regla (puede tener observaciones) |

No clasifica la discrepancia en crítica o no crítica ni en tipos, porque esos criterios todavía no coinciden con el proceso de los auditores. El auditor decide si la posible discrepancia lo es y de qué nivel.

Cada hallazgo se muestra como `[POSIBLE DISCREPANCIA]`, `[SIN FUENTE]` u `[OBSERVACIÓN]`. Una observación se anota, pero no cambia el resultado. Qué reglas se revisan y cuáles son solo observación se configura en `config/discrepancias.yaml`. Ese archivo conserva además una gravedad interna por regla (crítica, no crítica, revisar); hoy no se muestra, pero permitirá volver a separar niveles cuando se definan. Un hallazgo de cierre aparece con `[CIERRE]` y tiene su propio resultado en la columna `ESTADO CIERRE`.

---

## 7. Excel de salida

Archivo: `dips_audit/reporte.py`. Se crea en `salidas/<archivo>_AUDITORIA_<fecha>.xlsx`.

| Hoja | Contenido |
| --- | --- |
| Dashboard | Gráficos: resultado, DIPs por tipo, tipos de discrepancia, referencias con más discrepancias |
| Resumen | Archivo, fecha y conteos |
| Auditoría | Un DIP por fila: resultado, hallazgos, comentario sugerido, referencia, TA, referencia técnica, RIR, adjuntos, apertura/cierre y las columnas originales |
| Hallazgos | Un hallazgo por fila: posible discrepancia u observación, y si es de apertura o de cierre |

---

## 8. Configuración

| Archivo | Qué se ajusta |
| --- | --- |
| `config/discrepancias.yaml` | Reglas activas y cuáles son solo observación |
| `config/config.yaml` | Tolerancias e ICAM (lectura en paralelo, reintentos) |
| `config/catalogo_others.yaml` | Palabras clave de cada ítem Others y variantes de intervalo |
| `DIPs References.xlsx` | TA, Parent Assembly, referencia técnica y RIR de cada ítem |

---

## 9. Comparación con la auditoría manual

Archivo: `dips_audit/comparacion.py`. Se ejecuta con `comparar.bat`.

El Excel `DIPs Audit (...)` trae, por DIP, cuándo y quién hizo la auditoría de apertura y la de cierre, y si el auditor encontró discrepancia (`DIP Discrepancy Found = Y`). Esa marca es una sola por DIP, no una por auditoría.

El programa audita cada DIP **dos veces**: a la fecha y hora de la auditoría de apertura, contando solo los hallazgos de apertura, y a la de cierre, contando solo los de cierre. El resultado del programa para el DIP es el peor de esas auditorías. Luego lo compara con la marca del auditor:

| Auditor | Programa | Se lee como |
| --- | --- | --- |
| Sin discrepancia | OK | Sí: ambos OK |
| Con discrepancia | Posible discrepancia | Sí: ambos encuentran discrepancia |
| Sin discrepancia | Posible discrepancia | No: el programa marca y el auditor no |
| Con discrepancia | OK | No: el programa no la detecta |

**Excel de la comparación.** La hoja **Resumen** no usa cruces tipo matriz: cada tabla responde una sola pregunta, con una fila por respuesta (qué se comparó; si el resultado es el mismo; qué dijo el programa de los DIPs sin discrepancia; qué dijo de los DIPs con discrepancia; resultado de la apertura; resultado del cierre; motivos de las marcas, por separado en apertura y cierre; y la lista de discrepancias del auditor). **Detalle por DIP** tiene una fila por barcode y **Hallazgos del programa**, una fila por hallazgo.

**Resultado con la auditoría del 23-sep-2026** (363 DIPs Others, 245 aperturas y 221 cierres, todos leídos en ICAM). Son datos de prueba y están en `pruebas/`.

DIPs que el auditor dio **sin discrepancia** (347):

| Resultado del programa | DIPs |
| --- | ---: |
| OK: coincide | 227 (65 %) |
| Posible discrepancia: el auditor no la marcó (86 son DIPs que no están en la tabla de referencias) | 120 (35 %) |

DIPs en que el auditor **encontró discrepancia** (16):

| Resultado del programa | DIPs |
| --- | ---: |
| Posible discrepancia: coincide | 8 |
| OK: no la detecta | 8 |

En total, el programa llega al mismo resultado que el auditor en 235 de 363 DIPs (65 %).

Antes de calibrar las reglas de referencia técnica con estos datos, el programa marcaba discrepancia en 201 de los 347 DIPs sin discrepancia; ahora marca 120, de los cuales 86 son DIPs que la tabla de referencias no tiene.

**Limitación:** ICAM muestra el estado actual del DIP, no el que vio el auditor en su momento. Por ejemplo, un attachment agregado después cuenta como si hubiera estado.

**Modo prueba.** Si el Excel está dentro de `pruebas/` (o se usa `--prueba`), el programa guarda los datos de ICAM en `pruebas/icam/` y los resultados en `pruebas/salidas/`, con el prefijo `PRUEBA_` y un aviso en el Excel. Así las corridas de prueba no se mezclan con las auditorías reales en `data/icam/` y `salidas/`. La carpeta se configura con `carpeta_pruebas` en `config/config.yaml`.

---

## 10. Benchmark

Archivo: `dips_audit/benchmark.py`. Se ejecuta con `.venv\Scripts\python -m dips_audit benchmark` (1 segundo).

Audita 50 DIPs ya auditados (`benchmark/dips_auditados.xlsx`, copia sin nombres del histórico) y 46 nombres difíciles de asociar (`benchmark/casos_asociacion.yaml`). Compara los indicadores con la **línea base** (`benchmark/linea_base.json`). Si alguno empeora, lo avisa y termina con error. Si el cambio era intencional, se copia el resultado nuevo sobre la línea base. Los resultados quedan en `benchmark/resultados/`.

Conviene ejecutarlo después de cualquier cambio en reglas, catálogo o configuración.

---

## 11. Mapa del código

| Archivo | Qué hace |
| --- | --- |
| `__main__.py` | Comandos de consola: `auditar`, `comparar`, `abrir-icam`, `extraer-icam`, `benchmark`, `referencias` |
| `cargador.py` | Lee el Excel de entrada y los datos de ICAM, y los deja en un formato común |
| `extractor_icam.py` | Lee las páginas de ICAM (solo lectura) y las guarda en `data/icam/` |
| `icam.py` | Interpreta el texto de cada pestaña de ICAM |
| `texto.py` | Limpieza de texto, sinónimos, S/N, fechas y presiones |
| `referencias.py` | Lee la tabla de referencias, interpreta el TA y carga el catálogo |
| `asociacion.py` | Reconoce qué ítem es cada DIP |
| `referencia_tecnica.py` | Encuentra y compara referencias técnicas |
| `reglas.py` | Reglas de apertura y de cierre, duplicados y S/N repetidos |
| `rir.py` | RIR: cómo se leen y qué se revisa |
| `discrepancias.py` | Carga `discrepancias.yaml`: reglas activas y gravedad |
| `auditor.py` | Une todo: carga, asociación, reglas y resultado |
| `reporte.py` | Escribe el Excel de salida |
| `comparacion.py` | Compara con la auditoría manual |
| `benchmark.py`, `evaluacion.py`, `anonimizar.py` | Benchmark y su muestra anónima |

Pruebas: `.venv\Scripts\python -m pytest` (carpeta `tests/`).

---

## 12. Pendientes

- **Completar la tabla de referencias** con los ítems que faltan (generadores de oxígeno, NFS, sensores de proximidad, etc.). Es lo que más reduce los DIPs SIN FUENTE.
- **Amortiguadores MAX:** la tabla dice 10 FC para MAX, pero las descripciones citan "not to exceed 20 landings" (GMM 3.6) y los auditores aceptaron 15 FC en los 6 DIPs así del 23 y el 28-sep. Confirmar cuál es el TA correcto y, si corresponde, corregir la tabla.
- **Definir con los auditores** los niveles (crítica / no crítica) y los tipos de discrepancia del proceso. Hasta entonces el programa solo da posible discrepancia.
- **Criterio de cierre tarde:** T40S009H94W cerró con Usage Remaining −1 (31 h tarde) y el auditor lo dio OK. T40S00992SM (5 días) se hizo en otra tarea y queda para verificar.
- **Motivo de las discrepancias manuales:** el Excel solo marca "Y". Con el comentario del auditor se podría saber qué detectó en las 9 discrepancias que el programa da OK.
