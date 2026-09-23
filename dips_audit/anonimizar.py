"""Copia anónima del histórico de auditorías para el benchmark.

Junta en una sola hoja los datos del Excel de entrada y el veredicto del auditor
de una muestra de DIPs Others, sin columnas ni textos con nombres del personal.
"""

from __future__ import annotations

import re
import warnings
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

HOJA = "DIPs"
MARCA = "[PERSONA]"
TIPO_DIP = "Others"
VEREDICTOS = ["OK", "DISCREPANCIA NO CRÍTICA", "DISCREPANCIA CRÍTICA"]
CANTIDAD = 50    # DIPs del benchmark
SEMILLA = 2026   # fija la muestra: la misma semilla da los mismos DIPs
# Datos de entrada sin los cuales el DIP no se puede auditar. Algunos DIPs de la
# hoja Datos del histórico no los tienen, y no se completan desde ICAM porque allí
# ya están corregidos: el benchmark usa lo que vio el auditor.
DATOS_MINIMOS = ["DIP Interval", "Interval Type"]

# Columnas del Excel de entrada, en el orden en que se guardan.
COLUMNAS_ENTRADA = [
    "Fault Barcode", "ATA", "Type DIP", "Fault Name", "DIP Interval", "Interval Type",
    "Fault Status", "Aircraft", "Task Parent Assy", "Fault Severity", "Deferral Reference",
    "Fault Due Date", "Fault Found on Date", "Scheduled Date", "Usage Remaining",
]
CAPTURA = "¿Tiene Captura de Ref. Ténica y/o Adjuntada EC/RA?"
COLUMNAS_VEREDICTO = [
    "AUDIT DATE - Apertura", "STATUS - Apertura", "COMMENTS - Apertura", CAPTURA,
    "AUDIT DATE - Cierre", "STATUS - Cierre", "COMMENTS - Cierre",
]
# Columnas del histórico con nombres o cuentas del personal: no se copian, pero
# se usan para reconocer esos nombres dentro de los comentarios.
COLUMNAS_PERSONAL = ["CUENTA ICAM", "DIFERIDO POR", "AUDITOR - Apertura", "Cerrado por",
                     "AUDITOR - Cierre"]
TEXTOS_LIBRES = ["Fault Name", "COMMENTS - Apertura", "COMMENTS - Cierre"]

# Nombres de pila frecuentes. Permiten reconocer a personas que no figuran en las
# columnas del personal (p. ej. un planificador mencionado en un comentario).
NOMBRES_DE_PILA = set("""
    ABDIEL ABEL ADOLFO ADRIAN ALBERTO ALEJANDRA ALEJANDRO ALEXIS ALFREDO ALICIA ALVARO
    ANA ANDREA ANDRES ANGEL ANGELA ANTONIO ARIEL ARMANDO ARTURO AURORA BEATRIZ BENJAMIN
    BERNARDO BRENDA BRYAN CAMILO CARLA CARLOS CARMEN CAROLINA CATALINA CESAR CRISTIAN
    CRISTINA DANIEL DANIELA DARIO DAVID DIANA DIEGO EDGAR EDSON EDUARDO EDWIN ELENA ELIDIO
    ELIZABETH EMILIO ENRIQUE ERIC ERICK ERNESTO ESTEBAN EVELYN FABIO FELIPE FERNANDO
    FRANCISCO GABRIEL GABRIELA GERARDO GILBERTO GLORIA GONZALO GUILLERMO GUSTAVO HECTOR
    HUGO IGNACIO ISABEL ISMAEL IVAN JAHANGIR JAIME JAVIER JEAN JENNIFER JESSICA JESUS
    JOEL JORGE JOSE JUAN JULIA JULIAN JULIO KAREN KATHERINE KEVIN LAURA LEONARDO LILIANA
    LORENA LUCAS LUCIA LUIS MANUEL MARCO MARCOS MARIA MARIANA MARIO MARTA MARTIN MARYAM
    MAURICIO MAYRA MELISSA MIGUEL MOISES NATALIA NELSON NESTOR NICOLAS OMAR ONESIMO OSCAR
    PABLO PAOLA PASTOR PATRICIA PAULA PEDRO RAFAEL RAMON RAUL RICARDO ROBERTO RODRIGO
    ROSA RUBEN SANDRA SANTIAGO SARA SEBASTIAN SERGIO SILVIA SOFIA TOMAS VALENTINA VANESSA
    VICTOR VIVIANA WILLIAM YESENIA
""".split())
# Siglas y términos técnicos que coinciden con un nombre y nunca se tachan.
_NO_SON_NOMBRES = {"MAX", "APU"}
_MESES = {"JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV",
          "DEC", "ENE", "ABR", "AGO", "DIC"}
