"""Asociación de cada DIP con su entrada del catálogo de referencias."""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from .referencias import Catalogo, EntradaCatalogo, FilaReferencia
from .texto import contiene_frase, normalizar

# Palabras que no aportan para decidir la categoría.
_PALABRAS_VACIAS = {
    "DIP", "DIPS", "MAREP", "OPEN", "A", "THE", "OF", "WITH", "TO", "IN", "ON", "AND",
    "FOR", "IS", "WAS", "FOUND", "DURING", "DUE", "DATE", "LESS", "THAN", "DAYS", "DAY",
    "NEXT", "CHECK", "REF", "REFERENCE", "PER", "IAW", "AT", "BY", "OR", "NOT",
    # español
    "DE", "LA", "EL", "LOS", "LAS", "DEL", "POR", "CON", "EN", "PARA", "UN", "UNA",
    "VENCE", "PROXIMO", "VENCER", "FECHA",
}


# Palabras demasiado genéricas para confirmar que una sugerencia de la IA es
# correcta (p. ej. BATTERY aparece en ELT y en detectores de humo).
_GENERICAS = {
    "BATTERY", "INSPECTION", "INSPECT", "SYSTEM", "ASSY", "ASSEMBLY", "REPLACEMENT",
    "REPLACE", "INDICATION", "LEFT", "RIGHT", "LH", "RH", "FWD", "AFT", "PORTABLE", "CABIN",
    "PASSENGER", "COMPARTMENT", "TASK", "SCHEDULED", "MAINTENANCE", "SHOWS", "SMT", "AHM",
    "SERVICE", "EXPIRE", "EXPIRATION", "DAMAGED", "LOW", "PRESSURE", "CONTROL", "SENSOR",
    "BOX", "UNIT", "PANEL", "DOOR", "ACCESS", "ENGINE", "AIRCRAFT", "EMERGENCY", "KIT",
    "CABLE", "CABLES", "TENSION", "RETENSION", "ADJUSTMENT", "WEIGHT", "BOTTLE", "CHECK",
}


@dataclass(frozen=True)
class ParametrosAsociacion:
    """Ajustes de la asociación con el modelo local (config.yaml, sección llm)."""
    candidatos: int = 6              # referencias candidatas que se le muestran al modelo
    # Un intervalo menor a esta fracción del TA de referencia se considera implausible
    # para validar una sugerencia de la IA (p. ej. 7 días para un TA de 4-6 meses).
    fraccion_minima_ta: float = 0.2

    @classmethod
    def desde_config(cls, c: dict) -> ParametrosAsociacion:
        return cls(candidatos=c.get("candidatos", cls.candidatos),
                   fraccion_minima_ta=c.get("fraccion_minima_ta", cls.fraccion_minima_ta))


@dataclass
class Asociacion:
    entrada: EntradaCatalogo | None
    metodo: str            # REGLAS, IA, AMBIGUA, NINGUNA
    detalle: str = ""
    candidatos: list[str] = field(default_factory=list)
    propuesta: str | None = None  # ID que propuso el modelo, aunque se haya descartado

    @property
    def confianza(self) -> str:
        return {"REGLAS": "ALTA", "IA": "MEDIA"}.get(self.metodo, "BAJA")


def palabras_clave(texto_normalizado: str) -> set[str]:
    return {p for p in texto_normalizado.split()
            if p not in _PALABRAS_VACIAS and not p.isdigit() and len(p) > 1}


def _equivalentes(entradas: list[EntradaCatalogo]) -> bool:
    """True si todas las entradas llevarían a las mismas verificaciones."""
    primera = entradas[0]
    firma = lambda e: (tuple((tuple(v.limites), tuple(v.flotas or [])) for v in e.variantes),
                       e.hasta_vencimiento, frozenset(e.parent_assy))
    return all(firma(e) == firma(primera) for e in entradas[1:])


def _puntaje_palabras(consulta: set[str], texto: set[str]) -> float:
    """Suma, por cada palabra de la consulta, su mejor parecido con una palabra
    del texto (tolera errores de tipeo: BOTLE ~ BOTTLE, HALOM ~ HALON)."""
    total = 0.0
    for q in consulta:
        mejor = max((fuzz.ratio(q, t) for t in texto), default=0)
        if mejor >= 75:
            total += mejor / 100
    return total


def sugerir(nombre_normalizado: str, catalogo: Catalogo, limite: int = 6) -> list[EntradaCatalogo]:
    """Candidatos para el modelo local, ordenados por parecido de palabras."""
    consulta = palabras_clave(nombre_normalizado)
    puntajes = []
    for e in catalogo.entradas:
        texto = palabras_clave(e.texto_busqueda())
        puntajes.append((_puntaje_palabras(consulta, texto),
                         fuzz.token_set_ratio(nombre_normalizado, e.texto_busqueda()), e))
    puntajes.sort(key=lambda x: (-x[0], -x[1]))
    return [e for _, _, e in puntajes[:limite]]


