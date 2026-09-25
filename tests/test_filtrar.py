from openpyxl import Workbook, load_workbook

from dips_audit.filtrar import filtrar, pendiente, ruta_salida

ENCABEZADO = ["Fault Barcode", "Fault Status", "DIP Open Audit User", "DIP Closed Audit User"]


def test_pendiente():
    assert pendiente("ACTV", " ", " ")
    assert pendiente("ACTV (Active)", None, "X")
    assert not pendiente("ACTV", "KCAMPOS", " ")
    assert pendiente("COMPLETE", "KCAMPOS", " ")
    assert not pendiente("COMPLETE", " ", "KCAMPOS")
    assert not pendiente("PAUSE", " ", " ")


def test_filtrar(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "DIPs Audit (55)"
    ws.append(ENCABEZADO)
    ws.append(["A1", "ACTV", " ", " "])
    ws.append(["A2", "ACTV", "KCAMPOS", " "])
    ws.append(["C1", "COMPLETE", "KCAMPOS", "KCAMPOS"])
    ws.append(["C2", "COMPLETE", "KCAMPOS", " "])
    ws.append(["P1", "PAUSE", " ", " "])
    ws.auto_filter.ref = "A1:D6"
    otra = wb.create_sheet("Notas")
    otra.append(["sin columnas"])
    entrada = tmp_path / "DIPs Audit (25SEP2026).xlsx"
    wb.save(entrada)

    salida, resumen = filtrar(entrada)

    assert salida == ruta_salida(entrada) == tmp_path / "DIPs Audit (25SEP2026) FILTERED.xlsx"
    assert resumen == {"DIPs Audit (55)": (2, 5)}
    ws = load_workbook(salida)["DIPs Audit (55)"]
    assert [r[0] for r in ws.iter_rows(min_row=2, values_only=True)] == ["A1", "C2"]
    assert ws.auto_filter.ref == "A1:D3"
