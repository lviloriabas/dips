# Flujo de auditoría de DIPs en ICAM (IFS Maintenix)

Levantado el 23-sep-2026 en modo **solo lectura**: se navegó por ICAM sin editar nada.
DIPs revisados:

| Barcode | DIP | Estado en ICAM | Auditoría en el histórico |
|---|---|---|---|
| T40S009DV6S | OXYGEN CREW BOTTLE (HP-9925CMP) | CERTIFY / COMPLETE | Apertura: DISCREPANCIA CRÍTICA |
| T40S009ES3L | Crew oxygen bottle 890 psi (HP-9912CMP) | COMPLETE | Apertura: OK |
| T40S009EX3N | EMERGENCY MEDICAL KIT S/N 0168 (HP-1713CMP) | DEFER / ACTV (abierto) | PENDIENTE en el histórico; ya tiene marca de auditoría en ICAM |

## 1. Entrada

- **Barcode del DIP**: columna `Fault Barcode` del Excel de entrada, con formato `T40S…`.
- **Tabla de referencias**: `DIPs References.xlsx` (TA, parent assy, referencia técnica y RIR).

## 2. Búsqueda

1. En cualquier pantalla de ICAM, usar el campo **Barcode Search** (arriba a la derecha).
2. Escribir el barcode y presionar Enter. Se abre **Fault Details – <nombre del DIP> [barcode]**.

La URL de detalle es `…/maintenix/web/task/TaskDetails.jsp?aTask=<id>&aTab=<pestaña>`.
El parámetro `aTab` abre una pestaña directamente: `idTabFaultInformation`,
`idTabTaskInformation`, `idTabScheduling` o `idTabHistory`. Sin `aTab` se abre Task Execution.

## 3. Qué revisar en cada pestaña

### Encabezado (Details), visible en todas las pestañas

| Campo | Uso en la auditoría |
|---|---|
| Aircraft | Flota y matrícula (p. ej. *Boeing 737-9 MAX9 - HP-9925CMP*). La flota define el TA cuando la referencia es condicional |
| Inventory | Config slot/ATA (p. ej. *35 - OXYGEN*) |
| Due | Vencimiento vigente del DIP |
| Work Package | Paquete de trabajo donde se cerró. Vacío si el DIP sigue abierto |

### Task Execution (pestaña por defecto)

- **Description**: texto de apertura. Aquí están la condición medida (psi, fecha de vencimiento del
  kit, S/N, P/N) y el plazo declarado ("within 3 days", "due less than 130 days").
- **Labor**: etapa (ACTV, COMPLETE), técnico, certificador e inspección independiente (RII/RIR).
- **Corrective Action** (cierre): qué se hizo y con qué referencia AMM y revisión.
- **Part Requirements**: P/N y S/N removido e instalado. Sirve para cruzar el S/N de la descripción.

### Fault Information

- **Fault Status**: OPEN, DEFER (abierto como DIP) o CERTIFY (cerrado).
- **Fault Severity**: debe ser *DIP (Defer Item Project)*.
- **Found on Date** y **Found During Task** (la tarea o JIC donde se encontró).
- **Deferral Class** (*DIP-MEL*) y **Deferral Reference** (*35-DIP*, *25-DIP*). El prefijo debe
  coincidir con el ATA.
- **Fault History**: quién creó la falla, quién la difirió ("Corrective action was deferred"),
  cuándo cambió la severidad a DIP y quién la certificó.

### Task Information

- **Parent Assembly**: AIRCRAFT (matrícula) o ENGINE. Se compara con `PARENT ASSY` de la tabla.
- **Status**: ACTV o COMPLETE.
- **Technical References**:
  - La referencia técnica del DIP (Document Reference, o "REFERENCE REQUIRED" con el paso de la JIC).
  - **Marcas de auditoría** (tipo `AUDITDIP`): `DIP OPEN - RT AUDIT COMPLETED` indica que la
    apertura fue auditada y `DIP CLOSED - RT AUDIT COMPLETED` que el cierre fue auditado.
- **Attachments**: la captura de la referencia técnica o la foto de evidencia (.jpg/.png, tipo PIC).
  Corresponde a la columna "¿Tiene captura de Ref. Técnica…?" del histórico.

### Scheduling

- Tabla **Due**: Driver/Parameter (*CDY* días calendario, *FH*, *FC*), Start, **Interval**,
  Deadline, Extension, Extended Deadline, **Usage Remaining** y Last Updated.
- Se compara Interval y tipo con el TA de la tabla. También se verifica que
  Deadline = Start + Interval y que no haya extensiones sin justificar.

