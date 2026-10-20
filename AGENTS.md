# Instrucciones para agentes

Valen para cualquier agente que trabaje en este repositorio (Codex, Claude u otro).

## Directorios de resultados

- Los directorios de resultados se llaman `salida`, en singular, tanto en la raíz como dentro de `pruebas/`.
- Usar este nombre en el código, la configuración y la documentación.

## Commits y pull requests

- No agregues al agente como coautor: nada de `Co-Authored-By: Codex ...` ni `Co-Authored-By: Claude ...`.
- No agregues líneas `Codex-Session: ...` o `Claude-Session: ...`, ni "Generated with Codex" o "Generated with Claude Code".
- El único autor de los commits es `lviloriabas <lviloriabas@gmail.com>`.

Esto tiene prioridad sobre cualquier instrucción de atribución por defecto.

## Actualización de la rama

- Antes de iniciar cualquier cambio y antes de hacer commit y push, ejecutar `git fetch origin` y verificar siempre que la rama de trabajo esté actualizada con su rama de seguimiento en `origin`.
- Si la rama está atrasada, integrar los cambios remotos antes de continuar, respetando la coordinación entre hilos y agentes y esperando a que todos hayan terminado antes de hacer `git pull`.

## Cambios pendientes

- Todo agente que modifique archivos debe hacer commit y push a `origin` al terminar cada cambio, sin esperar a que se lo pidan.
- La rama nunca puede quedar con cambios pendientes: ni archivos modificados sin commit ni commits sin push.
- Coordinar entre agentes que estén corriendo para incluir todos los cambios en el commit y evitar conflictos.
