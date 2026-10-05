# Guía de reglas y referencias de DIPS

Guía de consulta para agregar chequeos al auditor de DIPs. La presentación y el PDF
están en esta misma carpeta: `Guia_DIPS_reglas_referencias.pptx` y
`Guia_DIPS_reglas_referencias.pdf`.

## Qué se configura

Una **regla o chequeo** comprueba una condición. Un **tipo de discrepancia** agrupa
reglas. La **referencia** aporta el valor autorizado con el que se compara el DIP:
TA, RIR, Parent Assembly o fuente técnica.

| Necesidad | Cómo hacerlo |
| --- | --- |
| Agregar un chequeo nuevo | Función Python, conexión al flujo, código en YAML y pruebas |
| Preparar ejemplos sin escribirlos desde cero | `docs/generar_regla.bat` |
| Crear un tipo con reglas existentes | Mover los códigos al nuevo tipo en `config/discrepancias.yaml`, sin duplicarlos |
| Activar, desactivar o clasificar una regla | `config/discrepancias.yaml` |
| Incorporar un componente o referencia | Fila en la tabla y, cuando haga falta, entrada en el catálogo |
| Cambiar una tolerancia | `config/config.yaml` |

**Un código nuevo en YAML no crea su detección.** Todos los códigos configurados
deben existir en el programa, y todos los implementados deben estar configurados.
Un tipo necesita al menos una regla.

El generador prepara ejemplos. No modifica la detección ni instala reglas.

## Antes de agregar una regla

Escriba el criterio con el dato que necesita, la condición que produce el hallazgo,
la etapa (apertura o cierre), los estados aplicables y las excepciones. Defina qué
hacer si el dato no está disponible y qué mensaje debe ver el auditor.

Ejemplo didáctico: «En un DIP activo, informar si la descripción está vacía».
Sirve para enseñar el procedimiento. Confirme el criterio con quien define la
auditoría antes de integrarlo.

## Alternativa A: generador de ejemplos

1. En `docs`, haga doble clic en **`generar_regla.bat`**. Usa el Python de `.venv`.
   Si falta, ejecute `setup.bat` desde la carpeta DIPS.
2. Responda las preguntas. Para el ejemplo anterior:

   | Dato | Ejemplo |
   | --- | --- |
   | Código | `descripcion_obligatoria` |
   | Tipo de discrepancia | `Datos requeridos` |
   | Campo | Descripción del DIP |
   | Condición | `vacio` |
   | Etapa | `APERTURA` |
   | Severidad | `OBSERVACION` |
   | Mensaje | `La descripción del DIP está vacía.` |

3. Abra `docs/ejemplos/generados/descripcion_obligatoria/`. Contiene:
   `regla.py.txt`, `discrepancias.yaml.txt`, `prueba.py.txt` y `LEEME.md`.
4. Lea `LEEME.md`. Revise e integre los ejemplos como indica la alternativa manual.
   Si otra persona mantiene el programa, entréguele la carpeta junto con el
   criterio y sus excepciones. Generar la carpeta todavía no activa el chequeo.

El generador ofrece **campo vacío** o **texto que falta** en Descripción, Fault Name,
Deferral Reference, Parent Assembly y Fault Severity. Busca texto sin distinguir
mayúsculas. Si la clave del dato no existe, deja una verificación manual. Si existe
pero está vacía, la trata como campo vacío.

Fechas, TA, RIR, referencias asociadas y comparaciones entre varios DIPs necesitan
una implementación específica. La extensión `.txt` separa los ejemplos del código
ejecutable. Hay un ejemplo preparado en `docs/ejemplos/descripcion_obligatoria/`.
No sobrescribe carpetas existentes; use otro destino con `--salida` para otra versión.

Desde la consola, situada en la raíz de DIPS:

```bat
.venv\Scripts\python docs\generar_regla.py --codigo descripcion_obligatoria --tipo "Datos requeridos" --campo descripcion --condicion vacio --etapa APERTURA --severidad OBSERVACION --mensaje "La descripción del DIP está vacía."
```

## Alternativa B: escribir e integrar la regla manualmente

Para un dato normalizado de un DIP, agregue una función en `dips_audit/reglas.py`:

```python
def regla_descripcion_obligatoria(dip, ctx, r):
    if dip.get("estado") not in ACTIVOS:
        return
    if "descripcion" not in dip:
        r.manuales.append("Verificar descripción: dato no disponible.")
        return
    if not str(dip.get("descripcion") or "").strip():
        r.agregar(ctx, "descripcion_obligatoria", "Datos requeridos",
                  "La descripción del DIP está vacía.")
```

En **`auditar_dip`**, antes de `return r`, agregue:

```python
regla_descripcion_obligatoria(dip, ctx, r)
```

