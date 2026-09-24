# Auditoría preliminar de DIPs

El programa lee el Excel de entrada y, con `--icam`, los datos de cada DIP en ICAM, aplica las reglas y entrega un Excel con el resultado de cada DIP. El auditor confirma.

## Proceso

```mermaid
flowchart LR
    A[Excel de entrada] --> P{{Programa}}
    I[(ICAM<br/>solo lectura)] -- por barcode --> P
    T[DIPs References.xlsx] --> P
    P --> S[Excel de salida]
    S --> D[DISCREPANCIA]
    S --> R[POSIBLE DISCREPANCIA]
    S --> O[OK]
    D --> U([Auditor confirma])
    R --> U
    O --> U
    style D fill:#F4B6B6,color:#000
    style R fill:#FCE3B0,color:#000
    style O fill:#C9E7C9,color:#000
```

## Uso

```mermaid
flowchart TD
    A["1. Ejecutar auditar.bat con el Excel de entrada<br/>(con --icam para leer todos los DIPs en ICAM)"] --> B
    B["2. Con --icam, si se pide, iniciar sesión en ICAM<br/>en la ventana de Edge (dejarla abierta)"] --> C
    C["3. Abrir el Excel de salida en la carpeta salidas<br/>Hoja Dashboard: resumen y gráficos"] --> D
    D["4. Hoja Auditoría: filtrar RESULTADO<br/>y revisar DISCREPANCIA y POSIBLE DISCREPANCIA"]
```

## Lectura de ICAM

```mermaid
sequenceDiagram
    participant P as Programa
    participant E as Edge de ICAM (sesión iniciada)
    participant I as ICAM
    P->>E: Abre la ventana (si está cerrada) y se conecta
    E->>I: Abre ICAM (no la página de inicio de sesión)
    alt Sin sesión
        P-->>P: Avisa; sigue apenas se inicia sesión y se detiene apenas hay un error
    end
    loop Cada barcode (3 a la vez)
        E->>I: Barcode Search (ScanBarcode)
        par 5 pestañas en paralelo
            E->>I: Task Execution
            E->>I: Fault Information
            E->>I: Task Information
            E->>I: Scheduling
            E->>I: History
        end
        E->>I: Show Historical Tasks (RIR cerrados)
        E->>I: Página de cada RIR vigente (Scheduling, Task Information)
        P->>P: Valida y guarda data/icam/barcode.json
    end
```

| Control | Cómo |
| --- | --- |
| Solo lectura | Las únicas consultas son la búsqueda y la lectura de las pestañas. No se abre ningún formulario de edición ni corre código de ICAM |
| Sin errores | Cada respuesta se valida (DIP, barcode y contenido). 3 reintentos por consulta. Un DIP incompleto no se guarda. Si la sesión vence, se detiene y lo leído queda guardado |
| Rapidez | Sin dibujar páginas ni descargar imágenes. 3 DIPs a la vez, pestañas en paralelo. Un DIP ya leído no se vuelve a leer |

## Datos que se usan

```mermaid
flowchart LR
    subgraph X[Excel de entrada]
        X1[Fault Name] --- X2[DIP Interval / Interval Type] --- X3[Fechas y Usage Remaining] --- X4[Parent Assy / ATA / Deferral Reference]
    end
    subgraph I[ICAM]
        I1[Description] --- I2[Technical References] --- I3[Deferral Notes] --- I4[Attachments] --- I5[Scheduling] --- I6[S/N removido e instalado]
    end
    subgraph T[DIPs References.xlsx]
        T1[TA por flota o condición] --- T2[Parent Assy] --- T3[AMM / ECRA]
    end
```

## Reglas

