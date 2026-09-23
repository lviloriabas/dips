"""Compara el resultado del auditor contra las auditorías humanas del histórico."""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .auditor import Auditor, ResultadoAuditoria
from .cargador import cargar_export, parse_fecha

ESTADOS_HUMANOS = ["OK", "DISCREPANCIA NO CRÍTICA", "DISCREPANCIA CRÍTICA"]
ESTADOS_IA = ["OK", "REVISAR", "DISCREPANCIA NO CRÍTICA", "DISCREPANCIA CRÍTICA"]
# Temas de los comentarios humanos (en orden de prioridad). Los primeros dependen
# de información que no viene en el Excel de ICAM (attachments, RIRs, tarjetas).
TEMAS = [
    ("Attachments / ref. técnica", re.compile(r"ATTACHMENT|ADJUNT|REFERENCIA T|CAPTURA", re.I)),
    ("RIR", re.compile(r"\bRIR", re.I)),
    ("S/N", re.compile(r"S/N|\bSN\b", re.I)),
    ("Duplicado / por error", re.compile(r"DUPLICAD|MISTAKE|POR ERROR", re.I)),
    ("Intervalo / due date", re.compile(r"T/A|INTERVAL|FECHA|DEBE SER|DEBE TENER|DAY|FH|FC", re.I)),
]
_NO_DETECTABLE = {"Attachments / ref. técnica", "RIR"}


def tema(comentario: object) -> str:
    texto = "" if comentario is None or (isinstance(comentario, float)) else str(comentario)
    if not texto.strip():
        return "Sin comentario"
    for nombre, patron in TEMAS:
        if patron.search(texto):
            return nombre
    return "Otro"


@dataclass
class Evaluacion:
    resultado: ResultadoAuditoria
    comparacion: pd.DataFrame
    matriz: pd.DataFrame
    metricas: dict


