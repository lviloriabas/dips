# Auditor preliminar de DIPs (Others)

Revisa el Excel de entrada y genera otro Excel con las posibles discrepancias de cada DIP. Un auditor debe confirmar cada discrepancia.

Funciona sin internet, no se conecta a ICAM y no modifica el Excel original. El resultado queda en `salidas/`.

## Instalación

```bat
git clone https://github.com/lviloriabas/dips-ai.git
cd dips-ai
setup.bat
```

`setup.bat` se puede correr varias veces. Hace lo siguiente:

1. Instala Python 3.12 si no hay Python 3.11 o superior.
2. Crea el entorno `.venv` con las librerías de `requirements.txt`.
3. Instala Ollama y descarga el modelo local (~6 GB).
4. Corre las pruebas.

Opciones: `-ModeloLiviano` (usa `ministral-3:3b`), `-Modelo NOMBRE`, `-SinModelo` (sin Ollama, solo reglas) y `-SinPruebas`.

El histórico de auditorías no está en el repositorio porque tiene nombres del personal. En su lugar hay una copia anónima para el benchmark.

## Uso

```bat
auditar.bat "C:\ruta\entrada.xlsx"
```

También se puede arrastrar el Excel sobre `auditar.bat`. Opciones:

1. `--hoja NOMBRE`: hoja a leer. Por defecto, la primera con `Fault Barcode` y `Fault Name`.
2. `--fecha AAAA-MM-DD`: fecha de auditoría para detectar vencidos. Por defecto, hoy.
3. `--llm`: usa el modelo local para los DIPs que las reglas no asocian.
4. `--sin-excel`: muestra el resultado solo en consola.

Otros comandos, con `.venv\Scripts\python -m dips_audit`:

