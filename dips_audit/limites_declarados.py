"""Lo que el propio DIP dice de su plazo: límites, inspecciones repetitivas y vencimientos.

Muchos DIPs no están en la tabla de referencias (SIN FUENTE), pero su descripción cita la
fuente y el plazo: "open DIP for 45 days or 225 FC", "in no more than 100FH, 50FC or 10 days
whichever occurs first", "detailed visual inspection every 30 days", "inspect within 50 flight
hours and correct within 100 flight hours", "DUE DATE NOVEMBER/2027". Con eso se revisa el T/A
del DIP contra su propia fuente, como lo hace el auditor ("verificar contra la fuente que cita").
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date

from .texto import extraer_fechas, sin_acentos

# Unidad escrita -> DAY, FH, FC, MONTH.
_UNIDAD = {
    "DAY": "DAY", "DAYS": "DAY", "CDY": "DAY",
    "FH": "FH", "FHS": "FH", "FHRS": "FH", "HRS": "FH", "HOURS": "FH", "HOUR": "FH",
    "FLIGHT HOURS": "FH", "FLYING HOURS": "FH", "FLIGHT HOUR": "FH",
    "FC": "FC", "CYCLES": "FC", "CYCLE": "FC", "LANDINGS": "FC", "FLIGHT CYCLES": "FC",
    "MONTHS": "MONTH", "MONTH": "MONTH",
}
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
_UNI = (r"(FLIGHT\s+HOURS?|FLYING\s+HOURS|FLIGHT\s+CYCLES|DAYS|DAY|CDY|FHRS|FHS|FH|HRS|HOURS|HOUR|FC"
        r"|CYCLES|CYCLE|LANDINGS|MONTHS|MONTH)\b")
_UN_LIMITE = _NUM + r"\s*" + _UNI
# Varios límites seguidos: "100FH, 50FC OR 10 DAYS", "45 DAYS OR 225 FC", "25 FH / 10 CYCLES".
_VARIOS = _UN_LIMITE + r"(?:\s*(?:,|OR|/|AND)\s*" + _UN_LIMITE + r")*"
# Plazo del DIP. "NOT PRIOR TO 7 DAYS" (FDR) no es un plazo: es cuándo empieza.
_PLAZO = re.compile(
    r"(?<!NOT )\b(?:WITHIN|IN|FOR|NOT\s+TO\s+EXCEED|NO\s+MORE\s+THAN|PRIOR\s+TO|BEFORE"
    r"|NO\s+LATER\s+THAN|NOT\s+LATER\s+THAN|DUE)\s*:?\s*(?:THE\s+NEXT\s+|A\s+PERIOD\s+OF\s+|NEXT\s+)?"
    + _VARIOS)
# Inspección repetitiva: "EVERY 30 DAYS", "AFTER EACH 400 CYCLES", "EVERY 6,875 FC OR 30 MONTHS".
_REPETITIVO = re.compile(r"\b(?:EVERY|AFTER\s+EACH|REPEAT(?:ED)?\s+EVERY|AT\s+INTERVALS\s+OF)\s*"
                         + _VARIOS)
# "INSPECT WITHIN 50 FH AND CORRECT WITHIN 100 FH": el primero es una inspección (RIR).
_INSPECCIONAR = re.compile(r"\bINSPECT(?:ION)?\s+WITHIN\s+" + _UN_LIMITE + r".{0,40}?\bCORRECT")


@dataclass(frozen=True)
class LimiteDeclarado:
    valor: float
    unidad: str   # DAY, FH, FC, MONTH

    def __str__(self) -> str:
        v = int(self.valor) if float(self.valor).is_integer() else self.valor
        return f"{v} {self.unidad}"


@dataclass
class Declarado:
    """Límites que el texto del DIP declara. Cada grupo son límites alternativos (lo que
    ocurra primero)."""
    plazos: list[tuple[str, list[LimiteDeclarado]]] = field(default_factory=list)
    repetitivos: list[tuple[str, list[LimiteDeclarado]]] = field(default_factory=list)

    @property
    def plazo(self) -> tuple[str, list[LimiteDeclarado]] | None:
        """El grupo de límites del plazo (el que más límites tiene; a igualdad, el primero)."""
        return max(self.plazos, key=lambda g: len(g[1]), default=None)


def _limites(fragmento: str) -> list[LimiteDeclarado]:
    salida = []
    for m in re.finditer(_UN_LIMITE, fragmento):
        numero, unidad = m.group(1), _UNIDAD[re.sub(r"\s+", " ", m.group(2))]
        # "50.000 FC" es cincuenta mil ciclos (punto de miles), no 50.
        if unidad in ("FC", "FH") and re.fullmatch(r"\d{1,3}\.\d{3}", numero):
            numero = numero.replace(".", "")
        salida.append(LimiteDeclarado(float(numero.replace(",", "")), unidad))
    return list(dict.fromkeys(salida))


def extraer_limites(texto: object) -> Declarado:
    t = re.sub(r"\s+", " ", sin_acentos(str(texto or "")).upper())
    t = re.sub(r"\bFLGHT\b", "FLIGHT", t)  # "10 FLGHT CYCLES"
    d = Declarado()
    inspecciones = {m.span() for m in _INSPECCIONAR.finditer(t)}
    for m in _REPETITIVO.finditer(t):
        d.repetitivos.append((m.group(0), _limites(m.group(0))))
    repetidos = [m.span() for m in _REPETITIVO.finditer(t)]
    for m in _PLAZO.finditer(t):
        if any(a <= m.start() < b for a, b in repetidos):
            continue
        if any(a == m.start() - len("INSPECT ") or a <= m.start() < b for a, b in inspecciones):
            # "INSPECT WITHIN 50 FH": es una inspección, no el plazo del DIP.
            d.repetitivos.append((m.group(0), _limites(m.group(0))))
            continue
        d.plazos.append((m.group(0), _limites(m.group(0))))
    return d


# Fecha de vencimiento del ítem: la que sigue a "DUE DATE", "EXPIRE DATE", "HYDRO DATE"...
_VENCE = re.compile(r"\b(?:DUE\s*DATE|DUE|EXPIR\w*(?:\s+DATE)?|EXP\.?\s*DATE|VALID\s+UNTIL|SHELF\s+LIFE"
                    r"(?:\s+EXPIRY)?|(?:NEXT\s+)?HYDRO(?:STATIC)?(?:\s+TEST)?(?:\s+DATE)?|WEIGHT\s+DUE)"
                    r"\b\s*(?:DATE)?\s*[:\-]?\s*(?:OR\s+DUE\s+DATE\s*:?\s*)?(?:LESS\s+THAN\s+\d+\s+DAYS\s*)?\(?")
_MES_ANIO = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{4})\b")   # "11/2029"


def fechas_de_vencimiento(texto: object) -> list[date]:
    """Fechas que el texto da como vencimiento del ítem ('DUE DATE NOVEMBER/2027',
    'EXPIRE DATE 30-SEP-2026', 'DUE DATE 11/2029'). Mes y año = último día del mes."""
    t = re.sub(r"\s+", " ", sin_acentos(str(texto or "")).upper())
    fechas: list[date] = []
    for m in _VENCE.finditer(t):
        despues = t[m.end():m.end() + 22]
        mm = _MES_ANIO.match(despues)
        if mm and 1 <= int(mm.group(1)) <= 12:
            anio, mes = int(mm.group(2)), int(mm.group(1))
            fechas.append(date(anio, mes, calendar.monthrange(anio, mes)[1]))
            continue
        encontradas = extraer_fechas(re.split(r"[.;]| AND | P/N| S/N", despues)[0])
        if encontradas:
            fechas.append(encontradas[0])
    return fechas