def evaluar(auditor: Auditor, ruta_historico: Path, hoja_export: str = "Busqueda",
            hoja_veredictos: str = "Datos") -> Evaluacion:
    lote = cargar_export(ruta_historico, hoja_export)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        humanos = pd.read_excel(ruta_historico, sheet_name=hoja_veredictos)
    humanos = humanos.drop_duplicates("Fault Barcode").set_index("Fault Barcode")

    # La fecha de referencia de cada DIP es la fecha en que el humano lo auditó.
    fechas: list[date] = []
    for barcode in lote.datos["barcode"]:
        f = parse_fecha(humanos["AUDIT DATE - Apertura"].get(barcode)) if barcode in humanos.index else None
        fechas.append(f.date() if isinstance(f, datetime) else auditor.fecha_auditoria)
    resultado = auditor.auditar_lote(lote, fechas)

    filas = resultado.filas.copy()
    filas["ESTADO HUMANO"] = filas["Fault Barcode"].map(humanos["STATUS - Apertura"])
    filas["COMENTARIO HUMANO"] = filas["Fault Barcode"].map(humanos["COMMENTS - Apertura"])
    comp = filas[(filas["ESTADO IA"] != "FUERA DE ALCANCE")
                 & filas["ESTADO HUMANO"].isin(ESTADOS_HUMANOS)].copy()

    comp["HUMANO DISCREPANCIA"] = comp["ESTADO HUMANO"] != "OK"
    comp["IA DISCREPANCIA"] = comp["ESTADO IA"].str.startswith("DISCREPANCIA")
    comp["IA MARCA"] = comp["ESTADO IA"] != "OK"
    comp["TEMA HUMANO"] = comp["COMENTARIO HUMANO"].map(tema)
    comp["NO DETECTABLE DESDE EXCEL"] = comp["TEMA HUMANO"].isin(_NO_DETECTABLE)
    # Cualquier hallazgo, incluidas observaciones (no cambian el estado).
    comp["IA ALGÚN HALLAZGO"] = comp["HALLAZGOS"].fillna("").str.strip() != ""

    def acuerdo(fila) -> str:
        if fila["HUMANO DISCREPANCIA"] and fila["IA MARCA"]:
            return "Ambos marcan"
        if not fila["HUMANO DISCREPANCIA"] and not fila["IA MARCA"]:
            return "Ambos OK"
        if fila["HUMANO DISCREPANCIA"]:
            return "Solo humano"
        return "Solo IA"
    comp["ACUERDO"] = comp.apply(acuerdo, axis=1)

    matriz = pd.crosstab(comp["ESTADO HUMANO"], comp["ESTADO IA"]).reindex(
        index=ESTADOS_HUMANOS, columns=ESTADOS_IA, fill_value=0)

    humano_disc = comp[comp["HUMANO DISCREPANCIA"]]
    detectables = humano_disc[~humano_disc["NO DETECTABLE DESDE EXCEL"]]
    humano_ok = comp[~comp["HUMANO DISCREPANCIA"]]
    asociados = comp["ASOCIACIÓN"].str.startswith("REGLAS").sum()

    h = resultado.hallazgos
    h = h[h["Fault Barcode"].isin(humano_ok["Fault Barcode"])
          & h["Severidad"].isin(["CRITICA", "NO CRITICA"])]
    metricas = {
        "dips_comparados": len(comp),
        "asociados_por_reglas": int(asociados),
        "pct_asociados": asociados / len(comp) * 100 if len(comp) else 0,
        "humano_discrepancias": len(humano_disc),
        "humano_disc_marcadas_ia": int(humano_disc["IA MARCA"].sum()),
        "humano_disc_detectables": len(detectables),
        "humano_disc_detectables_marcadas": int(detectables["IA MARCA"].sum()),
        "humano_ok": len(humano_ok),
        "humano_ok_ia_ok": int((~humano_ok["IA MARCA"]).sum()),
        "humano_ok_ia_discrepancia": int(humano_ok["IA DISCREPANCIA"].sum()),
        "humano_ok_ia_revisar": int((humano_ok["ESTADO IA"] == "REVISAR").sum()),
        "codigos_en_humano_ok": h["Código"].value_counts().to_dict(),
        "por_tema": {
            t: (int(len(g)), int(g["IA MARCA"].sum()), int(g["IA ALGÚN HALLAZGO"].sum()))
            for t, g in humano_disc.groupby("TEMA HUMANO")
        },
        "segundos": resultado.segundos,
    }
    return Evaluacion(resultado=resultado, comparacion=comp, matriz=matriz, metricas=metricas)


def exportar_evaluacion(ev: Evaluacion, ruta: Path) -> Path:
    from .reporte import COLORES_ESTADO, _escribir_tabla
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Métricas"
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 20
    for k, v in ev.metricas.items():
        ws.append([k, str(v) if isinstance(v, dict) else v])
    ws.append([])
    ws.append(["Matriz: filas = auditor humano, columnas = auditor automático"])
    _matriz = ev.matriz.reset_index()
    ws.append(list(_matriz.columns))
    for fila in _matriz.itertuples(index=False):
        ws.append(list(fila))

    columnas = ["Fila Excel", "Fault Barcode", "Aircraft", "Fault Name", "DIP Interval",
                "Interval Type", "ESTADO HUMANO", "COMENTARIO HUMANO", "TEMA HUMANO",
                "ESTADO IA", "HALLAZGOS", "ACUERDO", "NO DETECTABLE DESDE EXCEL",
                "REFERENCIA ASOCIADA", "ASOCIACIÓN"]
    desacuerdos = ev.comparacion[ev.comparacion["ACUERDO"].isin(["Solo humano", "Solo IA"])]
    _escribir_tabla(wb.create_sheet("Desacuerdos"), desacuerdos[columnas], None,
                    "ESTADO IA", COLORES_ESTADO)
    _escribir_tabla(wb.create_sheet("Comparación completa"), ev.comparacion[columnas], None,
                    "ESTADO IA", COLORES_ESTADO)
    wb.save(ruta)
    return ruta
