# Carpeta de pruebas

Aquí van los datos de prueba, separados de las auditorías reales.

| Carpeta | Contenido |
| --- | --- |
| `entrada/` | Excel de prueba (por ejemplo `DIPs Audit (23SEP2026).xlsx`) |
| `icam/` | Datos de ICAM de esos DIPs |
| `salidas/` | Resultados, con el prefijo `PRUEBA_` |

Si el Excel está dentro de esta carpeta, `auditar.bat` y `comparar.bat` trabajan en **modo prueba**: leen y guardan los datos de ICAM en `pruebas/icam/`, dejan los resultados en `pruebas/salidas/` y los marcan como PRUEBA en el nombre del archivo y dentro del Excel. Con un Excel de otra carpeta se puede forzar con `--prueba`.

El contenido de esta carpeta no se sube al repositorio: tiene nombres del personal.