_PALABRA = re.compile(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+")


class ErrorAnonimizacion(Exception):
    pass


@dataclass
class Anonimizacion:
    tabla: pd.DataFrame
    nombres_tachados: int       # apariciones de personas reemplazadas por [PERSONA]
    textos_modificados: int     # celdas de texto libre con algún reemplazo


def _sin_acentos(texto: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def _clave(palabra: str) -> str:
    return _sin_acentos(palabra).upper()


def nombres_del_personal(datos: pd.DataFrame) -> set[str]:
    """Palabras (nombres, apellidos y cuentas) de las columnas del personal."""
    palabras: set[str] = set()
    for col in COLUMNAS_PERSONAL:
        if col not in datos:
            continue
        for valor in datos[col].dropna().astype(str):
            palabras |= {_clave(p) for p in _PALABRA.findall(valor)}
    # Palabras cortas y meses (JAN) aparecen en los textos con otro significado.
    return {p for p in palabras if len(p) >= 4 and p not in _MESES}


class Tachador:
    """Reemplaza por [PERSONA] los nombres de personas en un texto libre.

    Una persona empieza en un nombre conocido (del personal o de pila) y sigue con
    las palabras poco comunes que vienen detrás (apellidos): "POR JOEL X Y" ->
    "POR [PERSONA]". Las palabras comunes del corpus cortan la secuencia.
    """

    def __init__(self, personal: set[str], textos: list[str]):
        self.disparadores = (personal | NOMBRES_DE_PILA) - _NO_SON_NOMBRES
        conteo = Counter(_clave(p) for t in textos for p in _PALABRA.findall(t))
        # Palabras de uso general en el histórico (vocabulario técnico y del español).
        self.comunes = {p for p, n in conteo.items() if n > 4} - personal

    def _es_nombre(self, palabra: str) -> bool:
        return palabra in self.disparadores

    def _puede_seguir(self, palabra: str) -> bool:
        return len(palabra) >= 3 and (palabra in self.disparadores
                                      or palabra not in self.comunes)

    @staticmethod
    def _cierra(pieza: str) -> bool:
        """Una palabra seguida de puntuación termina el nombre ("PEREZ, ...")."""
        return pieza != pieza.rstrip(".,;:)")

    def tachar(self, texto: str) -> tuple[str, int]:
        piezas = list(re.finditer(r"\S+", texto))
        salida: list[str] = []
        tachados = 0
        i = 0
        while i < len(piezas):
            palabra = _clave(piezas[i].group(0).strip(".,;:()"))
            if not self._es_nombre(palabra):
                salida.append(piezas[i].group(0))
                i += 1
                continue
            j = i + 1
            # Hasta 3 palabras más (nombre compuesto y dos apellidos).
            while j < len(piezas) and j - i < 4 and not self._cierra(piezas[j - 1].group(0)):
                siguiente = piezas[j].group(0).rstrip(".,;:)")
                if not siguiente.isalpha() or not self._puede_seguir(_clave(siguiente)):
                    break
                j += 1
            final = piezas[j - 1].group(0)
            puntuacion = final[len(final.rstrip(".,;:)")):]
            salida.append(MARCA + puntuacion)
            tachados += 1
            i = j
        return " ".join(salida), tachados


def _fecha_con_hora(fecha: object, hora: object, am_pm: object) -> object:
    """En la hoja Datos la hora de apertura está en dos columnas ('03:55:00', 'PM')."""
    if not isinstance(fecha, (datetime, pd.Timestamp)) or pd.isna(fecha):
        return fecha
    try:
        t = datetime.strptime(f"{str(hora).strip()} {str(am_pm).strip()}", "%I:%M:%S %p")
    except ValueError:
        return fecha
    return pd.Timestamp(fecha).replace(hour=t.hour, minute=t.minute, second=0).to_pydatetime()


def anonimizar(ruta_historico: Path, cantidad: int | None = CANTIDAD,
               semilla: int = SEMILLA) -> Anonimizacion:
    """Arma la tabla del benchmark a partir del histórico (hojas Busqueda y Datos).

    Para los DIPs de Busqueda se usan sus datos de entrada, como en la validación
    original. Los que solo están en Datos toman los datos de entrada de esa hoja.
    Solo quedan DIPs Others con veredicto; `cantidad` = None los deja todos.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            busqueda = pd.read_excel(ruta_historico, sheet_name="Busqueda", dtype=object)
            datos = pd.read_excel(ruta_historico, sheet_name="Datos", dtype=object)
        except ValueError as e:
            raise ErrorAnonimizacion(f"El histórico debe tener las hojas Busqueda y Datos ({e}).")
    datos = datos.dropna(subset=["Fault Barcode"]).drop_duplicates("Fault Barcode")
    busqueda = busqueda.dropna(subset=["Fault Barcode"]).drop_duplicates("Fault Barcode")
    faltantes = [c for c in COLUMNAS_VEREDICTO + ["Fault Barcode"] if c not in datos]
    if faltantes:
        raise ErrorAnonimizacion("Faltan columnas en la hoja Datos: " + ", ".join(faltantes))

    entrada_b = busqueda.rename(columns={"Area": "Type DIP"}).reindex(columns=COLUMNAS_ENTRADA)
    entrada_b["Fuente"] = "Busqueda"
    solo_datos = datos[~datos["Fault Barcode"].isin(busqueda["Fault Barcode"])].copy()
    if {"on", "Date"} <= set(solo_datos.columns):
        solo_datos["Fault Found on Date"] = [
            _fecha_con_hora(f, h, p) for f, h, p in
            zip(solo_datos["Fault Found on Date"], solo_datos["on"], solo_datos["Date"])]
    entrada_d = solo_datos.reindex(columns=COLUMNAS_ENTRADA)
    entrada_d["Fuente"] = "Datos"

    veredictos = datos.set_index("Fault Barcode")[COLUMNAS_VEREDICTO]
    tabla = pd.concat([entrada_b, entrada_d], ignore_index=True)
    tabla = tabla.join(veredictos, on="Fault Barcode")

    personal = nombres_del_personal(datos)
    textos = [str(v) for c in TEXTOS_LIBRES for v in tabla[c].dropna()]
    tachador = Tachador(personal, textos)
    for col in TEXTOS_LIBRES:
        tabla[col] = [tachador.tachar(v)[0] if isinstance(v, str) and v.strip() else v
                      for v in tabla[col]]

    # Se filtra después de tachar: el tachador distingue palabras comunes con todo el corpus.
    tabla = muestrear(tabla, cantidad, semilla)
    textos_finales = [v for c in TEXTOS_LIBRES for v in tabla[c] if isinstance(v, str)]
    tachados = sum(v.count(MARCA) for v in textos_finales)
    modificados = sum(MARCA in v for v in textos_finales)
    restantes = verificar(tabla, personal)
    if restantes:
        raise ErrorAnonimizacion("Quedaron nombres del personal en el texto: "
                                 + "; ".join(restantes[:5]))
    return Anonimizacion(tabla=tabla, nombres_tachados=tachados, textos_modificados=modificados)


def muestrear(tabla: pd.DataFrame, cantidad: int | None, semilla: int = SEMILLA) -> pd.DataFrame:
    """DIPs Others con veredicto del auditor y con los datos mínimos de entrada; si hay
    `cantidad`, una muestra de ese tamaño.

    La muestra respeta la proporción de cada veredicto (OK, no crítica, crítica) y
    siempre es la misma para la misma semilla.
    """
    tipo = tabla["Type DIP"].astype(str).str.strip().str.upper()
    tabla = tabla[(tipo == TIPO_DIP.upper())
                  & tabla["STATUS - Apertura"].isin(VEREDICTOS)
                  & tabla[DATOS_MINIMOS].notna().all(axis=1)].reset_index(drop=True)
    if not cantidad or cantidad >= len(tabla):
        return tabla
    grupos = tabla.groupby("STATUS - Apertura")
    # Reparto proporcional; los lugares sobrantes van a los restos más grandes.
    cuota = grupos.size() * cantidad / len(tabla)
    asignado = cuota.astype(int)
    faltan = cantidad - int(asignado.sum())
    asignado[(cuota - asignado).sort_values(ascending=False).index[:faltan]] += 1
    muestra = pd.concat(g.sample(n=int(asignado[v]), random_state=semilla) for v, g in grupos)
    return muestra.sort_index().reset_index(drop=True)


def verificar(tabla: pd.DataFrame, personal: set[str]) -> list[str]:
    """Textos que todavía contienen una columna o una palabra del personal."""
    problemas = [f"columna {c}" for c in COLUMNAS_PERSONAL if c in tabla.columns]
    for col in tabla.columns:
        for valor in tabla[col].dropna():
            if isinstance(valor, str):
                encontradas = {_clave(p) for p in _PALABRA.findall(valor)} & personal
                if encontradas:
                    problemas.append(f"{col}: {', '.join(sorted(encontradas))}")
    return problemas


def guardar(anon: Anonimizacion, ruta: Path) -> Path:
    from openpyxl.utils import get_column_letter

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(ruta, engine="openpyxl") as w:
        anon.tabla.to_excel(w, sheet_name=HOJA, index=False)
        ws = w.sheets[HOJA]
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = ws.dimensions
        for n, col in enumerate(anon.tabla.columns, start=1):
            ancho = 50 if col in TEXTOS_LIBRES else max(12, min(len(str(col)) + 2, 24))
            ws.column_dimensions[get_column_letter(n)].width = ancho
    return ruta