La función necesita esa conexión para ejecutarse. Use `r.agregar` para respetar
activación, tipo y severidad. Algunas reglas existentes fijan una severidad en
Python que prevalece sobre la del YAML en ciertos casos: revise esa excepción.

| Datos necesarios | Lugar de integración |
| --- | --- |
| Un solo DIP normalizado | `reglas.py` y llamada desde `auditar_dip` |
| Referencia asociada o datos de ICAM de una etapa específica | `auditor.py` o módulo correspondiente |
| Varios DIPs | Etapa del lote en `auditor.py` |
| Dato nuevo de ICAM | Extracción en `icam.py` y paso al DIP en `cargador.py`, antes de la regla |

Dentro del bloque `tipos:` de `config/discrepancias.yaml`, agregue:

```yaml
  Datos requeridos:
    reglas:
      descripcion_obligatoria: OBSERVACION
```

Si el tipo ya existe, agregue solo el código bajo sus `reglas:`. Use espacios,
respete la sangría y evite códigos repetidos. Para una regla de **CIERRE**, agregue
su código a `CODIGOS_CIERRE` en `reglas.py` y limite la función a los estados
correspondientes. `CODIGOS_CIERRE` clasifica la etapa; no limita cuándo se ejecuta.

Copie la prueba preparada a `tests/test_descripcion_obligatoria.py`. Compruebe
el caso que falla, el que cumple, la etapa, la regla desactivada, el dato no
disponible y las excepciones. La prueba debe pasar por el flujo real.

Desde la raíz de DIPS:

```bat
.venv\Scripts\python -m dips_audit validar-reglas
.venv\Scripts\python -m pytest
.venv\Scripts\python -m dips_audit benchmark
```

`validar-reglas` comprueba formato, severidades, duplicados y cobertura de códigos.
No verifica que la condición sea correcta ni que el flujo llame a la función.
Las pruebas y una auditoría de muestra comprueban eso. El benchmark permite
revisar el efecto en casos de la línea base: cada cambio debe tener una causa.

## Tipos, activación y severidades

Para un tipo nuevo con chequeos existentes, mueva sus códigos al nuevo bloque,
conservando severidad y activación. Si el bloque anterior queda sin reglas,
elimínelo. Revise los comandos con `--categorias`, pues el nombre habrá cambiado.

Desactivar una regla conservando su severidad:

```yaml
descripcion_obligatoria: {activa: false, severidad: OBSERVACION}
```

Para desactivar el tipo completo, agregue `activo: false` junto a `reglas:`.
Por defecto, tipos y reglas están activos. Use `true` o quite la desactivación
para reactivarlos. Una regla inactiva desaparece de los hallazgos.

| Severidad en YAML | Efecto visible |
| --- | --- |
| `CRITICA`, `NO CRITICA`, `REVISAR` | POSIBLE DISCREPANCIA |
| `CONSULTAR MANUAL` | REVISAR |
| `SIN FUENTE` | SIN FUENTE |
| `OBSERVACION` | Informa sin cambiar el resultado |

**`REVISAR` en YAML produce POSIBLE DISCREPANCIA.** Para obtener el resultado
visible REVISAR use `CONSULTAR MANUAL`. Prevalece el hallazgo de mayor severidad.
Los niveles críticos y no críticos son internos, no categorías visibles actuales.

```bat
.venv\Scripts\python -m dips_audit categorias
auditar.bat "entrada.xlsx" --categorias "Incorrect DIP Interval" RIR
auditar.bat "entrada.xlsx" --excluir-categorias "Missing S/N"
```

`--tipos-dip Others` filtra tipos de DIP (Area / Type DIP).
`--categorias RIR` filtra tipos de discrepancia. Son filtros distintos.

## Archivo y enlace de referencias

La tabla aporta los valores autorizados. No crea funciones ni chequeos nuevos.

