# Configurar las reglas

Las reglas deciden qué hallazgos aparecen y cómo se clasifica cada DIP. Sus criterios de detección están en Python; `config/discrepancias.yaml` decide si se informa cada hallazgo y qué resultado produce. Para cambiar un criterio de detección o crear una regla nueva hace falta modificar el código y sus pruebas.

## Cambiar una regla existente

1. Ejecute `.venv\Scripts\python -m dips_audit categorias` para ver los tipos y códigos de regla. El mismo código está comentado en `config/discrepancias.yaml` con una explicación breve.
2. Busque el código en `config/discrepancias.yaml` y cambie el valor a la derecha de `:`. Por ejemplo:

   ```yaml
   tipos:
     Incorrect DIP Interval:
       reglas:
         intervalo_excedido: CRITICA     # posible discrepancia
         intervalo_menor: OBSERVACION  # se informa, pero no cambia el resultado
   ```

3. Ejecute `.venv\Scripts\python -m dips_audit validar-reglas`. Corrija el error que se muestre antes de auditar.
4. Ejecute `.venv\Scripts\python -m dips_audit benchmark` y revise el cambio frente a la línea base. Si cambió un criterio, ejecute también `.venv\Scripts\python -m pytest`.

La regla y el tipo están activos si no se indica lo contrario. Para desactivar solo una regla, conserve su severidad:

```yaml
intervalo_excedido: {activa: false, severidad: CRITICA}
```

Para desactivar todas las reglas de un tipo, agregue `activo: false` debajo del nombre del tipo y antes de `reglas:`. Una regla desactivada desaparece de los hallazgos. Para volver a activarla, quite `activa: false` o `activo: false`.

## Qué significa cada valor

| Valor en YAML | Resultado que puede producir | Uso |
| --- | --- | --- |
| `CRITICA`, `NO CRITICA`, `REVISAR` | POSIBLE DISCREPANCIA | El auditor debe leer el hallazgo y decidir. Son niveles internos para ordenar hallazgos; hoy los tres dan el mismo resultado visible. |
| `CONSULTAR MANUAL` | REVISAR | El TA o el RIR depende de un dato del manual. |
| `SIN FUENTE` | SIN FUENTE | No hay una fila de referencia con qué revisar el DIP. |
| `OBSERVACION` | No cambia el resultado | Se informa el hallazgo para conocimiento del auditor. |

Si un DIP tiene varios hallazgos, prevalece el de mayor severidad. `REVISAR` **dentro del YAML** produce POSIBLE DISCREPANCIA; para obtener el resultado visible REVISAR se usa `CONSULTAR MANUAL`.

## Dónde se cambia cada cosa

| Necesidad | Archivo |
| --- | --- |
| Activar, desactivar o clasificar un hallazgo existente | `config/discrepancias.yaml` |
| Cambiar una tolerancia (días, horas o uso) | `config/config.yaml` |
| Cambiar TA, Parent Assembly, referencia técnica o RIR de un ítem | `DIPs References.xlsx` |
| Mejorar cómo se reconoce un ítem de la tabla | `config/catalogo_others.yaml` |
| Cambiar cuándo se detecta un hallazgo o agregar una regla | `dips_audit/reglas.py` y módulos relacionados; ver [guía técnica](tecnico.md) |

`validar-reglas` comprueba el formato, valores, códigos repetidos y que todos los códigos configurados existan en el programa. El benchmark muestra el efecto de la configuración en casos ya auditados.
