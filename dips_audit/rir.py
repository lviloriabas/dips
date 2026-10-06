"""RIR (inspecciones repetitivas) del DIP: cómo están en ICAM y qué se revisa.

En ICAM los RIR son Follow-on Tasks del DIP, de clase ADHOC. Cada RIR aparece como la
tarea vigente (ACTV) y la siguiente (FORECAST); el intervalo es la diferencia entre sus
Due (594 -> 1394 CYCLES = 800 FC; 02-OCT -> 16-OCT = 14 DAY). Si se leyó la página del RIR,
su Scheduling da el intervalo, el Start y los límites exactos.

Reglas (criterios de los auditores en el histórico):
  - La referencia pide RIR y el DIP no tiene: rir_faltante.
  - Intervalo del RIR distinto del de la referencia: rir_intervalo_incorrecto.
  - El T/A tiene límites que el RIR no tiene (p. ej. CYCLES y CDY): rir_limite_faltante.
  - El RIR no empieza donde empieza el T/A: rir_inicio_distinto.
  - RIR asignado a otro Parent Assembly (avión en vez de motor): rir_parent_distinto.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from .icam import FichaICAM, TareaSiguiente
from .texto import normalizar

# Unidad normalizada de ICAM y de la tabla: DAY, FH, FC, MONTH.
_UNIDADES = {"CDY": "DAY", "DAY": "DAY", "DAYS": "DAY", "D": "DAY", "HOUR": "FH", "HOURS": "FH",
             "FH": "FH", "HRS": "FH", "CYCLE": "FC", "CYCLES": "FC", "FC": "FC", "LANDINGS": "FC",
             "MONTH": "MONTH", "MONTHS": "MONTH", "CMON": "MONTH"}


def solo_rir(dip: dict) -> bool:
    """Los DIPs que mencionan boroscope/borescope se siguen solo por RIR, sin T/A."""
    texto = " ".join(normalizar(dip.get(c)) for c in
                     ("nombre", "descripcion", "notas_descripcion"))
    return bool(re.search(r"\bBOR[OE]SCOP\w*\b", texto))


def unidad(texto: str) -> str:
    return _UNIDADES.get((texto or "").strip().upper(), (texto or "").strip().upper())


@dataclass
class Limite:
    valor: float
    unidad: str       # DAY, FH, FC, MONTH
    inicio: str = ""  # Start en ICAM (solo si se leyó la página del RIR)
    restante: float | None = None  # Usage Remaining de este límite, en la misma unidad

    def __str__(self) -> str:
        v = int(self.valor) if float(self.valor).is_integer() else round(self.valor, 2)
        return f"{v} {self.unidad}"


@dataclass
class RIR:
    nombre: str
    ids: list[str]
    estados: list[str]
    limites: list[Limite] = field(default_factory=list)   # intervalo(s) del RIR
    fuente: str = ""            # "página del RIR" o "ACTV/FORECAST"
    parent: str = ""            # Parent Assembly del RIR (página del RIR)

    def __str__(self) -> str:
        intervalo = " / ".join(map(str, self.limites)) or "intervalo sin dato"
        return f"{self.nombre} ({', '.join(self.ids)}): {intervalo}"


def _fecha(texto: str) -> datetime | None:
    m = re.search(r"\d{2}-[A-Z]{3}-\d{4}", texto or "")
    return datetime.strptime(m.group(0), "%d-%b-%Y") if m else None


def _intervalo_por_due(actual: TareaSiguiente, siguiente: TareaSiguiente) -> Limite | None:
    """Intervalo entre la tarea vigente y la siguiente."""
    if (actual.restante is not None and siguiente.restante is not None
            and actual.unidad == siguiente.unidad and actual.unidad):
        return Limite(round(siguiente.restante - actual.restante, 2), unidad(actual.unidad),
                      restante=actual.restante)
    a, b = _fecha(actual.fecha), _fecha(siguiente.fecha)
    if a and b and not actual.unidad and not siguiente.unidad:
        return Limite((b - a).days, "DAY")
    return None


def agrupar(tareas: list[TareaSiguiente], detalles: dict[str, FichaICAM] | None = None) -> list[RIR]:
    """RIR del DIP a partir de sus Follow-on Tasks (y de la página de cada RIR, si se leyó)."""
    detalles = detalles or {}
    por_nombre: dict[str, list[TareaSiguiente]] = {}
    for t in tareas:
        if t.es_rir:
            por_nombre.setdefault(t.nombre, []).append(t)
    rirs = []
    for nombre, grupo in por_nombre.items():
        rir = RIR(nombre, [t.id for t in grupo], [t.estado for t in grupo])
        detalle = next((detalles[t.id] for t in grupo if t.id in detalles), None)
        if detalle and detalle.intervalos:
            rir.limites = [Limite(i.valor, unidad(i.parametro), i.inicio, _restante(i.restante))
                           for i in detalle.intervalos if i.valor is not None]
            rir.parent = detalle.parent_assembly
            rir.fuente = "página del RIR"
        if not rir.limites:
            actual = next((t for t in grupo if t.estado.upper() == "ACTV"), None)
            siguiente = next((t for t in grupo if t.estado.upper() == "FORECAST"), None)
            limite = _intervalo_por_due(actual, siguiente) if actual and siguiente else None
            if limite:
                rir.limites, rir.fuente = [limite], "ACTV/FORECAST"
        rirs.append(rir)
    return rirs


def _restante(texto: str) -> float | None:
    m = re.fullmatch(r"(-?[\d.,]+)(?:\s+[A-Z]+)?", (texto or "").strip(), re.I)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def remanentes_inverosimiles(rirs: list[RIR]) -> list[str]:
    """Valores claramente fuera del intervalo; una demora pequeña puede ser real."""
    mensajes = []
    for rir in rirs:
        for limite in rir.limites:
            restante, intervalo = limite.restante, limite.valor
            if restante is None or not math.isfinite(intervalo) or intervalo <= 0:
                continue
            if (not math.isfinite(restante) or restante < -max(5, intervalo)
                    or restante > intervalo + max(5, intervalo * 0.1)):
                mensajes.append(f"RIR {rir.ids[0]} Usage Remaining {restante:g} {limite.unidad}, "
                                f"fuera del rango esperable para un intervalo de {limite} "
                                f"({rir.fuente or 'ICAM'}). Verificar configuración en ICAM.")
    return list(dict.fromkeys(mensajes))


def requerido(texto_rir: str) -> Limite | None:
    """RIR que pide la tabla ('1 DAY', '100 FH', 'INSPECT WITHIN 50 FH')."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(DAYS?|FH|FC|HOURS?|CYCLES?|MONTHS?)", (texto_rir or "").upper())
    return Limite(float(m.group(1)), unidad(m.group(2))) if m else None


