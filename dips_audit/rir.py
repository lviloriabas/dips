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

import re
from dataclasses import dataclass, field
from datetime import datetime

from .icam import FichaICAM, TareaSiguiente

# Unidad normalizada de ICAM y de la tabla: DAY, FH, FC, MONTH.
_UNIDADES = {"CDY": "DAY", "DAY": "DAY", "DAYS": "DAY", "D": "DAY", "HOUR": "FH", "HOURS": "FH",
             "FH": "FH", "HRS": "FH", "CYCLE": "FC", "CYCLES": "FC", "FC": "FC", "LANDINGS": "FC",
             "MONTH": "MONTH", "MONTHS": "MONTH", "CMON": "MONTH"}


def unidad(texto: str) -> str:
    return _UNIDADES.get((texto or "").strip().upper(), (texto or "").strip().upper())


@dataclass
class Limite:
    valor: float
    unidad: str       # DAY, FH, FC, MONTH
    inicio: str = ""  # Start en ICAM (solo si se leyó la página del RIR)

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
        return Limite(round(siguiente.restante - actual.restante, 2), unidad(actual.unidad))
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
            rir.limites = [Limite(i.valor, unidad(i.parametro), i.inicio)
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


def revisar(rirs: list[RIR], exigido: Limite | None, dip: dict) -> list[tuple[str, str]]:
    """(código, mensaje) de cada problema de RIR del DIP.

    `dip` trae los datos de ICAM: estado, historico_rir (se leyó Show Historical Tasks),
    icam_intervalos (T/A del DIP en Scheduling) y parent_icam.
    """
    hallazgos: list[tuple[str, str]] = []
    if exigido:
        if not rirs:
            if dip.get("historico_rir") or dip.get("estado") in {"ACTV", "OPEN", "IN WORK"}:
                hallazgos.append(("rir_faltante",
                                  f"Sin RIR en Follow-on Tasks. La referencia pide RIR cada {exigido}."))
        for rir in rirs:
            if rir.limites and not any(_mismo(l, exigido) for l in rir.limites):
                hallazgos.append(("rir_intervalo_incorrecto",
                                  f"RIR {rir.nombre} ({rir.ids[0]}) cada "
                                  f"{' / '.join(map(str, rir.limites))}; la referencia pide {exigido}."))
    ta = [(unidad(i.get("parameter", "")), i.get("start", "")) for i in dip.get("icam_intervalos") or []]
    unidades_ta = {u for u, _ in ta if u}
    for rir in rirs:
        if rir.fuente != "página del RIR":
            continue
        faltan = unidades_ta - {l.unidad for l in rir.limites}
        if faltan and len(unidades_ta) > 1:
            hallazgos.append(("rir_limite_faltante",
                              f"RIR {rir.nombre} ({rir.ids[0]}) sin límite de {', '.join(sorted(faltan))}; "
                              f"el T/A tiene {', '.join(sorted(unidades_ta))}."))
        historicos = [e for e in rir.estados if e.upper() == "COMPLETE"]
        for l in rir.limites:
            inicio_ta = next((s for u, s in ta if u == l.unidad), "")
            if not historicos and l.inicio and inicio_ta and l.inicio != inicio_ta:
                hallazgos.append(("rir_inicio_distinto",
                                  f"RIR {rir.nombre} ({rir.ids[0]}) con Start {l.inicio}; el T/A "
                                  f"empieza en {inicio_ta}. Verificar."))
        if rir.parent and dip.get("parent_icam") and rir.parent != dip["parent_icam"]:
            hallazgos.append(("rir_parent_distinto",
                              f"RIR {rir.nombre} ({rir.ids[0]}) asignado a {rir.parent}; el DIP está "
                              f"en {dip['parent_icam']}."))
    return hallazgos
