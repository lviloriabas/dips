"""Asociación de cada DIP con su entrada del catálogo de referencias."""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .referencias import Catalogo, EntradaCatalogo, FilaReferencia
from .texto import normalizar

# Palabras que no aportan para decidir la categoría.
_PALABRAS_VACIAS = {
    "DIP", "DIPS", "MAREP", "OPEN", "A", "THE", "OF", "WITH", "TO", "IN", "ON", "AND",
    "FOR", "IS", "WAS", "FOUND", "DURING", "DUE", "DATE", "LESS", "THAN", "DAYS", "DAY",
    "NEXT", "CHECK", "REF", "REFERENCE", "PER", "IAW", "AT", "BY", "OR", "NOT",
    # español
    "DE", "LA", "EL", "LOS", "LAS", "DEL", "POR", "CON", "EN", "PARA", "UN", "UNA",
    "VENCE", "PROXIMO", "VENCER", "FECHA",
}


@dataclass
class Asociacion:
    entrada: EntradaCatalogo | None
    metodo: str            # REGLAS, REF_TECNICA, AMBIGUA, NINGUNA
    detalle: str = ""
    candidatos: list[str] = field(default_factory=list)

    @property
    def confianza(self) -> str:
        return {"REGLAS": "ALTA", "REF_TECNICA": "ALTA"}.get(self.metodo, "BAJA")


def palabras_clave(texto_normalizado: str) -> set[str]:
    return {p for p in texto_normalizado.split()
            if p not in _PALABRAS_VACIAS and not p.isdigit() and len(p) > 1}


def _equivalentes(entradas: list[EntradaCatalogo]) -> bool:
    """True si todas las entradas llevarían a las mismas verificaciones."""
    primera = entradas[0]
    firma = lambda e: (tuple((tuple(v.limites), tuple(v.flotas or [])) for v in e.variantes),
                       e.hasta_vencimiento, frozenset(e.parent_assy))
    return all(firma(e) == firma(primera) for e in entradas[1:])


def _palabra_parecida(a: str, b: str) -> bool:
    """Igual, o con un error de escritura en palabras de 5 letras o más (FUNIGATION ~ FUMIGATION).
    En palabras cortas y siglas un cambio de letra es otra palabra (ELT/EMK)."""
    return a == b or (min(len(a), len(b)) >= 5 and fuzz.ratio(a, b) >= 85)


def _frase_aproximada(palabras: list[str], frase: str) -> tuple[str, str] | None:
    """(texto encontrado, frase) si la frase aparece con errores de escritura, o None."""
    f = normalizar(frase).split()
    for i in range(len(palabras) - len(f) + 1):
        tramo = palabras[i:i + len(f)]
        if f and all(_palabra_parecida(p, q) for p, q in zip(tramo, f)):
            return " ".join(tramo), " ".join(f)
    return None


def coincide_aproximado(entrada: EntradaCatalogo, nombre_normalizado: str
                        ) -> tuple[int, list[tuple[str, str]]] | None:
    """Como EntradaCatalogo.coincide, tolerando errores de escritura. Devuelve
    (puntaje, [(texto del DIP, frase del catálogo) que no son idénticas]) o None."""
    palabras = nombre_normalizado.split()
    if any(_frase_aproximada(palabras, x) for x in entrada.excluir):
        return None
    puntaje, distintas = 0, []
    for grupo in entrada.requiere:
        encontradas = [(f, m) for f in grupo if (m := _frase_aproximada(palabras, f))]
        if not encontradas:
            return None
        frase, (texto, normal) = max(encontradas, key=lambda x: len(normalizar(x[0])))
        puntaje += 100 + len(normalizar(frase))
        if texto != normal:
            distintas.append((texto, normal))
    return puntaje, distintas


def similares_en_tabla(nombre: str, catalogo: Catalogo, limite: int = 2, umbral: float = 70
                       ) -> list[tuple[FilaReferencia, float]]:
    """Filas de DIPs References (de cualquier tipo) parecidas al Fault Name.

    Solo es una pista para el auditor: sirve para detectar DIPs abiertos con un
    Type DIP distinto al de la tabla (p. ej. un ítem de Powerplant en Others).
    """
    clave = " ".join(sorted(palabras_clave(normalizar(nombre))))
    if not clave:
        return []
    opciones = {i: " ".join(sorted(palabras_clave(normalizar(r.descripcion))))
                for i, r in enumerate(catalogo.referencias)}
    resultado = process.extract(clave, opciones, scorer=fuzz.token_set_ratio, limit=limite,
                                score_cutoff=umbral)
    return [(catalogo.referencias[i], puntaje) for _, puntaje, i in resultado]


def asociar(nombre: str, catalogo: Catalogo) -> Asociacion:
    """Asocia un Fault Name a una entrada del catálogo por reglas de palabras clave
    (confianza ALTA). Sin coincidencia única, el DIP queda sin referencia."""
    n = normalizar(nombre)
    coincidencias: list[tuple[EntradaCatalogo, int]] = []
    for e in catalogo.entradas:
        ok, puntaje = e.coincide(n)
        if ok:
            coincidencias.append((e, puntaje))
    coincidencias.sort(key=lambda x: -x[1])

    if not coincidencias:
        # Mismas palabras clave, tolerando errores de escritura. Se acepta solo si una única
        # entrada (o entradas equivalentes) coincide: es tan exigente como la exacta.
        aproximadas = [(e, r) for e in catalogo.entradas
                       if (r := coincide_aproximado(e, n)) is not None]
        if aproximadas:
            mejor = max(p for _, (p, _) in aproximadas)
            empatadas = [(e, r) for e, r in aproximadas if r[0] == mejor]
            if len(empatadas) == 1 or _equivalentes([e for e, _ in empatadas]):
                e, (_, distintas) = empatadas[0]
                detalle = ", ".join(f"'{t}' se leyó como '{f}'" for t, f in distintas) + "."
                return Asociacion(e, "REGLAS", detalle=detalle,
                                  candidatos=[x.id for x, _ in aproximadas])
        return Asociacion(None, "NINGUNA")

    mejor, puntaje = coincidencias[0]
    empatadas = [e for e, p in coincidencias if p == puntaje]
    if len(empatadas) == 1 or _equivalentes(empatadas):
        return Asociacion(mejor, "REGLAS", candidatos=[e.id for e, _ in coincidencias])
    return Asociacion(None, "AMBIGUA", candidatos=[e.id for e in empatadas])
