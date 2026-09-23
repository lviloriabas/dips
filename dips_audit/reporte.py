"""Exporta el resultado de la auditoría a un Excel nuevo (el original no se modifica)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .auditor import ResultadoAuditoria

COLORES_ESTADO = {
    "DISCREPANCIA CRÍTICA": "F4B6B6",
    "DISCREPANCIA NO CRÍTICA": "FCE3B0",
    "REVISAR": "CFE2F3",
    "OK": "C9E7C9",
    "FUERA DE ALCANCE": "E4E4E4",
}
COLORES_SEVERIDAD = {"CRITICA": "F4B6B6", "NO CRITICA": "FCE3B0", "REVISAR": "CFE2F3",
                     "OBSERVACION": "EFEFEF"}
_ENCABEZADO = PatternFill("solid", fgColor="1F3A5F")
_ENCABEZADO_IA = PatternFill("solid", fgColor="5B3A8C")
COLUMNAS_IA = ["ESTADO IA", "TIPO DE DISCREPANCIA", "COMENTARIO SUGERIDO", "HALLAZGOS",
               "VERIFICACIÓN MANUAL", "REFERENCIA ASOCIADA", "ASOCIACIÓN",
               "TA SEGÚN REFERENCIA", "REFERENCIA TÉCNICA ESPERADA"]
_ANCHOS = {"Fault Name": 45, "COMENTARIO SUGERIDO": 60, "HALLAZGOS": 70,
           "VERIFICACIÓN MANUAL": 60, "TA SEGÚN REFERENCIA": 45,
           "REFERENCIA TÉCNICA ESPERADA": 40, "Detalle": 90, "ESTADO IA": 24,
           "TIPO DE DISCREPANCIA": 28, "REFERENCIA ASOCIADA": 32}
_ENVOLVER = {"HALLAZGOS", "VERIFICACIÓN MANUAL", "COMENTARIO SUGERIDO", "TA SEGÚN REFERENCIA",
             "Detalle", "Fault Name", "REFERENCIA TÉCNICA ESPERADA"}


def ruta_salida(resultado: ResultadoAuditoria, carpeta: Path) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    return carpeta / f"{resultado.lote.ruta.stem}_AUDITORIA_{marca}.xlsx"


def _valor(v: object) -> object:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    return v


def _escribir_tabla(ws, df: pd.DataFrame, columnas_ia: set[str] | None = None,
                    col_color: str | None = None, colores: dict | None = None) -> None:
    columnas_ia = columnas_ia or set()
    ws.append(list(df.columns))
    for celda in ws[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = _ENCABEZADO_IA if celda.value in columnas_ia else _ENCABEZADO
        celda.alignment = Alignment(wrap_text=True, vertical="center")
    for fila in df.itertuples(index=False):
        ws.append([_valor(v) for v in fila])
    for n, nombre in enumerate(df.columns, start=1):
        letra = get_column_letter(n)
        ws.column_dimensions[letra].width = _ANCHOS.get(nombre, 16)
        envolver = nombre in _ENVOLVER
        for celda in ws[letra][1:]:
            celda.alignment = Alignment(wrap_text=envolver, vertical="top")
            if isinstance(celda.value, datetime):
                celda.number_format = "dd-mmm-yyyy hh:mm"
    if col_color and colores and col_color in df.columns:
        letra = get_column_letter(list(df.columns).index(col_color) + 1)
        for celda in ws[letra][1:]:
            color = colores.get(celda.value)
            if color:
                celda.fill = PatternFill("solid", fgColor=color)
                celda.font = Font(bold=True)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions


def exportar_excel(resultado: ResultadoAuditoria, ruta: Path) -> Path:
    wb = Workbook()
    _hoja_resumen(wb.active, resultado)

    # Hoja principal: columnas originales de ICAM + columnas de la auditoría.
    original = resultado.lote.original.copy()
    ia = resultado.filas.set_index("Fila Excel")[COLUMNAS_IA]
    combinado = pd.concat([ia, original], axis=1, join="inner")
    combinado.insert(0, "Fila Excel", combinado.index)
    _escribir_tabla(wb.create_sheet("Auditoría"), combinado, set(COLUMNAS_IA),
                    "ESTADO IA", COLORES_ESTADO)

    discrepancias = resultado.hallazgos
    _escribir_tabla(wb.create_sheet("Hallazgos"), discrepancias, None,
                    "Severidad", COLORES_SEVERIDAD)
    wb.save(ruta)
    return ruta


def _hoja_resumen(ws, resultado: ResultadoAuditoria) -> None:
    ws.title = "Resumen"
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 90
    ws.append(["Auditoría preliminar de DIPs (generada automáticamente)"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Resultado de apoyo: toda discrepancia debe ser confirmada por un auditor."])
    ws.append([])
    datos = [
        ("Archivo", str(resultado.lote.ruta)),
        ("Hoja", resultado.lote.hoja),
        ("Generado", datetime.now().strftime("%d-%b-%Y %H:%M")),
        ("DIPs en el archivo", len(resultado.filas)),
        ("Tiempo de procesamiento", f"{resultado.segundos:.1f} s"),
        ("Consultas al modelo local", resultado.consultas_llm),
    ]
    for fila in datos:
        ws.append(list(fila))
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.append([])
    ws.append(["Estado", "Cantidad"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for estado in COLORES_ESTADO:
        n = resultado.conteo_estados().get(estado, 0)
        ws.append([estado, n])
        ws.cell(ws.max_row, 1).fill = PatternFill("solid", fgColor=COLORES_ESTADO[estado])
    if not resultado.hallazgos.empty:
        ws.append([])
        ws.append(["Tipo de discrepancia (críticas y no críticas)", "Cantidad"])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        h = resultado.hallazgos
        conteo = h[h["Severidad"].isin(["CRITICA", "NO CRITICA"])]["Tipo de discrepancia"]
        for tipo, n in conteo.value_counts().items():
            ws.append([tipo, int(n)])
    if resultado.advertencias:
        ws.append([])
        ws.append(["Notas de la carga"])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        for nota in resultado.advertencias:
            ws.append(["", nota])
            ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True)
