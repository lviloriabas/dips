"""Inventario de oxygen generators: el PDF que se adjunta a los DIPs de generators.

Es un formulario (Word -> PDF) con una fila por posición (ASU, LSU/LAV, PSU): Position, PN,
SN, Manufac. Date, Exp. Date y DIP Barcode. Los datos están en los campos del formulario,
no en el texto de la página: "SNRow4" = "BEFA-F016-171", "Exp DateRow4" = "01-2029",
"DIP BarcodeRow4" = "T40S009JAH7"; en las PSU la fila es la posición ("SN1EF 1DEF",
"_2" el segundo generator de la PSU). El vencimiento del generator es el último día del mes
de Exp. Date: con él se audita el due date del DIP.
"""

from __future__ import annotations

import calendar
import io
import re
from dataclasses import dataclass
from datetime import date

from .texto import clave_sn, extraer_fechas, extraer_sn, sin_acentos

# Prefijo del nombre del campo -> columna. Los más largos primero ("POSITION" antes que "PN").
_COLUMNAS = [("MANUFAC DATE", "fabricacion"), ("EXP DATE", "vence"), ("DIP BARCODE", "dip"),
             ("POSITION", "posicion"), ("PN", "pn"), ("SN", "sn")]
_VACIOS = {"", "X", "N/A", "NA", "-", "--"}
_MES_ANIO = re.compile(r"^(\d{1,2})\s*[/\-. ]\s*(\d{4})$")   # 01/2029, 01-2029


@dataclass(frozen=True)
class Generador:
    posicion: str
    pn: str
    sn: str
    vence: date | None    # último día del mes de Exp. Date
    vence_texto: str      # tal como está en el PDF
    dip: str              # DIP Barcode del PDF ("" si N/A)


def leer_campos_pdf(datos: bytes) -> dict[str, str]:
    """Campos del formulario del PDF que tienen valor."""
    from pypdf import PdfReader

    campos = PdfReader(io.BytesIO(datos)).get_fields() or {}
    salida = {}
    for nombre, campo in campos.items():
        valor = campo.get("/V")
        if valor is not None and str(valor).strip():
            salida[str(nombre)] = str(valor).strip()
    return salida


def fecha_de_vencimiento(texto: str) -> date | None:
    """'01/2029' o '01-2029' -> 31-ENE-2029; también '31-JAN-2029', 'JAN-2029'."""
    t = texto.strip().upper()
    m = _MES_ANIO.match(t)
    if m and 1 <= int(m.group(1)) <= 12:
        anio, mes = int(m.group(2)), int(m.group(1))
        return date(anio, mes, calendar.monthrange(anio, mes)[1])
    fechas = extraer_fechas(t)
    return fechas[0] if fechas else None


def _columna(nombre: str) -> tuple[str, str] | None:
    """('vence', 'Row4') para 'Exp DateRow4'."""
    n = re.sub(r"\s+", " ", sin_acentos(nombre)).upper()
    for prefijo, columna in _COLUMNAS:
        if n.startswith(prefijo):
            return columna, n[len(prefijo):].strip()
    return None


def leer_inventario(campos: dict[str, str]) -> list[Generador]:
    """Generators del formulario. Una fila sin S/N (vacía, X o N/A) no cuenta."""
    filas: dict[str, dict[str, str]] = {}
    for nombre, valor in campos.items():
        col = _columna(nombre)
        if col:
            filas.setdefault(col[1], {})[col[0]] = str(valor).strip()
    salida = []
    for clave, f in filas.items():
        sn = f.get("sn", "")
        if sn.upper() in _VACIOS:
            continue
        vence = f.get("vence", "")
        dip = f.get("dip", "")
        posicion = f.get("posicion") or re.sub(r"_\d+$", "", clave).strip()
        salida.append(Generador(posicion=posicion, pn=f.get("pn", ""), sn=sn,
                                vence=fecha_de_vencimiento(vence), vence_texto=vence,
                                dip="" if dip.upper() in _VACIOS else dip.upper()))
    return salida


def es_inventario(generadores: list[Generador]) -> bool:
    return any(g.vence for g in generadores)


@dataclass
class CruceInventario:
    generadores: list[Generador]    # los del DIP: por DIP Barcode o por S/N de la descripción
    sn_fuera: list[str]             # S/N de la descripción que no están en el PDF

    @property
    def vence(self) -> date | None:
        fechas = [g.vence for g in self.generadores if g.vence]
        return min(fechas) if fechas else None

    @property
    def primero(self) -> Generador | None:
        con_fecha = [g for g in self.generadores if g.vence]
        return min(con_fecha, key=lambda g: g.vence) if con_fecha else None


def _sn_exacto(sn: str) -> str:
    """El S/N con sus letras, sin guiones ni espacios: BEEE-F020-166 y BEED-F020-166 son
    dos generators con los mismos dígitos."""
    return re.sub(r"[^A-Z0-9]", "", sin_acentos(str(sn or "")).upper())


def cruzar(inventario: list[Generador], barcode: str, texto: str) -> CruceInventario:
    """Generators del DIP en el inventario: los que tienen su barcode en DIP Barcode y los
    que tienen un S/N que menciona el DIP. El S/N se compara con sus letras; solo si así no
    está en el PDF se compara por los dígitos (escrito sin el prefijo)."""
    sn_dip = list(dict.fromkeys(extraer_sn(texto)))
    exactos = {_sn_exacto(g.sn) for g in inventario}
    del_dip, claves, sn_fuera = set(), set(), []
    for sn in sn_dip:
        if _sn_exacto(sn) in exactos:
            del_dip.add(_sn_exacto(sn))
        elif clave_sn(sn) and any(clave_sn(g.sn) == clave_sn(sn) for g in inventario):
            claves.add(clave_sn(sn))
        else:
            sn_fuera.append(sn)
    barcode = (barcode or "").upper()
    propios = [g for g in inventario
               if (barcode and g.dip == barcode) or _sn_exacto(g.sn) in del_dip
               or clave_sn(g.sn) in claves]
    return CruceInventario(generadores=list(dict.fromkeys(propios)), sn_fuera=sn_fuera)