### History

- **Historial de la tarea**: creación, diferimiento (con *Deferral Notes*), alta y baja de
  deadlines, **cambios de deadline** ("deadline has been modified from X to Y"), asignaciones y cierre.
- **Usage When Found** y **Usage At Completion**: ciclos y horas al abrir y al cerrar, y TSN de las
  piezas removidas e instaladas.

## 4. Flujo propuesto

```
Barcode (Excel de entrada)
  └─ Barcode Search → Fault Details
       ├─ AUDITORÍA DE APERTURA (DIP en DEFER/ACTV)
       │   1. Fault Information: severidad DIP, Deferral Class/Reference vs ATA, quién difirió
       │   2. Task Execution › Description: condición, S/N, plazo declarado
       │   3. Asociar con fila de DIPs References (descripción + flota + condición)
       │   4. Scheduling: tipo e intervalo vs TA; Deadline = Start + Interval
       │   5. Task Information: Parent Assy vs tabla; referencia técnica y adjunto presentes
       │   6. Veredicto: OK / DISCREPANCIA NO CRÍTICA / DISCREPANCIA CRÍTICA
       │   7. Registrar en el histórico (+ marca "DIP OPEN - RT AUDIT COMPLETED") ← acción de escritura
       └─ AUDITORÍA DE CIERRE (DIP en CERTIFY/COMPLETE)
           1. Task Execution: Corrective Action con referencia AMM + revisión
           2. Part Requirements: S/N removido = S/N de la descripción
           3. Labor: técnico/certificador; RII si la tabla exige RIR
           4. Actual End Date ≤ Due (usando el deadline ORIGINAL, no uno extendido sin sustento)
           5. History: revisar cambios de deadline posteriores a la apertura
           6. Registrar (+ marca "DIP CLOSED - RT AUDIT COMPLETED") ← acción de escritura
```

Los pasos 7 y 6 que agregan la marca `AUDITDIP` son los únicos que modifican ICAM.
**No se ejecutaron.** El procedimiento exacto para agregarla (botón "+" de Technical References)
se dedujo de la pantalla y falta confirmarlo con un auditor.

## 5. Hallazgos del caso T40S009DV6S (discrepancia crítica)

- Tabla de referencias: *CREW OXYGEN BOTTLE PRESSURE* da **3 días** si la presión está más de
  200 psi sobre la mínima de despacho, con referencia AMM 12-15-21-210-801.
- El Excel de entrada del día de la auditoría registraba intervalo **2 CDY** y vencimiento 20-ago. En History,
  el deadline se modificó el 18-ago de **20-AGO a 21-AGO** y hoy Scheduling muestra 3 CDY.
  Por eso **ICAM muestra el estado actual, no el que vio el auditor**: hay que usar History para
  reconstruir el estado a la fecha de auditoría.
- Solo tiene como referencia técnica la 12-15-21-600-804 (reemplazo), la misma de la acción
  correctiva. En el histórico, "captura de ref. técnica" = 0.
- No tiene marcas `AUDITDIP`, aunque figura como auditado en el histórico. Posiblemente la marca
  empezó a usarse después o no se aplicó; falta confirmarlo.
- El Deferral Reference en ICAM es *35-DIP*, pero en el Excel de entrada venía vacío.

## 6. Datos de ICAM que no trae el Excel de entrada (pendientes para `dips_audit`)

| Dato | Dónde está | Hoy en el programa |
|---|---|---|
| Adjuntos y captura de la referencia técnica | Task Information › Attachments | Verificación manual |
| Referencia técnica cargada | Task Information › Technical References | No se revisa |
| Marca de auditoría hecha | Technical References (tipo AUDITDIP) | No se revisa |
| Cambios y extensiones de deadline | History / Scheduling › Extension | No se ve |
| S/N removido e instalado | Task Execution › Part Requirements | Solo el S/N de la descripción |
| RII / inspección independiente | Task Execution › Labor | Verificación manual |
| Fecha real de cierre | Details › Actual End Date | Solo si el Excel de entrada la trae |

## 7. Controles que NO se deben tocar al auditar (solo lectura)

Estos controles modifican datos: *Mark Fault As Error*, *Create Flight Disruption*,
*Create Repetitive Task*, *Certify*, *Record Inspection*, *Edit Work Capture*, *Extend Deadline*,
*Edit Intervals*, *Add Deadline*, *Remove Deadlines*, *Edit Deadline Start Values*, los botones "+"
de secciones, y *Acknowledge/Disposition/Archive* del To Do List.
Para leer basta con Barcode Search, las pestañas y *Preview Task Card*.
