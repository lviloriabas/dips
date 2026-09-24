# Auditor preliminar de DIPs

Audita los DIPs Others de un Excel con los datos de **ICAM** (solo lectura) y `DIPs References.xlsx`. Resultado por DIP: **POSIBLE DISCREPANCIA** u **OK**, con el motivo. Reglas fijas, sin IA. Detalle en [docs/tecnico.md](docs/tecnico.md).

## Instalación

```bat
git clone https://github.com/lviloriabas/dips-ai.git
cd dips-ai
setup.bat
```

## Uso

| Acción | Cómo | Resultado |
| --- | --- | --- |
| Auditar | Arrastrar el Excel sobre `auditar.bat` | `salidas/...xlsx`, filtrar `RESULTADO` |
| Comparar con la auditoría manual | Arrastrar `DIPs Audit (...).xlsx` sobre `comparar.bat` | `salidas/..._COMPARACION_...xlsx` (hojas **Resumen** y **Detalle por DIP**) |
| Modo prueba | Poner el Excel en `pruebas/entrada/` (o usar `--prueba`) | `pruebas/salidas/PRUEBA_...xlsx` |

Por defecto se audita **solo con el Excel** (menos reglas). Para leer en ICAM todos los DIPs del archivo, de cualquier tipo, ejecute el `.bat` en la consola con `--icam` (ver [Comandos](#comandos)); el programa no hace preguntas.

Con `--icam` se abre una ventana de Edge en ICAM: si pide sesión, iníciela ahí. El programa sigue apenas la sesión se inicia y se detiene apenas la página de inicio de sesión muestra un error. Deje la ventana abierta para las próximas corridas.

## Comandos

```bat
auditar.bat "DIPs Audit (23SEP2026).xlsx" --icam
auditar.bat "DIPs Audit (23SEP2026).xlsx" -f "2026-09-23 14:00"
auditar.bat "DIPs Audit (23SEP2026).xlsx" --categorias "Incorrect DIP Interval" RIR
auditar.bat "DIPs Audit (23SEP2026).xlsx" --excluir-categorias "Missing S/N"
comparar.bat "DIPs Audit (23SEP2026).xlsx" -i -e RIR
```

| Opción | Uso |
| --- | --- |
| `-i`, `--icam` | Leer en ICAM todos los DIPs del archivo (sin esta opción, solo el Excel: menos reglas) |
| `--datos-icam RUTA` | Usar datos de ICAM ya extraídos (carpeta `data/icam` o CSV), sin leer ICAM |
| `-j`, `--hoja NOMBRE` | Hoja a leer (por defecto, la que tiene `Fault Barcode`) |
| `-f`, `--fecha "AAAA-MM-DD HH:MM"` | Auditar a esa fecha y hora |
| `-n`, `--sin-excel` | Resultado solo en consola |
| `-c`, `--categorias TIPO ...` | Solo esos tipos de discrepancia (basta parte del nombre) |
| `-e`, `--excluir-categorias TIPO ...` | Todos menos esos tipos |
| `-p`, `--prueba` | Forzar modo prueba |
| `-o`, `--salida RUTA` | Excel de resultado (solo `auditar`) |

Otros comandos (`.venv\Scripts\python -m dips_audit ...`):

| Comando | Uso |
| --- | --- |
| `categorias` | Lista los tipos de discrepancia |
| `referencias` | Muestra cómo se interpretó la tabla de referencias |
| `extraer-icam archivo.xlsx` / `--barcode X` | Solo leer ICAM |
| `abrir-icam` | Abrir el Edge de ICAM para iniciar sesión |
| `benchmark` | Medir contra los DIPs ya auditados ([ver](docs/tecnico.md#10-benchmark)) |

Pruebas: `.venv\Scripts\python -m pytest`

## Resultado

| `RESULTADO` | Qué hacer |
| --- | --- |
| POSIBLE DISCREPANCIA | Leer `HALLAZGOS` y decidir |
| OK | Hacer las verificaciones de `VERIFICACIÓN MANUAL` |

Otras columnas: `COMENTARIO SUGERIDO`, `AUDITORÍA` (APERTURA/CIERRE), `ESTADO APERTURA` / `ESTADO CIERRE`, `REFERENCIA ASOCIADA`, `REFERENCIA TÉCNICA DEL DIP`, `RIR EN ICAM`, `ADJUNTOS EN ICAM`. El Excel de entrada no se modifica.

## Ajustes

| Qué | Dónde |
| --- | --- |
| Reglas activas y observaciones | `config/discrepancias.yaml` |
| Tolerancias, lectura de ICAM, manuales sin REV/fecha | `config/config.yaml` |
| Palabras clave de referencias Others | `config/catalogo_others.yaml` |
| TA, Parent Assembly, AMM/ECRA, RIR | `DIPs References.xlsx` |

Tras cambiar una regla, correr `benchmark` y comparar con la línea base.

## Problemas frecuentes

| Mensaje | Solución |
| --- | --- |
| "No se pudo iniciar sesión en ICAM: ..." | La página de inicio de sesión dio ese error (usuario o clave). Revisar y volver a arrastrar el archivo |
| "No se inició sesión en ICAM en 3 minutos" | Iniciar sesión en el Edge de ICAM y volver a arrastrar el archivo |
| "La sesión de ICAM venció" | Iniciar sesión de nuevo; lo ya leído queda guardado |
| "Permission denied" | Cerrar el Excel de salida |
| "Faltan columnas obligatorias" | Formato inesperado; ver [docs/tecnico.md](docs/tecnico.md#1-lectura-del-excel-de-entrada) |

## Documentos

- [tecnico.md](docs/tecnico.md): funcionamiento y reglas en detalle
- [proceso.md](docs/proceso.md): proceso en diagramas
- [comparacion_modos.md](docs/comparacion_modos.md): registro del modo con agente (eliminado)
