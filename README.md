# Auditor preliminar de DIPs (Others)

Herramienta de consola que audita el Excel exportado de **ICAM** y genera un Excel con
las posibles discrepancias de cada DIP (deferred item project). Es un **apoyo**: toda
discrepancia debe confirmarla un auditor.

- Funciona 100 % local, sin internet y sin costo por uso.
- No modifica el Excel original: escribe un archivo nuevo en `salidas/`.
- No se conecta a ICAM.

## Uso rápido

```bat
auditar.bat "C:\ruta\export_icam.xlsx"
```

También puede arrastrar el Excel sobre `auditar.bat`. Opciones:

| Opción | Uso |
|---|---|
| `--hoja NOMBRE` | Hoja a leer (por defecto, la primera que tenga `Fault Barcode` y `Fault Name`) |
| `--fecha AAAA-MM-DD` | Fecha de auditoría para detectar DIPs vencidos (por defecto, hoy) |
| `--llm` | Usa el modelo local para los DIPs que las reglas no pudieron asociar |
| `--sin-excel` | Solo muestra el resultado en consola |

Otros comandos (desde la carpeta del proyecto):

```bat
.venv\Scripts\python -m dips_audit referencias   :: cómo se interpretó la tabla de referencias
.venv\Scripts\python -m dips_audit evaluar       :: compara contra las auditorías humanas del histórico
.venv\Scripts\python -m dips_audit benchmark     :: compara modelos locales (precisión, velocidad, RAM)
.venv\Scripts\python -m dips_audit probar-llm    :: prueba rápida del modelo local
.venv\Scripts\python -m pytest                    :: pruebas automáticas
```

## Qué revisa

| Revisión | Desde el Excel |
|---|---|
| Intervalo y tipo de intervalo contra `DIPs References.xlsx` (por flota, meses, condiciones) | Sí |
| Parent assy (AIRCRAFT / ENGINE) | Sí |
| Due date coherente con apertura + intervalo | Sí |
| Due date posterior al vencimiento indicado en la descripción | Sí |
| DIP activo vencido; Usage Remaining mayor que el intervalo | Sí |
| DIPs duplicados; mismo S/N en dos DIPs | Sí |
| S/N mencionado en la descripción | Sí (observación) |
| Deferral Reference / ATA | Sí |
| Completado dentro del plazo | Solo si el export trae la fecha de cierre |
| Attachments, captura de referencia técnica, RIRs | No; aparecen como verificación manual |

### Estados del resultado

- **DISCREPANCIA CRÍTICA / NO CRÍTICA:** una regla falló. Se incluye la evidencia: valor encontrado y valor esperado.
- **REVISAR:** el DIP no tiene referencia en la tabla, o la asociación la sugirió el modelo local. Requiere un humano.
- **OK:** ninguna regla falló. Las verificaciones manuales (attachments, RIR) siguen pendientes.
- **Observaciones:** notas que no cambian el estado. Por ejemplo, falta el S/N o el intervalo es menor al de referencia.

## Cómo evita "alucinar"

1. **Las reglas deciden el veredicto.** El modelo local nunca marca un DIP como OK ni como discrepancia.
2. **El modelo solo interviene si las reglas no asocian el DIP.** Elige entre 6 candidatos o responde NINGUNA. La respuesta se fuerza con un esquema JSON y temperatura 0.
3. **Toda sugerencia del modelo se valida.** Debe compartir una palabra distintiva con el Fault Name y el intervalo del DIP debe ser compatible con el TA. Si no cumple, se descarta.
4. **Lo sugerido por la IA queda en REVISAR,** con su justificación, para que lo confirme un auditor.

## Resultados de validación (histórico 9-jul a ago-2026)

`python -m dips_audit evaluar` compara el resultado automático con lo que concluyeron los auditores en 413 DIPs Others:

- **Cobertura:** 93 % se asocian a una referencia solo con reglas. El resto no tiene fila en la tabla (puertas de acceso, redes de carga, sellante, desfibrilador, ULB…).
- **DIPs que el auditor dio OK:** el 85 % también sale OK, el 6 % sale con discrepancia y el 9 % sale como REVISAR (sin referencia).
- **Ese 6 % se concentra en conflictos de la tabla, no del programa:**
  - Amortiguadores MAX: la tabla dice 10 FC y se aceptan 15 y 20.
  - BLEED FAMV: la tabla dice 30 FH y ENGINE; se abre con 150 FH y AIRCRAFT.
  - BLEED CTRL CARD: la tabla dice 2902 FH, pero los comentarios humanos mencionan 2930 o 3000.