```mermaid
flowchart TD
    N[Fault Name] --> REF{¿Referencia en la tabla?}
    REF -- No --> PD1[POSIBLE DISCREPANCIA<br/>sin referencia]
    REF -- Sí --> V[Intervalo y tipo · Parent Assy · Due date<br/>Vencidos · Duplicados · Deferral Reference]
    V --> RT{¿Referencia técnica<br/>manual + REV + fecha?}
    RT -- Falta --> D1[DISCREPANCIA]
    RT -- De otra referencia --> D1
    RT -- Tarea que la tabla no tiene --> PD2[POSIBLE DISCREPANCIA]
    RT -- Completa y correcta --> F{¿Falló otra regla?}
    F -- Sí --> D1
    F -- No --> OK[OK]
    style D1 fill:#F4B6B6,color:#000
    style PD1 fill:#FCE3B0,color:#000
    style PD2 fill:#FCE3B0,color:#000
    style OK fill:#C9E7C9,color:#000
```

| Regla | Si falla |
| --- | --- |
| Intervalo mayor que el TA | DISCREPANCIA CRÍTICA |
| Tipo de intervalo distinto (días, FH, FC) | DISCREPANCIA CRÍTICA |
| Parent Assy distinto (AIRCRAFT / ENGINE) | DISCREPANCIA CRÍTICA |
| Due date después del vencimiento del ítem | DISCREPANCIA CRÍTICA |
| DIP activo vencido o cerrado fuera de plazo | DISCREPANCIA CRÍTICA |
| Referencia técnica sin manual, REV o fecha | DISCREPANCIA NO CRÍTICA |
| Referencia técnica de otra referencia | DISCREPANCIA NO CRÍTICA |
| Intervalo 0, Usage Remaining mayor que el intervalo | DISCREPANCIA NO CRÍTICA |
| DIP duplicado, S/N repetido, Deferral Reference distinto del ATA | DISCREPANCIA NO CRÍTICA |
| RIR faltante o con intervalo distinto del de la tabla | DISCREPANCIA NO CRÍTICA |
| RIR sin un límite del T/A o en otro Parent Assembly | DISCREPANCIA NO CRÍTICA |
| RIR con Start distinto del T/A | POSIBLE DISCREPANCIA |
| Sin referencia en la tabla, sin intervalo, due date dudoso | POSIBLE DISCREPANCIA |

Qué tipos de discrepancia y reglas se revisan, y la severidad de cada regla, se configuran en `config/discrepancias.yaml`.

## RIR en ICAM

```mermaid
flowchart LR
    D[DIP] --> F[Follow-on Tasks]
    F --> A["RIR ACTV<br/>594 CYCLES"]
    F --> B["RIR FORECAST<br/>1394 CYCLES"]
    F -.-> H["Show Historical Tasks<br/>RIR cerrados"]
    A --> I["Intervalo = 1394 − 594 = 800 FC"]
    B --> I
    A --> P["Página del RIR<br/>Scheduling: intervalo, Start, límites<br/>Task Information: Parent Assembly"]
    I --> C{"¿Igual al RIR de la tabla<br/>y a los límites y Start del T/A?"}
    P --> C
```

| Se revisa | Criterio del auditor |
| --- | --- |
| Intervalo | "RIRs (2 DAY INTERVAL)", "T/A y RIRs correctos (100 FH y 50 FH)" |
| Límites | "RIRs aperturados solo con limitantes de ciclos. Agregar limitante de 30 Meses" |
| Start | "RIRs de 200FH con START values diferentes al T/A ocasiona que corran mal" |
| Parent Assembly | "RIRS aperturados correctamente al motor ESN …" |

Las Follow-on Tasks REQ (servicio de taller) no son RIR.

## Referencia técnica en los DIPs Others leídos de ICAM

Se buscaron el manual, la REV y la fecha en 80 DIPs Others leídos de ICAM.

```mermaid
pie showData
    title Referencia técnica (80 DIPs Others)
    "Completa: manual + REV + fecha" : 22
    "Sin REV o sin fecha" : 32
    "Sin referencia del manual" : 26
```

## Pendiente

```mermaid
flowchart LR
    H[Hoy:<br/>Excel de salida] --> W[Excel web<br/>SharePoint / OneDrive]
    H --> M[Marca AUDITDIP en ICAM<br/>requiere autorización de escritura]
    H --> PA[Registro en Power Apps]
    style W stroke-dasharray: 5 5
    style M stroke-dasharray: 5 5
    style PA stroke-dasharray: 5 5
```