- Archivo local inicial: **`DIPs References.xlsx`**, en la raíz de DIPS.
- Hoja: **`References`**.
- Fuente preferida: [DIPs References.xlsx en SharePoint](https://copaairlines.sharepoint.com/:x:/r/teams/VP_Tecnica/dacre/records/_layouts/15/doc2.aspx?sourcedoc=%7B71427FA7-2DB0-4851-A5BA-63F30401684E%7D&file=DIPs%20References.xlsx&action=default&mobileredirect=true).

El enlace procede de `referencias_sharepoint` en `config/config.yaml`. Ábralo con
su cuenta corporativa y permiso de acceso. Esta guía no modifica SharePoint.

En una auditoría normal, el programa intenta actualizar desde SharePoint. Inicie
sesión en la ventana de Edge si Microsoft lo pide. Valida la descarga antes de
sustituir la copia de `data/`. Si falla, usa la última copia válida; si no existe,
usa `DIPs References.xlsx`. La consola informa qué copia usa y su fecha.
Si ninguna fuente es válida, se detiene.

El programa asocia cada DIP con una fila por el catálogo, referencia técnica o
descripción. Después compara TA, RIR, Parent Assembly y fuentes técnicas según
las reglas aplicables. Un chequeo que necesita ICAM requiere esos datos: auditar
solo con el Excel ejecuta menos controles.

El modo prueba y el benchmark usan la referencia local, salvo `--referencias`.
Para elegir una fuente en una ejecución:

```bat
auditar.bat "entrada.xlsx" --referencias "DIPs References.xlsx"
auditar.bat "entrada.xlsx" --referencias "C:\Referencias\tabla.xlsx"
auditar.bat "entrada.xlsx" --referencias "C:\Referencias\tabla.pdf"
auditar.bat "entrada.xlsx" --referencias "ENLACE_HTTPS_DE_SHAREPOINT"
```

Sustituya las rutas y el enlace de ejemplo por los reales. Para cambiar la fuente
habitual, edite `referencias`, `referencias_sharepoint` y `hoja_referencias` en
`config/config.yaml`. Para usar siempre archivo local, deje
`referencias_sharepoint: ""`. Un PDF necesita texto seleccionable y las nueve
columnas en una misma tabla; un escaneo o tabla cortada no sirve.

## Cómo agregar una fila de referencia

Abra el SharePoint o archivo local que realmente va a usar. En `References`,
agregue la fila manteniendo las nueve columnas y sus encabezados:

| Columna | Contenido |
| --- | --- |
| TYPE | Tipo de DIP, como Others, Powerplant o Structures |
| AREA | Área según la tabla |
| ATA | Capítulo ATA |
| FLEET | Flota aplicable |
| DESCRIPTION | Nombre preciso del componente o condición |
| PARENT ASSY | Ensamblaje autorizado, como AIRCRAFT o ENGINE |
| REFERENCES | Fuente técnica: AMM, ECRA, SRM u otra |
| TA | Plazo y unidad: por ejemplo `3 DAYS` o `60 DAYS OR 500 FH` |
| RIR | Inspección repetitiva aplicable con intervalo y unidad |

Use valores aprobados de la fuente técnica. Los ejemplos de unidades no
constituyen autorizaciones de mantenimiento. Conserve condiciones por flota o
medición.

Una fila nueva puede reconocerse sin entrada de catálogo por su referencia
técnica o palabras de DESCRIPTION. Se informa como asociación a una fila sin
catálogo. Si hay ambigüedad, puede quedar SIN FUENTE. Para mejorar el
reconocimiento, añada una entrada en `config/catalogo_others.yaml` siguiendo una
entrada vecina:

```yaml
- id: ITEM_EJEMPLO
  nombre: "Nombre para el catálogo"
  referencias: ["DESCRIPTION exacta de la fila"]
  requiere: [[PALABRA_CLAVE], [ALTERNATIVA_1, ALTERNATIVA_2]]
  excluir: [PALABRA_DE_OTRO_ITEM]
```

Adapte el identificador y las palabras al ítem real. Cada grupo de `requiere`
exige al menos una frase. Una frase de `excluir` impide la coincidencia.
`referencias` debe coincidir con DESCRIPTION exactamente; si no, la carga falla.

```bat
.venv\Scripts\python -m dips_audit referencias --referencias "DIPs References.xlsx"
.venv\Scripts\python -m dips_audit benchmark
auditar.bat "entrada.xlsx" --referencias "DIPs References.xlsx" --prueba
```

`referencias --referencias "DIPs References.xlsx"` muestra la interpretación
de esa tabla local. Sin `--referencias`, el comando también intenta actualizar
desde SharePoint. Al cambiar una copia local, indique su ruta para probar
precisamente esa copia. `abrir-icam` también actualiza las referencias.

## Problemas frecuentes

| Problema | Qué revisar |
| --- | --- |
| Código no existe en el programa | Implementación pendiente o error de escritura en YAML |
| Código falta en discrepancias.yaml | Registro de una regla implementada |
| Regla nueva no aparece | Conexión al flujo, condición, tipo y regla activos, filtros |
| Chequeo de cierre aparece como apertura | `CODIGOS_CIERRE` y estados aplicables |
| REVISAR produce POSIBLE DISCREPANCIA | Use `CONSULTAR MANUAL` para el resultado REVISAR |
| Ítem nuevo sigue SIN FUENTE | Copia de referencias utilizada, DESCRIPTION y catálogo |
| DESCRIPTION del catálogo no existe | Texto exacto y versión de la tabla |
| Falló SharePoint | Acceso, sesión, enlace y aviso de copia de respaldo |

Consulte [la guía técnica](tecnico.md) para la lógica específica. El chequeo está
listo cuando sus casos, excepciones y conexión al flujo funcionan, el YAML
valida y el efecto en el benchmark tiene una explicación.
