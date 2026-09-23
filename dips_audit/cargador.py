"""Lectura del Excel de entrada y normalización de columnas y fechas."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

import openpyxl
import pandas as pd

from .referencias import normalizar_unidad

# Columna estándar -> nombres aceptados en el Excel (sin distinguir mayúsculas).
COLUMNAS = {
    "barcode": ["Fault Barcode"],
    "ata": ["ATA"],
    "tipo": ["Type DIP", "Area"],
    "nombre": ["Fault Name"],
    "descripcion": ["Fault Description", "Description"],
    "intervalo": ["DIP Interval"],
    "tipo_intervalo": ["Interval Type"],
    "estado": ["Fault Status"],
    "avion": ["Aircraft"],
    "parent_assy": ["Task Parent Assy"],
    "severidad": ["Fault Severity"],
    "deferral_ref": ["Deferral Reference"],
    "due_date": ["Fault Due Date"],
    "found_date": ["Fault Found on Date"],
    "scheduled_date": ["Scheduled Date"],
    "usage_remaining": ["Usage Remaining"],
    "complete_date": ["Completed Date", "Fault Completed Date", "Completion Date"],
}
OBLIGATORIAS = ["barcode", "nombre", "intervalo", "tipo_intervalo", "estado", "avion"]


class ErrorCarga(Exception):
    pass


@dataclass
class Lote:
    ruta: Path
    hoja: str
    fila_encabezado: int
    original: pd.DataFrame          # columnas tal como vienen en el Excel de entrada
    datos: pd.DataFrame             # columnas estándar ya interpretadas
    notas: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Conversión de valores
# --------------------------------------------------------------------------

_FORMATOS_FECHA = [
    "%b/%d/%y %H:%M", "%b/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M",
    "%m/%d/%Y", "%d/%b/%Y", "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
    "%d/%b/%Y %H:%M",
]


def parse_fecha(valor: object) -> datetime | None:
    # pd.NaT es instancia de datetime: se descarta antes de esa comprobación.
    if valor is None or valor is pd.NaT or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, pd.Timestamp):
        return None if pd.isna(valor) else valor.to_pydatetime()
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime.combine(valor, time())
    texto = str(valor).replace("\xa0", " ").strip()
    if not texto:
        return None
    for fmt in _FORMATOS_FECHA:
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


def parse_numero(valor: object) -> float | None:
    if valor is None or isinstance(valor, (datetime, date, time)):
        return None
    if isinstance(valor, (int, float)):
        return None if pd.isna(valor) else float(valor)
    texto = str(valor).replace("\xa0", " ").replace(",", "").strip()
    try:
        return float(texto)
    except ValueError:
        return None


def parse_texto(valor: object) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return str(valor).replace("\xa0", " ").strip()


def flota_de_modelo(texto: str) -> str | None:
    """'Boeing 737-9 MAX9' -> MAX; '737-8V3' -> NG-800; '737-7V3' -> NG-700."""
    t = texto.upper()
    if "MAX" in t:
        return "MAX"
    m = re.search(r"737-(\d)", t)
    if m:
        return {"7": "NG-700", "8": "NG-800", "9": "NG-900"}.get(m.group(1))
    return None


def tipo_parent(texto: str) -> str:
    t = texto.upper()
    if re.search(r"\bENGINE\b|CFM|LEAP", t):
        return "ENGINE"
    if re.search(r"\bAPU\b", t):
        return "APU"
    if "BOEING" in t or re.search(r"\b737\b|737-", t):
        return "AIRCRAFT"
    return "OTRO" if t else ""


# --------------------------------------------------------------------------
# Lectura
# --------------------------------------------------------------------------

def _buscar_encabezado(filas: list[tuple]) -> int | None:
    for i, fila in enumerate(filas[:20]):
        valores = {parse_texto(v).lower() for v in fila}
        if "fault barcode" in valores and "fault name" in valores:
            return i
    return None


def cargar_export(ruta: Path, hoja: str | None = None) -> Lote:
    ruta = Path(ruta)
    wb = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    hojas = [hoja] if hoja else wb.sheetnames
    if hoja and hoja not in wb.sheetnames:
        raise ErrorCarga(f"La hoja '{hoja}' no existe. Hojas: {', '.join(wb.sheetnames)}")
    for nombre in hojas:
        filas = list(wb[nombre].iter_rows(values_only=True))
        i = _buscar_encabezado(filas)
        if i is not None:
            break
    else:
        wb.close()
        raise ErrorCarga("No se encontró una hoja con las columnas 'Fault Barcode' y 'Fault Name'.")
    wb.close()

    encabezado = [parse_texto(v) or f"Columna {n + 1}" for n, v in enumerate(filas[i])]
    # Encabezados repetidos: se numeran para no perder columnas.
    vistos: dict[str, int] = {}
    for n, e in enumerate(encabezado):
        if e in vistos:
            vistos[e] += 1
            encabezado[n] = f"{e} ({vistos[e]})"
        else:
            vistos[e] = 1
    col_barcode = next(n for n, e in enumerate(encabezado) if e.lower() == "fault barcode")
    cuerpo, numeros_fila = [], []
    for n, f in enumerate(filas[i + 1:], start=i + 2):  # n = número de fila en Excel
        f = (list(f) + [None] * len(encabezado))[:len(encabezado)]
        if parse_texto(f[col_barcode]):
            cuerpo.append(f)
            numeros_fila.append(n)
    original = pd.DataFrame(cuerpo, columns=encabezado, index=numeros_fila, dtype=object)

    datos, notas = normalizar_lote(original)
    return Lote(ruta=ruta, hoja=nombre, fila_encabezado=i + 1, original=original,
                datos=datos, notas=notas)


def _mapear_columnas(columnas: list[str]) -> dict[str, str]:
    minusculas = {c.lower().strip(): c for c in columnas}
    mapa = {}
    for estandar, alias in COLUMNAS.items():
        for a in alias:
            if a.lower() in minusculas:
                mapa[estandar] = minusculas[a.lower()]
                break
    return mapa


def normalizar_lote(original: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    mapa = _mapear_columnas(list(original.columns))
    faltantes = [c for c in OBLIGATORIAS if c not in mapa]
    if faltantes:
        raise ErrorCarga("Faltan columnas obligatorias en el Excel: " + ", ".join(
            COLUMNAS[c][0] for c in faltantes))
    notas: list[str] = []
    registros = []
    for fila_excel, fila in original.iterrows():
        def v(col: str) -> object:
            return fila[mapa[col]] if col in mapa else None

        due = parse_fecha(v("due_date"))
        found = parse_fecha(v("found_date"))
        intervalo = parse_numero(v("intervalo"))
        unidad = normalizar_unidad(v("tipo_intervalo"))
        correccion = ""
        # Fechas con día y mes invertidos por la configuración regional de Excel
        # (p. ej. 9-jul guardado como 7-sep). Se corrige solo si el resultado es
        # coherente con el due date.
        if found and due and found.date() > due.date() and found.day <= 12:
            try:
                invertida = found.replace(month=found.day, day=found.month)
            except ValueError:
                invertida = None
            if invertida and invertida <= due:
                correccion = (f"Fecha de apertura corregida de {found:%d-%b-%Y} a "
                              f"{invertida:%d-%b-%Y} (día/mes invertidos en el Excel)")
                found = invertida
        parent = parse_texto(v("parent_assy"))
        ata = parse_numero(v("ata"))
        registros.append({
            "fila": fila_excel,
            "barcode": parse_texto(v("barcode")),
            "ata": int(ata) if ata is not None else None,
            "tipo": parse_texto(v("tipo")),
            "nombre": parse_texto(v("nombre")),
            "descripcion": parse_texto(v("descripcion")),
            "intervalo": intervalo,
            "tipo_intervalo_original": parse_texto(v("tipo_intervalo")),
            "unidad": unidad,
            "estado": parse_texto(v("estado")).upper(),
            "avion": parse_texto(v("avion")),
            "parent_assy": parent,
            "parent_tipo": tipo_parent(parent),
            "severidad": parse_texto(v("severidad")).upper(),
            "deferral_ref": parse_texto(v("deferral_ref")),
            "due_date": due,
            "found_date": found,
            "scheduled_date": parse_fecha(v("scheduled_date")),
            "usage_remaining": parse_numero(v("usage_remaining")),
            "complete_date": parse_fecha(v("complete_date")),
            "correccion_fecha": correccion,
        })
    # dtype=object conserva los None: si no, pandas los vuelve NaT/NaN, que son
    # verdaderos en un if y pasan los controles "is None" de las reglas.
    datos = pd.DataFrame(registros, dtype=object)
    if datos.empty:
        return datos, notas

    # Flota por avión: se toma del parent assy cuando es el avión, y se propaga
    # a los DIPs del mismo avión cuyo parent es un motor.
    flotas: dict[str, str] = {}
    for _, r in datos.iterrows():
        f = flota_de_modelo(r["parent_assy"]) if r["parent_tipo"] == "AIRCRAFT" else None
        if f and r["avion"]:
            flotas.setdefault(r["avion"], f)
    datos["flota"] = [
        (flota_de_modelo(r["parent_assy"]) if r["parent_tipo"] == "AIRCRAFT" else None)
        or flotas.get(r["avion"]) for _, r in datos.iterrows()
    ]
    corregidas = int((datos["correccion_fecha"] != "").sum())
    if corregidas:
        notas.append(f"{corregidas} fecha(s) de apertura con día/mes invertidos fueron corregidas.")
    if "complete_date" not in mapa:
        notas.append("El Excel no trae fecha de cierre: no se puede verificar si los DIPs "
                     "COMPLETE se cerraron dentro del plazo.")
    if "descripcion" not in mapa:
        notas.append("El Excel no trae la descripción larga: la búsqueda de S/N y referencias "
                     "técnicas se hace solo sobre el Fault Name.")
    return datos, notas