- **Discrepancias humanas que no se detectan:** la mayoría dependen de attachments, RIRs o S/N de tarjetas, que no vienen en el Excel.

## Modelo local (benchmark, 23-sep-2026)

`python -m dips_audit benchmark` evalúa 46 casos difíciles (`tests/datos/benchmark_llm.yaml`): 26 DIPs con referencia escritos con errores de tipeo, abreviaturas o en español, y 20 DIPs reales sin referencia.

"Aciertos del modelo" es lo que responde el modelo por sí solo. "Final" es el resultado después de las validaciones deterministas. Un "error aceptado" es una referencia equivocada que pasó las validaciones; aun así, ese DIP queda en REVISAR.

| Modelo | Aciertos modelo | Final | Errores aceptados | s/consulta solo CPU* | RAM |
|---|---|---|---|---|---|
| **ministral-3:8b** (predeterminado) | 43/46 | 43/46 | 1 | 17.2 | 5.3 GB |
| qwen3:4b | 31/46 | 44/46 | 1 | 11.5 | 2.7 GB |
| gemma4:e4b-it-qat | 40/46 | 42/46 | 1 | 14.0 | 5.6 GB |
| ministral-3:3b (alternativa liviana) | 40/46 | 41/46 | 1 | 9.5 | 2.3 GB |
| llama3.2:3b | 36/46 | 39/46 | 1 | 7.5 | 2.2 GB |
| gemma4:e2b-it-qat | 35/46 | 44/46 | 2 | 8.3 | 3.6 GB |
| qwen3:4b con *thinking* | 39/46 | 39/46 | 0 | ~4x más lento | 3.0 GB |
| qwen3.5 (2b/4b/9b), qwen3:8b, granite4.1 (3b/8b), phi4-mini | 24–40/46 | 37–43/46 | 1–4 | — | 2–5 GB |

\* Medido forzando CPU (`--cpu`) en un Ryzen 5 3600 de 6 núcleos con DDR4. En un i7 de 14.ª generación debería ser más rápido; confírmelo corriendo `benchmark --cpu --casos 12` en esa PC.

Se eligió **ministral-3:8b** porque es el más confiable por sí mismo: sus aciertos no dependen de las validaciones. qwen3:4b llega al mismo resultado final, pero porque las validaciones corrigen muchas de sus respuestas.

La velocidad no es un problema: el modelo solo se consulta para los DIPs que las reglas no asocian (~7 %, uno o dos por día). Con 8 GB de RAM libres o menos, use `ministral-3:3b`.

## Configuración

- `DIPs References.xlsx`: tabla de referencias (fuente de verdad del TA, parent assy y referencia técnica).
- `config/catalogo_others.yaml`: cómo reconocer cada tipo de DIP (palabras clave) y los TA condicionales
  (por flota, por presión) que la tabla tiene en texto libre.
- `config/config.yaml`: severidad de cada hallazgo, tolerancias y modelo local.

Si se agrega una fila Others a la tabla, `referencias` avisa que falta en el catálogo.

## Instalación

```bat
git clone https://github.com/lviloriabas/dips-ai.git
cd dips-ai
setup.bat
```

`setup.bat` instala todo lo necesario y se puede ejecutar varias veces; lo que ya está instalado se omite:

1. Python 3.12, si no hay un Python 3.11 o superior. Usa winget o, si no está disponible, el instalador de python.org, solo para el usuario actual.
2. El entorno virtual `.venv` con las librerías de `requirements.txt`.
3. [Ollama](https://ollama.com) y el modelo de `config/config.yaml` (`llm.modelo`, ~6 GB).
4. Las pruebas automáticas.

| Opción | Uso |
|---|---|
| `setup.bat -ModeloLiviano` | Descarga `ministral-3:3b` (2.3 GB de RAM) en lugar del modelo predeterminado |
| `setup.bat -SinModelo` | No instala Ollama; la auditoría con reglas funciona igual |
| `setup.bat -Modelo qwen3:4b` | Descarga un modelo específico |
| `setup.bat -SinPruebas` | No corre las pruebas al final |

**Datos que no están en el repositorio:**
- El histórico de auditorías (`02 - HISTORY - DIPs AUDIT ....xlsx`), porque contiene nombres del personal. Cópielo a la carpeta para usar `evaluar` y la prueba de regresión, que sin él se omite.
- Los reportes generados en `salidas/`.
