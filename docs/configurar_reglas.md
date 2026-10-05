# Configurar las reglas

Abra `config/discrepancias.yaml`, cambie la severidad o activación de la regla y guarde. La siguiente auditoría usa los cambios.

```yaml
intervalo_excedido: CRITICA
```

Para desactivar esa regla:

```yaml
intervalo_excedido: {activa: false, severidad: CRITICA}
```

Para reactivarla, cambie `false` por `true`. Conserve los códigos y la sangría con espacios.

La [guía rápida de DIPS](Guia_DIPS_reglas_referencias.md) explica los valores, el uso del programa, ICAM, los pendientes y las referencias locales o de SharePoint. También está en [PowerPoint](Guia_DIPS_reglas_referencias.pptx) y [PDF](Guia_DIPS_reglas_referencias.pdf).
