"""Identificación de squibs y equivalencias de P/N documentadas por ICAM."""

import re

from .texto import extraer_pn


def es_squib(dip: dict, entrada=None) -> bool:
    return bool((entrada is not None and entrada.id.startswith("SQUIB")) or
                re.search(r"\bSQUIBS?\b", dip.get("nombre", ""), re.I))


def clave_pn(pn: str) -> str:
    # Las letras forman parte del P/N; no se aplica la normalización numérica de S/N.
    return re.sub(r"\s+", "", pn).upper()


def verificar_squib(dip: dict) -> str:
    texto = " ".join(dip.get(c) or "" for c in ("nombre", "descripcion", "notas_descripcion"))
    if dip.get("estado") == "COMPLETE":
        texto += " " + (dip.get("accion_correctiva") or "")
    citados = extraer_pn(texto)
    analogos = dip.get("analogos_pn") or {}
    verificados = []
    pendientes = []
    for pn in citados:
        coincide = next((base for base, otros in analogos.items()
                         if clave_pn(pn) in {clave_pn(base), *(clave_pn(p) for p in otros)}), None)
        if coincide:
            verificados.append(pn if clave_pn(pn) == clave_pn(coincide)
                               else f"{pn} (análogo de {coincide} en ICAM)")
        else:
            pendientes.append(pn)
    mensaje = "Squib: se revisa por P/N; el Batch No no es S/N."
    if verificados:
        mensaje += " P/N verificados en ICAM: " + ", ".join(verificados) + "."
    if pendientes or not citados:
        mensaje += " Verificar P/N y análogos" + (": " + ", ".join(pendientes) if pendientes else "")
        mensaje += " en la página de la parte en ICAM."
    return mensaje
