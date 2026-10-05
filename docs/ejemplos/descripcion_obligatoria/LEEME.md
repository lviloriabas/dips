# Integración de descripcion_obligatoria

Estos archivos son ejemplos. Generarlos no activa un chequeo.
El criterio y sus excepciones requieren revisión antes de usarlos en auditoría.

1. Copiar la función de `regla.py.txt` a `dips_audit/reglas.py`.
   Si necesita datos de ICAM, una referencia asociada o varios DIPs,
   adaptar la función y su lugar de ejecución con quien mantiene el sistema.
2. Dentro de `auditar_dip`, antes de `return r`, agregar:

   ```python
   regla_descripcion_obligatoria(dip, ctx, r)
   ```

3. Integrar `discrepancias.yaml.txt` en `config/discrepancias.yaml`.
   Conservar el bloque `tipos:` existente. Si `Datos requeridos` ya existe,
   incorporar solo `descripcion_obligatoria: OBSERVACION` debajo de sus `reglas:`.
4. Es de apertura: no agregar el código a `CODIGOS_CIERRE`.
5. Copiar `prueba.py.txt` a `tests/test_descripcion_obligatoria.py`.
6. Desde la raíz de DIPS, ejecutar:

   ```bat
   .venv\Scripts\python -m dips_audit validar-reglas
   .venv\Scripts\python -m pytest
   .venv\Scripts\python -m dips_audit benchmark
   ```

La prueba llama al flujo real `auditar_dip`: fallará si falta la conexión.
Agregar casos para dato no disponible y para las excepciones del criterio.
Revisar también un DIP de muestra con y sin el dato antes de publicar el cambio.
El generador cubre campo vacío y texto ausente. Comparaciones de fechas,
límites, referencias o varios DIPs necesitan una implementación específica.
