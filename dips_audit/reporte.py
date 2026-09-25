"""Exporta el resultado de la auditoría a un Excel nuevo (el original no se modifica)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .auditor import ResultadoAuditoria
from .reglas import MOSTRAR_SEVERIDAD

# El resultado es OK, REVISAR, SIN FUENTE o POSIBLE DISCREPANCIA: sin niveles (crítica / no
# crítica) ni tipos de discrepancia, que todavía no coinciden con el proceso de los auditores.
COLORES_RESULTADO = {"POSIBLE DISCREPANCIA": "FCE3B0", "REVISAR": "FFF59D", "SIN FUENTE": "D6E4F0",
                     "OK": "C9E7C9", "FUERA DE ALCANCE": "E4E4E4"}
COLORES_SEVERIDAD = {"POSIBLE DISCREPANCIA": "FCE3B0", "REVISAR": "FFF59D", "SIN FUENTE": "D6E4F0",
                     "OBSERVACIÓN": "EFEFEF"}
# Mismos tonos que las celdas, pero saturados: en los gráficos los pasteles no se distinguen.
COLORES_GRAFICO = {"POSIBLE DISCREPANCIA": "F39C12", "REVISAR": "F4D03F", "SIN FUENTE": "2E86DE",
                   "OK": "27AE60", "FUERA DE ALCANCE": "95A5A6"}
_ENCABEZADO = PatternFill("solid", fgColor="1F3A5F")
# Columnas agregadas por el programa: encabezado morado y celdas lila, para
# distinguirlas de las columnas originales del Excel de entrada.
_ENCABEZADO_IA = PatternFill("solid", fgColor="5B3A8C")
_CELDA_IA = PatternFill("solid", fgColor="EEE8F6")
COLUMNAS_IA = ["RESULTADO", "COMENTARIO SUGERIDO", "HALLAZGOS",
               "VERIFICACIÓN MANUAL", "REFERENCIA ASOCIADA", "ASOCIACIÓN",
               "TA SEGÚN REFERENCIA", "REFERENCIA TÉCNICA ESPERADA", "REFERENCIA TÉCNICA DEL DIP",
               "RIR EN ICAM", "ADJUNTOS EN ICAM", "AUDITORÍA", "FECHA AUDITORÍA",
               "ESTADO APERTURA", "ESTADO CIERRE"]
_ANCHOS = {"Fault Name": 45, "COMENTARIO SUGERIDO": 60, "HALLAZGOS": 70,
           "VERIFICACIÓN MANUAL": 60, "TA SEGÚN REFERENCIA": 45,
           "REFERENCIA TÉCNICA ESPERADA": 40, "REFERENCIA TÉCNICA DEL DIP": 40, "Detalle": 90,
           "REFERENCIA ASOCIADA": 32, "RESULTADO": 24, "ESTADO APERTURA": 24, "ESTADO CIERRE": 24}
_ENVOLVER = {"HALLAZGOS", "VERIFICACIÓN MANUAL", "COMENTARIO SUGERIDO", "TA SEGÚN REFERENCIA",
             "Detalle", "Fault Name", "REFERENCIA TÉCNICA ESPERADA"}


def ruta_salida(resultado: ResultadoAuditoria, carpeta: Path) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefijo = "PRUEBA_" if resultado.lote.prueba else ""
    return carpeta / f"{prefijo}{resultado.lote.ruta.stem}_AUDITORIA_{marca}.xlsx"


AVISO_PRUEBA = "PRUEBA: datos de prueba, no es una auditoría real."


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
            if nombre in columnas_ia:
                celda.fill = _CELDA_IA
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


def _colorear(ws, df: pd.DataFrame, columna: str, colores: dict) -> None:
    letra = get_column_letter(list(df.columns).index(columna) + 1)
    for celda in ws[letra][1:]:
        if celda.value in colores:
            celda.fill = PatternFill("solid", fgColor=colores[celda.value])


def exportar_excel(resultado: ResultadoAuditoria, ruta: Path) -> Path:
    wb = Workbook()
    _hoja_dashboard(wb.active, resultado)
    _hoja_resumen(wb.create_sheet("Resumen"), resultado)

    # Hoja principal: las columnas originales, en su orden y con su nombre, y al
    # final las columnas que agrega el programa (con su propio color).
    original = resultado.lote.original.copy()
    ia = resultado.filas.set_index("Fila Excel")[COLUMNAS_IA]
    combinado = pd.concat([original, ia], axis=1, join="inner")
    combinado["Fila Excel"] = combinado.index
    hoja = wb.create_sheet("Auditoría")
    _escribir_tabla(hoja, combinado, set(COLUMNAS_IA) | {"Fila Excel"}, "RESULTADO",
                    COLORES_RESULTADO)
    for columna in ("ESTADO APERTURA", "ESTADO CIERRE"):
        _colorear(hoja, combinado, columna, COLORES_RESULTADO)

    _escribir_tabla(wb.create_sheet("Hallazgos"), hallazgos_para_mostrar(resultado.hallazgos), None,
                    "Resultado", COLORES_SEVERIDAD)
    wb.save(ruta)
    return ruta


def hallazgos_para_mostrar(h: pd.DataFrame) -> pd.DataFrame:
    """Hallazgos con su resultado (posible discrepancia u observación), sin tipo de discrepancia."""
    h = h.drop(columns=["Tipo de discrepancia"], errors="ignore")
    h = h.assign(Severidad=h["Severidad"].map(MOSTRAR_SEVERIDAD).fillna(h["Severidad"]))
    return h.rename(columns={"Severidad": "Resultado"})


_RESULTADOS = ["POSIBLE DISCREPANCIA", "REVISAR", "SIN FUENTE", "OK"]
_TITULO = Font(bold=True, size=16, color="1F3A5F")
_SUBTITULO = Font(bold=True, size=11, color="1F3A5F")
_BORDE = Border(bottom=Side(style="thin", color="C3C2B7"))


def _etiquetas(valor: bool = False, porcentaje: bool = False) -> DataLabelList:
    """Solo el valor o el porcentaje (sin nombre de serie ni de categoría)."""
    e = DataLabelList()
    e.showVal, e.showPercent = valor, porcentaje
    e.showSerName = e.showCatName = e.showLegendKey = False
    return e


def _ejes_visibles(grafico) -> None:
    """Excel reciente oculta los ejes de openpyxl si no se piden."""
    grafico.x_axis.delete = False
    grafico.y_axis.delete = False
    grafico.x_axis.majorGridlines = None


def _tabla_datos(ws, fila: int, col: int, encabezado: list[str], filas: list[list]) -> tuple[int, int]:
    """Escribe una tabla chica (datos de un gráfico). Devuelve (primera fila, última fila)."""
    for j, e in enumerate(encabezado):
        c = ws.cell(fila, col + j, e)
        c.font = Font(bold=True, color="52514E")
        c.border = _BORDE
    for i, f in enumerate(filas, start=1):
        for j, v in enumerate(f):
            ws.cell(fila + i, col + j, v)
    return fila, fila + len(filas)


def _hoja_dashboard(ws, resultado: ResultadoAuditoria) -> None:
    """Primera hoja: indicadores y gráficos del resultado."""
    ws.title = "Dashboard"
    ws.sheet_view.showGridLines = False
    filas = resultado.filas
    tipos = dict(zip(resultado.lote.datos["fila"], resultado.lote.datos["tipo"]))
    datos = filas.assign(TIPO=[(tipos.get(f) or "Sin tipo") for f in filas["Fila Excel"]])
    en_alcance = datos[datos["RESULTADO"] != "FUERA DE ALCANCE"]
    total = len(en_alcance)

    ws["B2"] = "Auditoría preliminar de DIPs" + (f" · {AVISO_PRUEBA}" if resultado.lote.prueba else "")
    ws["B2"].font = Font(bold=True, size=16, color="C00000") if resultado.lote.prueba else _TITULO
    ws["B3"] = (f"{resultado.lote.ruta.name} · {datetime.now():%d-%b-%Y %H:%M} · "
                "Resultado de apoyo: el auditor confirma cada DIP.")
    ws["B3"].font = Font(color="52514E")

    # Indicadores
    tarjetas = [("DIPs auditados", total, None, "1F3A5F")]
    for r in _RESULTADOS:
        n = int((en_alcance["RESULTADO"] == r).sum())
        tarjetas.append((r, n, n / total if total else 0, COLORES_RESULTADO[r]))
    fuera = int((datos["RESULTADO"] == "FUERA DE ALCANCE").sum())
    for i, (nombre, n, pct, color) in enumerate(tarjetas):
        col = 2 + i * 3
        ws.merge_cells(start_row=5, start_column=col, end_row=5, end_column=col + 1)
        ws.cell(5, col, nombre).font = Font(bold=True, color="52514E")
        ws.cell(6, col, n).font = Font(bold=True, size=22)
        if pct is not None:
            ws.cell(7, col, pct).number_format = "0.0%"
        for fila in (5, 6, 7):
            ws.cell(fila, col).fill = PatternFill("solid", fgColor=color if fila == 5 and pct is not None
                                                   else "F4F4F1")
    ws.cell(8, 2, f"Fuera de alcance: {fuera} DIPs de otros tipos." if fuera else "").font = \
        Font(italic=True, color="7B7973")
    for c in range(2, 15):
        ws.column_dimensions[get_column_letter(c)].width = 14

    # Datos de los gráficos (columnas P en adelante, a la derecha de los gráficos)
    col = 16
    ws.cell(4, col, "Datos de los gráficos").font = _SUBTITULO
    f1, f2 = _tabla_datos(ws, 5, col, ["Resultado", "DIPs"],
                          [[r, int((en_alcance["RESULTADO"] == r).sum())] for r in _RESULTADOS])
    pie = PieChart()
    pie.title = "Resultado de los DIPs auditados"
    pie.add_data(Reference(ws, min_col=col + 1, min_row=f1, max_row=f2), titles_from_data=True)
    pie.set_categories(Reference(ws, min_col=col, min_row=f1 + 1, max_row=f2))
    for i, r in enumerate(_RESULTADOS):
        punto = DataPoint(idx=i)
        punto.graphicalProperties.solidFill = COLORES_GRAFICO[r]
        pie.series[0].dPt.append(punto)
    pie.dataLabels = _etiquetas(porcentaje=True)
    pie.legend.position = "b"
    pie.height, pie.width = 8, 12
    ws.add_chart(pie, "B10")

    # DIPs por tipo, apilados por resultado
    por_tipo = datos.groupby(["TIPO", "RESULTADO"]).size().unstack(fill_value=0)
    columnas = [r for r in _RESULTADOS + ["FUERA DE ALCANCE"] if r in por_tipo.columns]
    g1, g2 = _tabla_datos(ws, f2 + 2, col, ["Tipo DIP"] + columnas,
                          [[t] + [int(por_tipo.loc[t, c]) for c in columnas] for t in por_tipo.index])
    barras = BarChart()
    barras.type, barras.grouping, barras.overlap = "col", "stacked", 100
    barras.title = "DIPs por tipo"
    barras.add_data(Reference(ws, min_col=col + 1, max_col=col + len(columnas), min_row=g1, max_row=g2),
                    titles_from_data=True)
    barras.set_categories(Reference(ws, min_col=col, min_row=g1 + 1, max_row=g2))
    for serie, c in zip(barras.series, columnas):
        serie.graphicalProperties.solidFill = COLORES_GRAFICO[c]
        serie.graphicalProperties.line.solidFill = "FFFFFF"
    barras.y_axis.title = "DIPs"
    barras.legend.position = "b"
    _ejes_visibles(barras)
    barras.height, barras.width = 8, 14
    ws.add_chart(barras, "H10")

    # Referencias con más posibles discrepancias
    discrepancias = en_alcance[en_alcance["RESULTADO"] == "POSIBLE DISCREPANCIA"]
    refs = discrepancias["REFERENCIA ASOCIADA"].replace("", "Sin referencia").value_counts().head(10)
    for fila_graf, serie_datos, titulo, encabezado in [
            (27, refs, "Referencias con más DIPs con posible discrepancia", "Referencia")]:
        if serie_datos.empty:
            continue
        inicio = ws.max_row + 2
        d1, d2 = _tabla_datos(ws, inicio, col, [encabezado, "DIPs"],
                              [[str(k), int(v)] for k, v in serie_datos.items()][::-1])
        grafico = BarChart()
        grafico.type = "bar"
        grafico.title = titulo
        grafico.legend = None
        grafico.add_data(Reference(ws, min_col=col + 1, min_row=d1, max_row=d2), titles_from_data=True)
        grafico.set_categories(Reference(ws, min_col=col, min_row=d1 + 1, max_row=d2))
        grafico.series[0].graphicalProperties.solidFill = COLORES_GRAFICO["POSIBLE DISCREPANCIA"]
        grafico.dataLabels = _etiquetas(valor=True)
        _ejes_visibles(grafico)
        grafico.height, grafico.width = 8, 26
        ws.add_chart(grafico, f"B{fila_graf}")
    ws.column_dimensions[get_column_letter(col)].width = 38


def _hoja_resumen(ws, resultado: ResultadoAuditoria) -> None:
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 90
    ws.append(["Auditoría preliminar de DIPs (generada automáticamente)"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append(["Resultado de apoyo: toda discrepancia debe ser confirmada por un auditor."])
    if resultado.lote.prueba:
        ws.append([AVISO_PRUEBA])
        ws.cell(ws.max_row, 1).font = Font(bold=True, color="C00000")
    ws.append([])
    datos = [
        ("Archivo", str(resultado.lote.ruta)),
        ("Hoja", resultado.lote.hoja),
        ("Generado", datetime.now().strftime("%d-%b-%Y %H:%M")),
        ("DIPs en el archivo", len(resultado.filas)),
        ("Tiempo de procesamiento", f"{resultado.segundos:.1f} s"),
    ]
    for fila in datos:
        ws.append(list(fila))
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.append([])
    ws.append(["Resultado", "Cantidad"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    conteo = resultado.filas["RESULTADO"].value_counts()
    for valor, color in COLORES_RESULTADO.items():
        ws.append([valor, int(conteo.get(valor, 0))])
        ws.cell(ws.max_row, 1).fill = PatternFill("solid", fgColor=color)
    ws.append([])
    ws.append(["Resultado", "DIPs"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    conteo = resultado.filas["RESULTADO"].value_counts()
    for estado, color in COLORES_RESULTADO.items():
        ws.append([estado, int(conteo.get(estado, 0))])
        ws.cell(ws.max_row, 1).fill = PatternFill("solid", fgColor=color)
    if resultado.advertencias:
        ws.append([])
        ws.append(["Notas de la carga"])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
        for nota in resultado.advertencias:
            ws.append(["", nota])
            ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True)
