# Configurar las reglas

Abra `config/discrepancias.yaml`, cambie la severidad o activación de la regla y guarde. La siguiente auditoría usa los cambios.

```yaml
intervalo_excedido: POSIBLE DISCREPANCIA
```

Para desactivar esa regla:

```yaml
intervalo_excedido: {activa: false, severidad: POSIBLE DISCREPANCIA}
```

Para reactivarla, cambie `false` por `true`. Conserve los códigos y la sangría con espacios.

La [guía rápida de DIPS](Guia_DIPS_reglas_referencias.md) explica los valores, el uso del programa, ICAM, los pendientes y las referencias locales o de SharePoint. También está en [PowerPoint](Guia_DIPS_reglas_referencias.pptx) y [PDF](Guia_DIPS_reglas_referencias.pdf).

| Valor en YAML | Efecto en el resultado |
| --- | --- |
| `POSIBLE DISCREPANCIA` | POSIBLE DISCREPANCIA |
| `REVISAR` | REVISAR: consultar el manual |
| `SIN FUENTE EN DIPS REFERENCES` | SIN FUENTE EN DIPS REFERENCES |
| `OK` | Caso aceptado; el DIP queda OK si no hay otro hallazgo |

Prevalece POSIBLE DISCREPANCIA, después REVISAR y luego SIN FUENTE EN DIPS REFERENCES. Sin hallazgos, o solo con detalles adicionales, el DIP queda OK. En un DIP COMPLETE, una apertura con POSIBLE DISCREPANCIA y un cierre OK produce CORREGIDO EN CIERRE. Si el auditor ya marcó en ICAM el cierre sin discrepancia, el DIP COMPLETE queda OK y los hallazgos del programa siguen visibles. Este último resultado se calcula y no se asigna a una regla.
