# Auditor preliminar de DIPs (Others)

Revisa el Excel exportado de ICAM y genera otro Excel con las posibles discrepancias de cada DIP. Un auditor debe confirmar cada discrepancia.

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

El histórico de auditorías no está en el repositorio porque tiene nombres del personal. Cópielo a la carpeta para usar `evaluar`.

## Uso

```bat
auditar.bat "C:\ruta\export_icam.xlsx"
```

También se puede arrastrar el Excel sobre `auditar.bat`. Opciones:

1. `--hoja NOMBRE`: hoja a leer. Por defecto, la primera con `Fault Barcode` y `Fault Name`.
2. `--fecha AAAA-MM-DD`: fecha de auditoría para detectar vencidos. Por defecto, hoy.
3. `--llm`: usa el modelo local para los DIPs que las reglas no asocian.
4. `--sin-excel`: muestra el resultado solo en consola.

Otros comandos, con `.venv\Scripts\python -m dips_audit`:

1. `referencias`: muestra cómo se leyó la tabla de referencias.
2. `evaluar`: compara contra las auditorías del histórico.
3. `benchmark`: compara modelos locales.
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
8. Cierre dentro del plazo, si el export trae la fecha de cierre.

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

El modelo por defecto es `ministral-3:8b` (43 de 46 aciertos en `benchmark`, 5.3 GB de RAM, ~17 s por consulta en CPU). Con 8 GB de RAM o menos, use `ministral-3:3b` (41 de 46, 2.3 GB). Se consulta pocas veces al día, así que la velocidad no es un problema.

## Validación

Contra 413 DIPs auditados entre julio y agosto de 2026:

1. El 93 % se asocia a una referencia solo con reglas.
2. De los DIPs que el auditor dio OK, el 85 % también sale OK, el 6 % sale con discrepancia y el 9 % queda en Revisar.
3. Ese 6 % viene de diferencias en la tabla de referencias (amortiguadores MAX, BLEED FAMV, BLEED CTRL CARD).
4. Las discrepancias que no se detectan dependen casi siempre de attachments, RIRs o S/N que no están en el Excel.

## Configuración

1. `DIPs References.xlsx`: tabla de referencias.
2. `config/catalogo_others.yaml`: palabras clave de cada tipo de DIP e intervalos condicionales (por flota o presión).
3. `config/config.yaml`: severidad de los hallazgos, tolerancias y modelo local.

Si se agrega una fila Others a la tabla, `referencias` avisa que falta en el catálogo.
