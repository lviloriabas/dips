"""Inventario de oxygen generators (PDF adjunto) y la auditoría del due date con él."""

import io
from datetime import date, datetime

import pytest

from dips_audit.inventario import (cruzar, fecha_de_vencimiento, leer_campos_pdf,
                                   leer_inventario)
from dips_audit.reglas import auditar_dip, estado_final
from tests.conftest import hacer_dip

# Campos del formulario como vienen en el PDF (HP-1855CMP, 25-SEP-2026).
CAMPOS = {
    "PositionRow3": "AFT RH", "PNRow3": "E72220-10", "SNRow3": "BEFB-F029-134",
    "Manufac DateRow3": "02-2014", "Exp DateRow3": "02-2029", "DIP BarcodeRow3": "T40S009JAHK",
    "PositionRow4": "AFT LH", "PNRow4": "E72220-10", "SNRow4": "BEFA-F016-171",
    "Manufac DateRow4": "01-2014", "Exp DateRow4": "01-2029", "DIP BarcodeRow4": "T40S009JAH7",
    "PositionRow1_2": "LAV A", "PNRow1_2": "4441806-022", "SNRow1_2": "41806-022-05507",
    "Exp DateRow1_2": "08-2036", "DIP BarcodeRow1_2": "N/A",
    # PSU: la posición es la fila; "_2" es el segundo generator de la PSU (X = no aplica).
    "PN1EF 1DEF": "E72280-00", "SN1EF 1DEF": "BEFA-F041-025", "Exp DATE1EF 1DEF": "01/2029",
    "DIP BARCODE1EF 1DEF": "T40S009J6NT",
    "PN1EF 1DEF_2": "X", "SN1EF 1DEF_2": "X", "Exp DATE1EF 1DEF_2": "X",
    "PN2EF 2DEF": "E72280-00", "SN2EF 2DEF": "BEFA-F041-199", "Exp DATE2EF 2DEF": "12/2028",
    "DIP BARCODE2EF 2DEF": "T40S009J6NT",
}
INVENTARIO = leer_inventario(CAMPOS)


def pdf_con_campos(campos: dict[str, str]) -> bytes:
    """PDF de una página con un formulario (como el inventario hecho en Word)."""
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

    w = PdfWriter()
    w.add_blank_page(612, 792)
    lista = ArrayObject()
    for nombre, valor in campos.items():
        lista.append(w._add_object(DictionaryObject({
            NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject(nombre),
            NameObject("/V"): TextStringObject(valor)})))
    w._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): lista})
    salida = io.BytesIO()
    w.write(salida)
    return salida.getvalue()


def test_lee_los_campos_del_formulario():
    pytest.importorskip("pypdf")
    assert leer_campos_pdf(pdf_con_campos({"SNRow4": "BEFA-F016-171", "PNRow4": " "})) == {
        "SNRow4": "BEFA-F016-171"}


def test_vencimiento_es_el_fin_del_mes():
    assert fecha_de_vencimiento("01/2029") == date(2029, 1, 31)
    assert fecha_de_vencimiento("02-2029") == date(2029, 2, 28)
    assert fecha_de_vencimiento("31-JAN-2029") == date(2029, 1, 31)
    assert fecha_de_vencimiento("N/A") is None


def test_filas_del_inventario():
    por_sn = {g.sn: g for g in INVENTARIO}
    assert set(por_sn) == {"BEFB-F029-134", "BEFA-F016-171", "41806-022-05507",
                           "BEFA-F041-025", "BEFA-F041-199"}
    assert por_sn["BEFA-F016-171"].posicion == "AFT LH"
    assert por_sn["BEFA-F016-171"].vence == date(2029, 1, 31)
    assert por_sn["BEFA-F016-171"].dip == "T40S009JAH7"
    assert por_sn["BEFA-F041-025"].posicion == "1EF 1DEF"
    assert por_sn["41806-022-05507"].dip == ""


def test_cruce_por_dip_barcode_y_por_sn():
    # Por DIP Barcode, aunque la descripción no traiga los S/N.
    cruce = cruzar(INVENTARIO, "T40S009J6NT", "PASSENGER OXYGEN GENERATORS")
    assert {g.sn for g in cruce.generadores} == {"BEFA-F041-025", "BEFA-F041-199"}
    assert cruce.vence == date(2028, 12, 31)
    # Por S/N (con o sin guiones), aunque el PDF no tenga el barcode del DIP.
    cruce = cruzar(INVENTARIO, "T40S0000001", "LAV A S/N 41806022-05507 S/N BEFA-F099-999")
    assert [g.sn for g in cruce.generadores] == ["41806-022-05507"]
    assert cruce.sn_fuera == ["BEFA-F099-999"]


# --- Regla: el due date contra el Exp. Date del inventario --------------------------------

def _dip(**cambios):
    base = dict(
        barcode="T40S009JAH7", nombre="DIP - ASU AFT LH OXYGEN GENERATOR DUE DATE 31 JAN 2029",
        descripcion="ASU AFT LH P/N E72220-10 S/N BEFA-F016-171 DUE DATE 31 JAN 2029.",
        intervalo=859.0, found_date=datetime(2026, 9, 25, 6, 21),
        due_date=datetime(2029, 1, 31, 23, 59), usage_remaining=859.0, ata=35,
        deferral_ref="35-DIP", parent_assy="Boeing 737-8V3 - HP-1855CMP", flota="NG-800",
        avion="HP-1855CMP", adjuntos=["OXYGEN GENERATOR HP-1855CMP INVENTARY.pdf"],
        inventario={"archivos": ["OXYGEN GENERATOR HP-1855CMP INVENTARY.pdf"],
                    "generadores": INVENTARIO, "errores": {}})
    base.update(cambios)
    return hacer_dip(**base)


