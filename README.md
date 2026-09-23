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

1. `benchmark`: mide el programa contra DIPs ya auditados (ver [Benchmark](#benchmark)).
2. `anonimizar`: regenera el Excel del benchmark desde el histórico.
3. `referencias`: muestra cómo se leyó la tabla de referencias.
4. `benchmark-llm`: compara modelos locales.
5. `probar-llm`: prueba rápida del modelo.

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
2. El modelo solo se usa cuando las reglas no encuentran la referencia. Elige entre 6 candidatos o responde que ninguna.
3. Su respuesta se descarta si no comparte una palabra clave con el Fault Name o si el intervalo no es compatible.
4. Todo lo que sugiere el modelo queda en Revisar.

El modelo por defecto es `ministral-3:8b` (43 de 46 aciertos en `benchmark-llm`, 5.3 GB de RAM, ~17 s por consulta en CPU). Con 8 GB de RAM o menos, use `ministral-3:3b` (41 de 46, 2.3 GB). Se consulta pocas veces al día, así que la velocidad no es un problema.

## Benchmark

```bat
benchmark.bat
```

Audita los 915 DIPs de `benchmark/dips_auditados.xlsx` (julio y agosto de 2026) y compara el resultado con el veredicto del auditor. Tarda unos 2 segundos. Opciones: `--llm` (usa el modelo local) y `--guardar-linea-base`.

Muestra cada indicador junto a la línea base (`benchmark/linea_base.json`). Si alguno empeora, lo avisa y termina con código 2, y las pruebas fallan. Si el cambio es intencional, actualice la línea base con `benchmark.bat --guardar-linea-base`. El detalle queda en `salidas/BENCHMARK_*.xlsx`: la hoja Desacuerdos lista los DIPs donde el programa y el auditor no coinciden, con el comentario del auditor.

El Excel del benchmark es una copia anónima del histórico. No tiene las columnas del personal (auditor, diferido por, cuenta y cerrado por), y los nombres dentro de los comentarios quedan como `[PERSONA]`. Para regenerarlo cuando crezca el histórico, copie el histórico a la carpeta del proyecto y ejecute `anonimizar`. Revise los comentarios antes de subirlo.

Resultado actual, sobre los 619 DIPs Others con veredicto:

| Indicador | Resultado |
| --- | --- |
| Coincide con el auditor (OK o discrepancia) | 64.5 % |
| Asociados a una referencia solo con reglas | 84.8 % |
| OK del auditor que el programa también da OK | 68.1 % |
| OK del auditor que el programa marca con discrepancia | 7.1 % |
| OK del auditor que el programa deja en Revisar | 24.9 % |
| Discrepancias del auditor que el programa marca | 40.0 % |

1. En los 413 DIPs auditados hasta el 17-ago, el 85 % de los OK del auditor también sale OK. En los 206 posteriores, solo el 30 %.
2. La diferencia viene de dos causas: el tipo de intervalo `CDY` no se reconoce (queda en Revisar) y hay tipos de DIP que no están en el catálogo.
3. Las falsas discrepancias vienen de diferencias en la tabla de referencias (amortiguadores MAX, BLEED FAMV, BLEED CTRL CARD).
4. Las discrepancias que no se detectan dependen casi siempre de attachments, RIRs o S/N que no están en el Excel de entrada.

## Configuración

1. `DIPs References.xlsx`: tabla de referencias.
2. `config/catalogo_others.yaml`: palabras clave de cada tipo de DIP e intervalos condicionales (por flota o presión).
3. `config/config.yaml`: severidad de los hallazgos, tolerancias y modelo local.

Si se agrega una fila Others a la tabla, `referencias` avisa que falta en el catálogo.
