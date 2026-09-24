"""Pruebas de punta a punta: Excel de entrada -> auditoría -> Excel de resultado."""

from datetime import date, datetime

import openpyxl
import pytest

from dips_audit.__main__ import main
from dips_audit.auditor import Auditor
from dips_audit.reporte import exportar_excel
from tests.conftest import crear_export

AVION = "Boeing 737-8V3 - HP-1837CMP"
FILAS = [
    # OK
    ["T1", 28, "Others", "DIP - FUEL MICROBIAL GROWTH", 4, "DAY", "ACTV", "HP-1837CMP", AVION,
     "DIP", "28-DIP", datetime(2026, 8, 22, 23, 59), datetime(2026, 8, 18, 9, 0), None, 2],
    # Intervalo excedido (FDR es 30 días)
    ["T2", 31, "Others", "FDR - REPORT", 45, "DAY", "ACTV", "HP-1837CMP", AVION, "DIP", "31-DIP",
     datetime(2026, 10, 2, 23, 59), datetime(2026, 8, 18, 9, 0), None, 43],
    # Sin referencia en la tabla
    ["T3", 25, "Others", "DEFIBRILLATOR DUE DATE", 38, "DAY", "ACTV", "HP-1837CMP", AVION, "DIP",
     "25-DIP", datetime(2026, 9, 25, 23, 59), datetime(2026, 8, 18, 9, 0), None, 36],
    # Duplicado del oxígeno siguiente
    ["T4", 35, "Others", "CREW OXYGEN 850 PSI", 3, "DAY", "ACTV", "HP-1837CMP", AVION, "DIP",
     "35-DIP", datetime(2026, 8, 21, 23, 59), datetime(2026, 8, 18, 9, 0), None, 2],
    ["T5", 35, "Others", "DIP-CREW OXYGEN BOTTLE", 3, "DAY", "ACTV", "HP-1837CMP", AVION, "DIP",
     "35-DIP", datetime(2026, 8, 21, 23, 59), datetime(2026, 8, 18, 11, 0), None, 2],
    # Fuera de alcance (Powerplant)
    ["T6", 71, "Powerplant", "ENGINE 1 VCD SEAL", 40, "DAY", "ACTV", "HP-1837CMP", AVION, "DIP",
     "71-DIP", datetime(2026, 9, 27, 23, 59), datetime(2026, 8, 18, 9, 0), None, 38],
]


@pytest.fixture
def export(tmp_path):
    return crear_export(tmp_path / "export_icam.xlsx", FILAS)


def test_auditoria_de_punta_a_punta(config, export, tmp_path):
    auditor = Auditor(config, fecha_auditoria=date(2026, 8, 20))
    resultado = auditor.auditar_archivo(export)
    # Tres resultados: OK, SIN FUENTE (no está en la tabla) o POSIBLE DISCREPANCIA.
    estados = dict(zip(resultado.filas["Fault Barcode"], resultado.filas["RESULTADO"]))
    assert estados == {
        "T1": "OK",
        "T2": "POSIBLE DISCREPANCIA",
        "T3": "SIN FUENTE",
        "T4": "OK",
        "T5": "POSIBLE DISCREPANCIA",
        "T6": "FUERA DE ALCANCE",
    }
    comentario = resultado.filas.set_index("Fault Barcode").loc["T1", "COMENTARIO SUGERIDO"]
    assert comentario == "T/A aperturado correctamente"

    salida = exportar_excel(resultado, tmp_path / "salida.xlsx")
    wb = openpyxl.load_workbook(salida)
    assert wb.sheetnames == ["Dashboard", "Resumen", "Auditoría", "Hallazgos"]
    dashboard = wb["Dashboard"]
    assert len(dashboard._charts) >= 3            # resultado, DIPs por tipo, referencias
    assert dashboard["B6"].value == 5             # DIPs auditados (sin el Powerplant)
    ws = wb["Auditoría"]
    encabezado = [c.value for c in ws[1]]
    # Columnas originales primero, con su nombre y orden; las del programa al final.
    originales = [c.value for c in openpyxl.load_workbook(export)["Export"][1]]
    assert encabezado[:len(originales)] == originales
    agregadas = encabezado[len(originales):]
    assert agregadas[:2] == ["RESULTADO", "COMENTARIO SUGERIDO"] and agregadas[-1] == "Fila Excel"
    assert ws.cell(1, len(originales)).fill.fgColor.rgb != ws.cell(1, len(originales) + 1).fill.fgColor.rgb
    assert "TIPO DE DISCREPANCIA" not in encabezado and "ESTADO IA" not in encabezado
    assert [c.value for c in wb["Hallazgos"][1]].count("Tipo de discrepancia") == 0
    assert ws.max_row == len(FILAS) + 1
    # El archivo original no se modifica.
    assert openpyxl.load_workbook(export).sheetnames == ["Export"]


def test_cli_auditar(export, tmp_path, capsys):
    salida = tmp_path / "cli.xlsx"
    codigo = main(["auditar", str(export), "--salida", str(salida), "--fecha", "2026-08-20"])
    assert codigo == 0 and salida.exists()
    salida_consola = capsys.readouterr().out
    assert "POSIBLE DISCREPANCIA" in salida_consola and "CRÍTICA" not in salida_consola


def test_cli_archivo_inexistente(tmp_path):
    assert main(["auditar", str(tmp_path / "no_existe.xlsx"), "--sin-excel"]) == 1