1. `benchmark`: mide el programa y el modelo local con DIPs ya auditados (ver [Benchmark](#benchmark)).
2. `anonimizar`: regenera el Excel del benchmark desde el histórico.
3. `referencias`: muestra cómo se leyó la tabla de referencias.
4. `probar-llm`: prueba rápida del modelo.

Las pruebas se corren con `.venv\Scripts\python -m pytest`.

## Qué revisa

1. Intervalo y tipo de intervalo contra `DIPs References.xlsx`.
2. Parent assy (AIRCRAFT o ENGINE).
3. Due date según fecha de apertura e intervalo, y que no pase el vencimiento de la descripción.
4. DIPs activos vencidos y Usage Remaining mayor que el intervalo.
5. DIPs duplicados o con el mismo S/N.
6. S/N en la descripción (solo como observación).
7. Deferral Reference y ATA.
8. Cierre dentro del plazo, si el Excel de entrada trae la fecha de cierre.

Attachments, referencia técnica y RIRs no vienen en el Excel; quedan como verificación manual.

## Resultado

Cada DIP queda en uno de estos estados:

1. Discrepancia crítica o no crítica: falló una regla. Se muestra el valor encontrado y el esperado.
2. Revisar: no tiene referencia en la tabla o la asociación la sugirió el modelo.
3. OK: no falló ninguna regla. Las verificaciones manuales siguen pendientes.

Las observaciones son notas que no cambian el estado.

## Uso del modelo local

1. Las reglas deciden el resultado. El modelo nunca marca un DIP como OK ni como discrepancia.
2. El modelo solo se usa cuando las reglas no encuentran la referencia. Elige entre unas pocas referencias candidatas (las más parecidas al Fault Name) o responde que ninguna.
3. Su respuesta se descarta si no comparte una palabra clave con el Fault Name o si el intervalo no es compatible.
4. Todo lo que sugiere el modelo queda en Revisar.

El modelo por defecto es `ministral-3:8b` (5.3 GB de RAM). Con 8 GB de RAM o menos, use `ministral-3:3b` (2.3 GB). El modelo, las preguntas que se le hacen y la validación se ajustan en la sección `llm` de `config/config.yaml`; el efecto de cada ajuste se mide con el [benchmark](#benchmark).

## Benchmark

```bat
benchmark.bat
```

No tiene opciones. Lo que se ajusta está en `config/config.yaml`. Mide tres cosas:

1. **Auditoría.** Audita los 50 DIPs Others de `benchmark/dips_auditados.xlsx` con reglas y modelo local, y compara el resultado con el veredicto del auditor.
2. **Modelo local.** Le pregunta al modelo por los 46 Fault Names de `benchmark/casos_modelo_local.yaml`: las reglas no los resuelven y tienen anotada la referencia correcta. Compara al modelo con una alternativa sin modelo, que elige siempre la referencia más parecida y pasa por la misma validación.
3. **Costo.** Tiempo de cada etapa, segundos y tokens por consulta, y memoria del modelo.

Mientras corre muestra la etapa, el tiempo transcurrido, lo que falta y el total estimado. Casi todo el tiempo es del modelo: en un i7-1265U sin GPU tarda unos 33 min, con 50 consultas de unos 40 s. Mientras corre, Windows no apaga la pantalla ni se suspende: en suspensión el modelo se detiene y los tiempos no sirven. Sin Ollama mide solo las reglas en unos segundos y lo avisa.

Cada corrida deja dos archivos en `benchmark/resultados/`:

1. `AAAA-MM-DD_HHMMSS.json`: todos los datos, para guardar y comparar corridas.
2. `AAAA-MM-DD_HHMMSS.md`: el mismo resultado para leer. Tiene el resumen, cómo se audita, los indicadores, cómo se asoció cada DIP, los tiempos, la configuración usada y los DIPs donde el programa y el auditor no coinciden.

`benchmark/linea_base.json` es la copia de un resultado anterior. El benchmark muestra cada indicador junto a la línea base; si alguno empeora, lo avisa y termina con código 2. Si el cambio es intencional, copie el JSON del resultado sobre `benchmark/linea_base.json`. Las pruebas comparan la auditoría solo con reglas contra la línea base.

### Cómo ajustar

1. Cambie un valor de `config/config.yaml` (sección `llm`) o del catálogo.
2. Ejecute `benchmark.bat`.
3. Compare el Markdown del resultado con la línea base: aciertos, referencias equivocadas aceptadas y segundos por consulta.

Parámetros del modelo local:

| Parámetro | Qué cambia |
| --- | --- |
| `modelo` | El modelo de Ollama. Debe estar descargado (`ollama pull NOMBRE`). |
| `candidatos` | Cuántas referencias se le muestran. Menos candidatos, prompt más corto y más rápido. |
| `justificacion` | Si pide una justificación corta. Sin justificación la respuesta es más corta y más rápida. |
| `pensar` | Modo thinking (solo algunos modelos). Mucho más lento. |
| `temperatura`, `contexto_tokens`, `max_tokens_respuesta` | Cómo genera la respuesta. |
| `fraccion_minima_ta` | Validación: fracción mínima del TA que debe tener el intervalo del DIP. |

Las instrucciones que recibe el modelo están en `dips_audit/llm.py` (`_SISTEMA`).

### Datos

Los 50 DIPs son una muestra fija del histórico de julio y agosto de 2026: solo Others con veredicto (OK, no crítica o crítica), en la misma proporción que el histórico, y con intervalo y tipo de intervalo en el Excel de entrada. La muestra tiene 44 OK, 5 discrepancias no críticas y 1 crítica.

Son los datos del Excel de entrada del día de la auditoría. Hoy esos DIPs ya están corregidos en ICAM, así que los que no traen intervalo se descartan en lugar de completarlos desde ICAM. Cuando el programa se use antes de la auditoría, los DIPs llegarán sin corregir, como en esta muestra.

El Excel del benchmark es una copia anónima del histórico. No tiene las columnas del personal (auditor, diferido por, cuenta y cerrado por), y los nombres dentro de los comentarios quedan como `[PERSONA]`. Para regenerarlo cuando crezca el histórico, copie el histórico a la carpeta del proyecto y ejecute `anonimizar`. Con `--cantidad N` cambia el tamaño de la muestra (por defecto 50; 0 = todos los Others) y con `--semilla N` se elige otra muestra. Revise los comentarios antes de subirlo. Después de regenerarlo, ejecute el benchmark y copie el resultado como línea base.

### Resultado actual

Con `ministral-3:8b`, 6 candidatos y justificación, en un i7-1265U sin GPU (`benchmark/resultados/2026-09-23_152638.md`):

| Indicador | Resultado |
| --- | --- |
| Coincide con el auditor (OK o discrepancia) | 42 de 50 |
| Asociados a una referencia solo con reglas | 45 de 50 |
| OK del auditor que el programa también da OK | 38 de 44 |
| OK del auditor que el programa marca con discrepancia | 3 de 44 |
| OK del auditor que el programa deja en Revisar | 3 de 44 |
| Discrepancias del auditor que el programa marca | 4 de 6 |
| Modelo local: casos bien resueltos | 44 de 46 (sin modelo: 43 de 46) |
| Modelo local: referencias equivocadas aceptadas | 0 de 46 (sin modelo: 2 de 46) |
| Tiempo total | 33 min (39 s por consulta, 5.3 GB de RAM) |

1. Con 6 discrepancias en la muestra, cada una vale casi 17 puntos en ese indicador. Para medir la detección con más precisión, regenere la muestra con más DIPs (`anonimizar --cantidad N`).
2. En esta muestra el modelo no cambia el veredicto de ningún DIP: responde NINGUNA en los 5 que las reglas no asocian. Su aporte se ve en los casos: acierta uno más que la alternativa sin modelo y no acepta referencias equivocadas.
3. Las falsas discrepancias vienen de diferencias con la tabla de referencias (amortiguadores MAX y extintor de agua abierto en horas).
4. Las discrepancias que no se detectan dependen de attachments o S/N que no están en el Excel de entrada.
5. Ajustes probados: con 4 candidatos y sin justificación cada consulta tarda 24 s en vez de 39 s, pero el modelo resuelve bien 41 de 46 casos, menos que la alternativa sin modelo. Por eso no se usan (`benchmark/resultados/2026-09-23_144544.md`).

## Configuración

1. `DIPs References.xlsx`: tabla de referencias.
2. `config/catalogo_others.yaml`: palabras clave de cada tipo de DIP e intervalos condicionales (por flota o presión).
3. `config/config.yaml`: severidad de los hallazgos, tolerancias y modelo local.

Si se agrega una fila Others a la tabla, `referencias` avisa que falta en el catálogo.