def comparte_palabra_distintiva(nombre_normalizado: str, entrada: EntradaCatalogo) -> bool:
    """True si el Fault Name y la entrada comparten una palabra no genérica
    (con tolerancia a errores de tipeo: FUMIGATON ~ FUMIGATION)."""
    propias = palabras_clave(entrada.texto_busqueda()) - _GENERICAS
    return any(fuzz.ratio(p, q) >= (75 if min(len(p), len(q)) >= 7 else 80)
               for p in palabras_clave(nombre_normalizado) - _GENERICAS
               for q in propias if len(p) > 2 or p == q)


def intervalo_compatible(entrada: EntradaCatalogo, valor: float | None, unidad: str | None,
                         tol_dias: int = 1, fraccion_minima: float = 0.2) -> bool:
    """True si el intervalo del DIP podría corresponder al TA de la entrada.

    Se usa solo para descartar sugerencias de la IA claramente incompatibles
    (p. ej. un DIP de 112 días asociado a una referencia de 30 días).
    """
    if valor is None or unidad is None:
        return True
    if entrada.hasta_vencimiento:
        return unidad == "DAY"
    if not entrada.variantes:
        return True
    for v in entrada.variantes:
        for lim in v.limites:
            if lim.unidad == "MONTH" and unidad == "DAY":
                maximo = lim.valor * 31 + tol_dias
            elif lim.unidad == unidad:
                maximo = lim.valor + (tol_dias if unidad == "DAY" else 0)
            else:
                continue
            if maximo * fraccion_minima <= valor <= maximo:
                return True
    return False


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


def asociar(nombre: str, catalogo: Catalogo, llm=None, intervalo: float | None = None,
            unidad: str | None = None,
            parametros: ParametrosAsociacion = ParametrosAsociacion()) -> Asociacion:
    """Asocia un Fault Name a una entrada del catálogo.

    1) Reglas de palabras clave (confianza ALTA).
    2) Si no hay coincidencia única y hay modelo local: el modelo elige entre
       candidatos cerrados, y la elección se valida con palabras distintivas y
       compatibilidad de intervalo (confianza MEDIA, el DIP queda en REVISAR).
    """
    n = normalizar(nombre)
    coincidencias: list[tuple[EntradaCatalogo, int]] = []
    for e in catalogo.entradas:
        ok, puntaje = e.coincide(n)
        if ok:
            coincidencias.append((e, puntaje))
    coincidencias.sort(key=lambda x: -x[1])

    if coincidencias:
        mejor, puntaje = coincidencias[0]
        empatadas = [e for e, p in coincidencias if p == puntaje]
        if len(empatadas) == 1 or _equivalentes(empatadas):
            return Asociacion(mejor, "REGLAS", candidatos=[e.id for e, _ in coincidencias])
        candidatos = empatadas
    else:
        candidatos = sugerir(n, catalogo, parametros.candidatos)

    if llm is not None:
        texto_intervalo = f"{intervalo:g} {unidad}" if intervalo is not None and unidad else ""
        elegido, justificacion = llm.elegir_categoria(nombre, candidatos, texto_intervalo)
        propuesta = elegido.id if elegido else None
        if elegido is not None:
            excluida = next((x for x in elegido.excluir if contiene_frase(n, x)), None)
            if excluida:
                justificacion = (f"La IA propuso {elegido.id}, pero se descartó: el Fault Name "
                                 f"contiene '{excluida}', excluido para esa referencia.")
            elif not comparte_palabra_distintiva(n, elegido):
                justificacion = (f"La IA propuso {elegido.id}, pero se descartó: no comparte "
                                 f"palabras distintivas con el Fault Name.")
            elif not intervalo_compatible(elegido, intervalo, unidad,
                                          fraccion_minima=parametros.fraccion_minima_ta):
                justificacion = (f"La IA propuso {elegido.id}, pero se descartó: el intervalo "
                                 f"del DIP ({texto_intervalo}) no es compatible con su TA.")
            else:
                return Asociacion(elegido, "IA", detalle=justificacion,
                                  candidatos=[e.id for e in candidatos], propuesta=propuesta)
        return Asociacion(None, "AMBIGUA" if coincidencias else "NINGUNA",
                          detalle=justificacion, candidatos=[e.id for e in candidatos],
                          propuesta=propuesta)

    return Asociacion(None, "AMBIGUA" if coincidencias else "NINGUNA",
                      candidatos=[e.id for e in candidatos])
