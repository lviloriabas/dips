# DIPS: guía rápida de uso y configuración

Esta misma guía está en [PowerPoint](Guia_DIPS_reglas_referencias.pptx) y [PDF](Guia_DIPS_reglas_referencias.pdf). El orden es: uso del programa, resultados y colores, referencias del Excel y YAML de discrepancias.

## Ejecutar el programa

Abra una **terminal (CMD o PowerShell)** en la carpeta DIPS. En esta guía, `$` indica un comando y se omite al escribirlo. Cambie `entrada.xlsx` por el nombre o la ruta de su Excel, entre comillas. Conserve `.\` delante del comando para ejecutarlo desde esa carpeta.

**Primera instalación:** ejecute una vez:

```terminal
$ .\setup.bat
```

**Auditar con el Excel:** también puede arrastrarlo sobre `auditar.bat`.

```terminal
$ .\auditar.bat "entrada.xlsx"
```

**Auditar con ICAM y solo los pendientes:**

```terminal
$ .\auditar.bat "entrada.xlsx" --icam --pendientes
```

- `--icam`: consulta los DIPs en ICAM y permite más chequeos. Si Edge pide sesión, iníciela allí.
- `--pendientes`: incluye ACTV sin DIP Open Audit User y COMPLETE sin DIP Closed Audit User. Crea una copia `FILTERED.xlsx` junto al original. Quite esta opción para auditar todos.

**Consultar un DIP por barcode:**

```terminal
$ .\auditar.bat T40S0099V9C
```

Sustituya el barcode de ejemplo por el real. El programa consulta el DIP en ICAM y muestra los datos, el resultado y los hallazgos en la terminal. Esta consulta no genera un Excel de resultado.

Los **resultados** quedan en **`salida/`**. El Excel incluye los resultados de la auditoría y la hoja **Dashboard**, que muestra indicadores y gráficos del resultado. La sección siguiente explica los seis resultados y sus colores.

## Resultados y colores

La columna `RESULTADO` usa estos colores en el Excel de salida. Cada resultado indica qué revisar. Lea también `HALLAZGOS` y `VERIFICACIÓN MANUAL` para conocer la evidencia y los pasos pendientes.

1. **POSIBLE DISCREPANCIA.** El programa detectó una posible discrepancia. Revise el hallazgo y su evidencia antes de registrar la auditoría.
2. **CORREGIDO EN CIERRE.** DIP COMPLETE: la apertura tuvo una posible discrepancia y el cierre quedó OK. Revise ambos estados y complete la verificación manual.
3. **EXTENSIÓN.** El DIP tiene una extensión del T/A por fecha, FH o FC. Revise su soporte de autorización; se conserva este resultado aunque exista un OK manual de cierre.
4. **REVISAR.** El TA o el RIR depende del daño, de una condición o del manual. Consulte la referencia técnica para definir el límite aplicable.
5. **SIN FUENTE EN DIPS REFERENCES.** El DIP no tiene una referencia asociada en el Excel de referencias. Compruebe la fuente y complete los datos aprobados de la tabla.
6. **OK.** La auditoría automática no detectó una posible discrepancia. Complete los puntos pendientes en `VERIFICACIÓN MANUAL`. Un DIP COMPLETE que el auditor ya marcó en ICAM con el cierre sin discrepancia ("DIP CLOSED - RT AUDIT COMPLETED" en Technical References) también queda OK, aunque el programa encuentre otras discrepancias. En ese caso `ESTADO APERTURA`, `ESTADO CIERRE` y `HALLAZGOS` muestran lo que encontró el programa, y `VERIFICACIÓN MANUAL` lo indica para revisarlo. La duplicación siempre conserva la posible discrepancia, incluso después de cerrar o con ese OK manual.
7. **FUERA DE ALCANCE.** El tipo de DIP quedó fuera de los tipos elegidos para auditar. El programa no evaluó ese DIP en esta ejecución.

En cada etapa de auditoría prevalece **POSIBLE DISCREPANCIA**, luego **EXTENSIÓN**, **REVISAR** y **SIN FUENTE EN DIPS REFERENCES**. Los demás hallazgos siguen visibles. **CORREGIDO EN CIERRE** se calcula al comparar las etapas de auditoría (apertura y cierre).

## Referencias del Excel

El programa usa **`DIPs References.xlsx` como tabla de referencias**. Cada fila describe una referencia. Para cada DIP busca la fila aplicable y compara sus datos con el TA, el RIR y la fuente técnica de esa fila.

- **Archivo local:** `DIPs References.xlsx`, en la carpeta DIPS. Hoja **`References`**.
- **Archivo compartido:** [DIPs References.xlsx en SharePoint](https://copaairlines.sharepoint.com/:x:/r/teams/VP_Tecnica/dacre/records/_layouts/15/doc2.aspx?sourcedoc=%7B71427FA7-2DB0-4851-A5BA-63F30401684E%7D&file=DIPs%20References.xlsx&action=default&mobileredirect=true).
- **Configuración:** `config/config.yaml`. `referencias` indica el archivo local, `hoja_referencias` la hoja y `referencias_sharepoint` el enlace compartido.

Cada referencia tiene los siguientes campos:

| Campo del Excel | Contenido de la referencia |
| --- | --- |
| `TYPE` | Tipo de referencia o de DIP. |
| `AREA` | Área a la que pertenece la referencia. |
| `ATA` | Capítulo ATA del sistema o componente. |
| `FLEET` | Flota o modelo al que aplica. |
| `DESCRIPTION` | Descripción para identificar la condición o el componente. |
| `PARENT ASSY` | Conjunto al que se asocia el DIP, como AIRCRAFT o ENGINE. |
| `REFERENCES` | Manual o documento técnico que respalda la referencia. |
| `TA` | Plazo o límite permitido para corregir la condición. |
| `RIR` | Intervalo de la inspección repetitiva, cuando aplica. |

Para agregar o corregir una referencia, edite una fila con valores aprobados y conserve los encabezados. Use una descripción precisa. **TA y RIR incluyen valor y unidad**, por ejemplo `30 DAYS`, `100 FH` o `50 FC`.

La auditoría consulta SharePoint en cada corrida real y actualiza el archivo local si el contenido validado cambió. Las referencias e ICAM usan pestañas de una misma ventana de Edge durante toda la corrida. Si pide sesión, iníciela allí. Si falla SharePoint, usa la última copia válida descargada o el archivo local principal. **La terminal indica qué copia usó y su fecha.** Si ninguna es válida, se detiene.

## YAML de discrepancias

El programa ya está configurado para funcionar correctamente. **No necesita modificar el YAML por ahora.** Esta sección sirve de referencia para cambios futuros. Si necesita ajustar algún chequeo más adelante:

1. Abra **`config/discrepancias.yaml`** en un editor de texto.
2. Busque la regla y cambie su severidad o activación. Conserve los códigos y la sangría con espacios.
3. Guarde. La siguiente auditoría usa el cambio y comprueba el YAML automáticamente.

**Cambiar la severidad:** este ejemplo muestra un bloque existente.

```yaml
tipos:
  Incorrect DIP Interval:
    reglas:
      intervalo_excedido: POSIBLE DISCREPANCIA
      intervalo_menor: OK
```

**Desactivar una regla:** sustituya su línea por:

```yaml
intervalo_excedido: {activa: false, severidad: POSIBLE DISCREPANCIA}
```

Para reactivarla, cambie `false` por `true`. Para desactivar un tipo completo, agregue `activo: false` debajo del nombre del tipo, a la misma altura que `reglas:`.

| Valor en YAML | Efecto en el resultado |
| --- | --- |
| `POSIBLE DISCREPANCIA` | POSIBLE DISCREPANCIA |
| `REVISAR` | REVISAR |
| `SIN FUENTE EN DIPS REFERENCES` | SIN FUENTE EN DIPS REFERENCES |
| `OK` | Caso aceptado; el DIP queda OK si no hay otro hallazgo |

Se aplica la prioridad explicada en la lista de resultados. **CORREGIDO EN CIERRE** se calcula y no se asigna a una regla.

**La configuración de los chequeos disponibles está en el YAML.** Para cambios futuros, edite `config/discrepancias.yaml` y guarde. La siguiente auditoría utiliza esa configuración. **CORREGIDO EN CIERRE** se calcula y no se asigna a una regla.
