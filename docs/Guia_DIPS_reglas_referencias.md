# DIPS: guía rápida de uso y configuración

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

Los resultados de auditoría quedan en **`salidas/`**. Revise `RESULTADO`, `HALLAZGOS` y `VERIFICACIÓN MANUAL`: **POSIBLE DISCREPANCIA** requiere revisar el hallazgo, **REVISAR** consultar el manual, **SIN FUENTE** comprobar la referencia y **OK** completar las verificaciones manuales.

## Configurar los chequeos desde el YAML

1. Abra **`config/discrepancias.yaml`** en un editor de texto.
2. Busque la regla y cambie su severidad o activación. Conserve los códigos y la sangría con espacios.
3. Guarde. La siguiente auditoría usa el cambio y comprueba el YAML automáticamente.

**Cambiar la severidad:** este ejemplo muestra un bloque existente.

```yaml
tipos:
  Incorrect DIP Interval:
    reglas:
      intervalo_excedido: CRITICA
      intervalo_menor: OBSERVACION
```

**Desactivar una regla:** sustituya su línea por:

```yaml
intervalo_excedido: {activa: false, severidad: CRITICA}
```

Para reactivarla, cambie `false` por `true`. Para desactivar un tipo completo, agregue `activo: false` debajo del nombre del tipo, a la misma altura que `reglas:`.

| Valor en YAML | Efecto en el resultado |
| --- | --- |
| `CRITICA`, `NO CRITICA`, `REVISAR` | POSIBLE DISCREPANCIA |
| `CONSULTAR MANUAL` | REVISAR |
| `SIN FUENTE` | SIN FUENTE |
| `OBSERVACION` | Informa sin cambiar el resultado |

Prevalece el hallazgo de mayor severidad.

**La configuración de los chequeos disponibles está en el YAML.** Edite `config/discrepancias.yaml` para cambiar su activación o severidad y guarde. La siguiente auditoría utiliza esta configuración.

## Usar y actualizar las referencias

La tabla aporta el **TA, RIR, Parent Assembly y la fuente técnica** con los que el programa revisa cada DIP.

- **Archivo local:** `DIPs References.xlsx`, en la carpeta DIPS. Hoja **`References`**.
- **Archivo compartido:** [DIPs References.xlsx en SharePoint](https://copaairlines.sharepoint.com/:x:/r/teams/VP_Tecnica/dacre/records/_layouts/15/doc2.aspx?sourcedoc=%7B71427FA7-2DB0-4851-A5BA-63F30401684E%7D&file=DIPs%20References.xlsx&action=default&mobileredirect=true).
- **Configuración:** `config/config.yaml`. `referencias` indica el archivo local, `hoja_referencias` la hoja y `referencias_sharepoint` el enlace compartido.

Para agregar o corregir una referencia, edite una fila de la tabla con los valores aprobados. Conserve los encabezados **TYPE, AREA, ATA, FLEET, DESCRIPTION, PARENT ASSY, REFERENCES, TA y RIR**. Use una descripción precisa y escriba TA/RIR con su unidad, por ejemplo `30 DAYS`.

La auditoría intenta actualizar desde SharePoint. Si pide sesión, iníciela en Edge. Si falla, usa la última copia válida descargada o el archivo local inicial. **La consola indica qué copia usó y su fecha.** Si ninguna es válida, se detiene.

Esta misma guía está en [PowerPoint](Guia_DIPS_reglas_referencias.pptx) y [PDF](Guia_DIPS_reglas_referencias.pdf).
