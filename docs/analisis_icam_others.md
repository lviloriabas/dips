# Análisis de DIPs "Others" en ICAM: conclusiones

Análisis del 23-sep-2026, hecho en modo **solo lectura**. En ICAM solo se usó la búsqueda
por barcode y la lectura de las pestañas; no se modificó nada.

## Muestra

- **377 DIPs Others** del histórico de auditorías, con apertura entre el 9-jul y el 10-ago-2026.
  A la fecha, 263 están cerrados (CERTIFY) y 114 siguen activos (DEFER).
- La extracción se detuvo a pedido del usuario; no se revisaron los DIPs posteriores al 10-ago.
- De cada DIP se leyeron las pestañas Task Execution, Fault Information, Task Information,
  Scheduling e History. Los resultados se cruzaron con la columna `STATUS - Apertura` del
  histórico: 343 OK, 26 con discrepancia no crítica y 8 con discrepancia crítica.
- Los datos crudos no se suben al repositorio porque contienen nombres del personal.

## Conclusiones

### 1. El export muestra una foto del momento; ICAM muestra el estado actual

En **31 de 377** DIPs, el intervalo del export no coincide con el que tiene hoy ICAM en Scheduling.
Hay tres causas:

- **Correcciones hechas después de la auditoría.** En 5 de los 8 críticos, History registra
  un cambio de deadline posterior a la fecha de auditoría. Ejemplos: T40S0099RB9 (26-sep → 20-sep),
  T40S009ADVW (93 → 90 días) y T40S009BLMT (2902 → 2930 FH). En los DIPs OK esto ocurre solo en 3 de 343.
  **Conclusión:** en ICAM se puede verificar si la discrepancia reportada se corrigió.
- **Deadline provisional de 1 día.** Al diferir, ICAM crea un deadline CDY por defecto
  para el día siguiente. El planificador lo borra y carga el definitivo, en general
  en el mismo minuto: pasó en **110 de 377 DIPs (29 %)**, con una mediana de 0 minutos y un máximo de 7 horas.
  Si el export se saca antes de ese reemplazo, trae "1 DAY" aunque el DIP esté bien abierto.
  Ejemplos: T40S009BH9A (export 1 DAY, ICAM 88 días), T40S009AW94 (1 DAY, ICAM 3000 FH)
  y T40S009CYSR (1 DAY, ICAM 364 días).
- **Intervalo vacío en el export (16 DIPs).** Scheduling sí tiene el deadline.
  Los 16 quedaron OK, así que el auditor lo leyó en ICAM.

**Recomendación:** ante un intervalo de 1 día o vacío, `dips_audit` debe marcarlo como
"verificar en Scheduling" y no como discrepancia. Además, conviene sacar el export
algunas horas después del diferimiento.

### 2. Límites dobles

12 DIPs tienen dos deadlines (por ejemplo CDY + CYCLES en llantas, o HOURS + CDY). El export trae
un solo intervalo, así que el segundo límite no se puede auditar desde el Excel.
En los bleed control cards, la tabla pide además RIR cada 70 FH, que tampoco aparece en el export.

### 3. Cierre fuera del deadline en UTC

**6 DIPs** se completaron después del deadline en UTC, con atrasos de entre 4 minutos y 15 horas.
Ejemplo: T40S0099V53 vencía el 16-jul 23:59 UTC y se cerró el 17-jul 04:12 UTC, que en
Panamá (UTC-5) todavía es 16-jul 23:12.

- 4 tienen auditoría de cierre en el Excel y las 4 salieron OK. Los otros 2 no tienen cierre registrado.
- T40S009B2NE (certificado de fumigación) se cerró el 25-jul a las 10:10 hora local:
  está vencido también en hora local y no tiene auditoría de cierre.
- **Hay que definir el criterio**: ¿se cuenta en UTC, como en ICAM, o en hora local?
  Hoy los auditores lo aceptan.

### 4. Marcas de auditoría (AUDITDIP)

- 31 DIPs tienen la marca `DIP CLOSED - RT AUDIT COMPLETED`, todos cerrados entre el 21-ago y el 20-sep.
  Ninguno de los 377 tiene `DIP OPEN - RT AUDIT COMPLETED`. Esa marca sí aparece en DIPs
  más recientes (p. ej. T40S009EX3N, abierto el 27-ago).
- Los 154 cierres calificados OK en el Excel **no tienen marca**. En cambio, 26 DIPs con marca
  de cierre no tienen el cierre registrado en el Excel.
- **Conclusión:** la marca en ICAM es una práctica reciente (desde fines de agosto) y el
  Excel histórico no está al día con los cierres. Para saber qué falta auditar, la fuente
  confiable es la marca en ICAM.

### 5. Adjuntos

- Solo 112 de 377 DIPs (30 %) tienen algún adjunto.
- La columna "¿Tiene captura de ref. técnica?" coincide bien cuando vale 1: 29 de 31 tienen adjunto.
  De los 288 que tienen 0, 77 tienen adjunto hoy (se agregó después o es otra evidencia).
- En Others, la falta de adjuntos casi no se reporta como discrepancia: 243 DIPs OK no tienen
  adjunto. En Powerplant y Structures sí se exige.
  **Hay que decidir** si en Others es obligatorio o no.

### 6. Otros controles que dieron limpio

- **Fault Severity**: todos son DIP. **Deferral Class**: todos son DIP-MEL.
- **Parent Assembly**: 376 abiertos a AIRCRAFT y 1 a ENGINE. Coincide con la tabla de Others.
- **DIPs activos vencidos**: ninguno de los 114 activos está vencido hoy.
- **Deferral Reference vs ATA**: no se puede comparar contra el *Config Slot*, porque este
  refleja la tarea donde se encontró la falla (p. ej. 05-20 checks) y no el sistema. Hay que
  compararla contra el ATA del export, como ya hace `dips_audit`.

## Qué detectaron los auditores en Others (histórico completo, 80 discrepancias)

Hay comentario en 42 de las 80 discrepancias. Categorías:

| Tipo | Casos | ¿Se ve en el export? | ¿Se ve en ICAM? |
|---|---|---|---|
| Intervalo/T-A incorrecto | 28 | Parcial (foto del momento) | Sí: Scheduling + History |
| Faltan adjuntos o ref. técnica | 10 | No | Sí: Task Information |
| S/N faltante o incorrecto | 9 | Solo en la descripción | Sí: Part Requirements (S/N removido) |
| Due date o start incorrecto | 5 | Parcial | Sí: Scheduling (Start/Deadline) |
| RIRs faltantes | 5 | No | Parcial (tareas relacionadas) |
| Duplicado o creado por error | 4 | Sí | Sí |
| DIP que debió cerrarse | 1 | No | Sí (History del componente) |

## Recomendaciones para `dips_audit`

1. **Tratar el intervalo "1 DAY" o vacío como "verificar en ICAM"** y no como discrepancia
   (deadline provisional).
2. **Leer Scheduling e History de ICAM** (solo lectura, con la URL `TaskDetails.jsp?...&aTab=`)
   para: intervalo actual, límites dobles, extensiones y correcciones posteriores.
3. **Leer adjuntos y referencias técnicas** de Task Information para cerrar la verificación
   manual de "captura de referencia técnica".
4. **Usar la marca AUDITDIP** para saber qué DIPs ya tienen auditoría de apertura o cierre.
5. **Definir el criterio UTC o local** para "completado fuera de plazo".
6. **Cruzar el S/N de la descripción** con el S/N removido en Part Requirements.