def _mismo(a: Limite, b: Limite, tol_dias: int = 1) -> bool:
    """Mismo intervalo. Meses contra días: n meses = entre 30n y 31n días (± tolerancia)."""
    if {a.unidad, b.unidad} == {"MONTH", "DAY"}:
        meses, dias = (a, b) if a.unidad == "MONTH" else (b, a)
        return meses.valor * 30 - tol_dias <= dias.valor <= meses.valor * 31 + tol_dias
    return a.unidad == b.unidad and abs(a.valor - b.valor) <= 0.01


def _mismo_inicio(a: str, b: str) -> bool:
    """Mismo Start, salvo redondeo: 'Aircraft 50890.3' y 'Aircraft 50890.29'."""
    if a == b:
        return True
    na, nb = (re.findall(r"-?\d+(?:\.\d+)?", x) for x in (a, b))
    fechas = (re.findall(r"\d{2}-[A-Z]{3}-\d{4}", a), re.findall(r"\d{2}-[A-Z]{3}-\d{4}", b))
    if fechas[0] or fechas[1]:
        return fechas[0] == fechas[1]
    return len(na) == len(nb) and all(abs(float(x) - float(y)) <= 0.05 for x, y in zip(na, nb))


def revisar(rirs: list[RIR], exigido: Limite | None, dip: dict) -> list[tuple[str, str]]:
    """(código, mensaje) de cada problema de RIR del DIP.

    `dip` trae los datos de ICAM: estado, historico_rir (se leyó Show Historical Tasks),
    icam_intervalos (T/A del DIP en Scheduling) y parent_icam.
    """
    hallazgos: list[tuple[str, str]] = []
    sin_ta = solo_rir(dip)
    if (exigido or sin_ta) and not rirs:
        if dip.get("historico_rir") or dip.get("estado") in {"ACTV", "OPEN", "IN WORK"}:
            hallazgos.append(("rir_faltante",
                              f"Sin RIR; la referencia pide RIR cada {exigido}." if exigido
                              else "DIP de boroscope sin RIR; se sigue solo por RIR, sin T/A."))
    if exigido:
        for rir in rirs:
            if rir.limites and not any(_mismo(l, exigido) for l in rir.limites):
                # Más seguido que lo que pide la referencia (cada 1 día en vez de 2) es más
                # conservador: se anota, pero no es discrepancia.
                menor = all(l.unidad == exigido.unidad and l.valor < exigido.valor for l in rir.limites)
                hallazgos.append(("rir_intervalo_menor" if menor else "rir_intervalo_incorrecto",
                                  f"RIR {rir.ids[0]} cada "
                                  f"{' / '.join(map(str, rir.limites))}; la referencia pide {exigido}."))
    ta = [] if sin_ta else [(unidad(i.get("parameter", "")), i.get("start", ""))
                            for i in dip.get("icam_intervalos") or []]
    unidades_ta = {u for u, _ in ta if u}
    for rir in rirs:
        if rir.fuente != "página del RIR":
            continue
        faltan = unidades_ta - {l.unidad for l in rir.limites}
        if faltan and len(unidades_ta) > 1:
            hallazgos.append(("rir_limite_faltante",
                              f"RIR {rir.ids[0]} sin límite de {', '.join(sorted(faltan))}; "
                              f"el T/A tiene {', '.join(sorted(unidades_ta))}."))
        historicos = [e for e in rir.estados if e.upper() == "COMPLETE"]
        for l in rir.limites:
            inicio_ta = next((s for u, s in ta if u == l.unidad), "")
            if not historicos and l.inicio and inicio_ta and not _mismo_inicio(l.inicio, inicio_ta):
                hallazgos.append(("rir_inicio_distinto",
                                  f"RIR {rir.ids[0]} con Start {l.inicio}; el T/A "
                                  f"empieza en {inicio_ta}. Verificar."))
        if rir.parent and dip.get("parent_icam") and rir.parent != dip["parent_icam"]:
            hallazgos.append(("rir_parent_distinto",
                              f"RIR {rir.ids[0]} asignado a {rir.parent}; el DIP está "
                              f"en {dip['parent_icam']}."))
    return hallazgos