def _auditar(catalogo, ctx, **cambios):
    return auditar_dip(_dip(**cambios), catalogo.por_id("GENERADOR_OXIGENO"), ctx)


def _codigos(r):
    return {h.codigo for h in r.hallazgos}


def test_due_date_igual_al_del_inventario(catalogo, ctx):
    r = _auditar(catalogo, ctx)
    assert estado_final(r.hallazgos) == "OK"
    assert not _codigos(r) & {"due_date_posterior_a_vencimiento_item",
                              "due_date_anterior_a_vencimiento_item"}


def test_manda_el_inventario_y_no_la_descripcion(catalogo, ctx):
    # La descripción dice 28 FEB 2029 y el due date la sigue; el PDF dice 01-2029.
    r = _auditar(catalogo, ctx, due_date=datetime(2029, 2, 28, 23, 59),
                 descripcion="ASU AFT LH P/N E72220-10 S/N BEFA-F016-171 DUE DATE 28 FEB 2029.",
                 nombre="DIP - ASU AFT LH OXYGEN GENERATOR DUE DATE 28 FEB 2029")
    h = next(h for h in r.hallazgos if h.codigo == "due_date_posterior_a_vencimiento_item")
    assert h.severidad == "POSIBLE DISCREPANCIA"
    assert "31-JAN-2029" in h.mensaje and "S/N BEFA-F016-171" in h.mensaje
    # Al revés: la descripción trae otra fecha, pero el due date es el del PDF.
    r = _auditar(catalogo, ctx, descripcion="ASU AFT LH S/N BEFA-F016-171 DUE DATE 30 SEP 2026")
    assert estado_final(r.hallazgos) == "OK"


def test_varios_generators_manda_el_primero_que_vence(catalogo, ctx):
    r = _auditar(catalogo, ctx, barcode="T40S009J6NT", nombre="DIP - PASSENGER OXYGEN GENERATORS",
                 descripcion="1EF S/N BEFA-F041-025 DUE DATE 31 JAN 2029\n"
                             "2EF S/N BEFA-F041-199 DUE DATE 31 JAN 2029")
    h = next(h for h in r.hallazgos if h.codigo == "due_date_posterior_a_vencimiento_item")
    assert "31-DEC-2028" in h.mensaje and "BEFA-F041-199" in h.mensaje


def test_due_date_antes_del_inventario_es_observacion(catalogo, ctx):
    r = _auditar(catalogo, ctx, due_date=datetime(2028, 12, 31, 23, 59))
    assert "due_date_anterior_a_vencimiento_item" in _codigos(r)
    assert estado_final(r.hallazgos) == "OK"


def test_sn_que_no_esta_en_el_inventario(catalogo, ctx):
    r = _auditar(catalogo, ctx, descripcion="ASU AFT LH S/N BEFA-F016-171 Y S/N BEFA-F016-999")
    h = next(h for h in r.hallazgos if h.codigo == "sn_fuera_de_inventario")
    assert "BEFA-F016-999" in h.mensaje
    assert estado_final(r.hallazgos) == "POSIBLE DISCREPANCIA"


def test_sin_inventario_con_icam(catalogo, ctx):
    r = _auditar(catalogo, ctx, adjuntos=["ASU AFT LH HP-1855.jpg"],
                 inventario={"archivos": [], "generadores": [], "errores": {}})
    assert "sin_inventario_generadores" in _codigos(r)
    # Sin el PDF se usa la fecha de la descripción.
    r = _auditar(catalogo, ctx, due_date=datetime(2029, 3, 31, 23, 59),
                 inventario={"archivos": [], "generadores": [], "errores": {}})
    assert "due_date_posterior_a_vencimiento_item" in _codigos(r)


def test_sin_icam_queda_como_verificacion_manual(catalogo, ctx):
    r = _auditar(catalogo, ctx, inventario=None, adjuntos=None)
    assert any("PDF de inventario" in m for m in r.manuales)
    assert "sin_inventario_generadores" not in _codigos(r)


def test_pdf_sin_formulario_queda_como_verificacion_manual(catalogo, ctx):
    r = _auditar(catalogo, ctx, inventario={"archivos": ["escaneado.pdf"], "generadores": [],
                                            "errores": {}})
    assert any("escaneado.pdf" in m for m in r.manuales)
    assert "sin_inventario_generadores" not in _codigos(r)


def test_inventario_desde_el_registro_de_icam():
    from dips_audit.cargador import _inventario

    assert _inventario({"barcode": "T40S009JAH7"}) is None   # no se leyeron los PDF
    inv = _inventario({"pdf": {"INVENTARY.pdf": {"campos": CAMPOS}, "foto.pdf": {"campos": {}}},
                       "pdf_errores": {"otro.pdf": "respuesta 500, no es un PDF"}})
    assert inv["archivos"] == ["INVENTARY.pdf", "foto.pdf", "otro.pdf"]
    assert len(inv["generadores"]) == 5
    assert inv["errores"] == {"otro.pdf": "respuesta 500, no es un PDF"}
