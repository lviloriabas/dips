from datetime import datetime

import pytest

from dips_audit.cargador import (ErrorCarga, cargar_export, flota, flota_de_matricula,
                                 flota_de_modelo, parse_fecha, tipo_parent)
from tests.conftest import crear_export

FILA = ["T40S0099FC1", 35, "Others", "CREW OXYGEN", 3, "DAY", "COMPLETE", "HP-9924CMP",
        "Boeing 737-9 MAX9 - HP-9924CMP", "DIP", "35-DIP", "Jul/12/26 23:59",
        datetime(2026, 7, 9, 15, 55), "\xa0", 1]


@pytest.mark.parametrize("valor, esperado", [
    ("Jul/12/26 23:59", datetime(2026, 7, 12, 23, 59)),
    ("7/13/2026 12:30:00 AM", datetime(2026, 7, 13, 0, 30)),
    ("30/Nov/2026", datetime(2026, 11, 30)),
    (datetime(2026, 8, 1), datetime(2026, 8, 1)),
    ("\xa0", None),
    (None, None),
])
def test_parse_fecha(valor, esperado):
    assert parse_fecha(valor) == esperado


@pytest.mark.parametrize("texto, flota", [
    ("Boeing 737-9 MAX9 - HP-9924CMP", "MAX"),
    ("Boeing 737-8 MAX8 - HP-9810CMP", "MAX"),
    ("Boeing 737-8V3 - HP-1837CMP", "NG-800"),
    ("Boeing 737-86N - HP-1726CMP", "NG-800"),
    ("Boeing 737-7V3 - HP-1531CMP", "NG-700"),
])
def test_flota_de_modelo(texto, flota):
    assert flota_de_modelo(texto) == flota


@pytest.mark.parametrize("avion, esperado", [
    ("HP-9804CMP", "MAX"), ("HP-9901CMP", "MAX"), ("HP-1837CMP", "NG"), ("HP1531CMP", "NG"), ("", None),
])
def test_flota_de_matricula(avion, esperado):
    assert flota_de_matricula(avion) == esperado


def test_flota_por_matricula_y_modelo():
    # La matrícula decide MAX o NG; el modelo solo precisa el NG.
    assert flota("HP-9804CMP", "") == "MAX"
    assert flota("HP-1837CMP", "Boeing 737-8V3 - HP-1837CMP") == "NG-800"
    assert flota("HP-1837CMP", "") == "NG"
    assert flota("", "Boeing 737-7V3") == "NG-700"


def test_tipo_parent():
    assert tipo_parent("Boeing 737-8V3 - HP-1837CMP") == "AIRCRAFT"
    assert tipo_parent("(RH) ENGINE EQUIPED (MAX PART) (PN: LEAP-1B28, SN: 603057)") == "ENGINE"
    assert tipo_parent("(LH) CFM56-7B22/3 Engine (PN: CFM56-7B22/3, SN: 804281)") == "ENGINE"


def test_carga_basica(tmp_path):
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [FILA]))
    d = lote.datos.iloc[0]
    assert d["barcode"] == "T40S0099FC1" and d["unidad"] == "DAY" and d["intervalo"] == 3
    assert d["due_date"] == datetime(2026, 7, 12, 23, 59)
    assert d["flota"] == "MAX" and d["parent_tipo"] == "AIRCRAFT"
    assert d["fila"] == 2


@pytest.mark.parametrize("valor, esperado", [
    (" in  work (In Work) ", "IN WORK"), (" pause (Paused) ", "PAUSE"),
    ("ACTV (Active)", "ACTV"), ("COMPLETE (Complete)", "COMPLETE"),
])
def test_normaliza_estado_sin_perder_palabras(tmp_path, valor, esperado):
    fila = list(FILA)
    fila[6] = valor
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [fila]))
    assert lote.datos.iloc[0]["estado"] == esperado


def test_encabezado_en_otra_fila(tmp_path):
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [FILA], filas_antes=2))
    assert lote.fila_encabezado == 3
    assert lote.datos.iloc[0]["fila"] == 4


def test_corrige_dia_mes_invertidos(tmp_path):
    fila = list(FILA)
    fila[12] = datetime(2026, 9, 7, 15, 55)  # 9-jul guardado como 7-sep
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [fila]))
    d = lote.datos.iloc[0]
    assert d["found_date"] == datetime(2026, 7, 9, 15, 55)
    assert "invertidos" in d["correccion_fecha"]


def test_flota_se_propaga_a_dips_de_motor(tmp_path):
    motor = list(FILA)
    motor[0], motor[8] = "T40S0099XXX", "(LH) ENGINE EQUIPED (MAX PART) (PN: LEAP-1B28, SN: 60A795)"
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [FILA, motor]))
    assert lote.datos.iloc[1]["flota"] == "MAX"


@pytest.mark.parametrize("con_flota_conocida", [False, True])
def test_flota_desconocida_conserva_none(tmp_path, con_flota_conocida):
    desconocida = list(FILA)
    desconocida[0], desconocida[7], desconocida[8] = "T40S0099XXX", "", "CFM56 ENGINE"
    filas = [FILA, desconocida] if con_flota_conocida else [desconocida]
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", filas))
    assert lote.datos.iloc[-1]["flota"] is None
    if con_flota_conocida:
        assert lote.datos.iloc[0]["flota"] == "MAX"


def test_columnas_faltantes(tmp_path):
    ruta = crear_export(tmp_path / "e.xlsx", [["X", "Y"]], encabezado=["Fault Barcode", "Fault Name"])
    with pytest.raises(ErrorCarga, match="DIP Interval"):
        cargar_export(ruta)


def test_sin_hoja_valida(tmp_path):
    ruta = crear_export(tmp_path / "e.xlsx", [], encabezado=["A", "B"])
    with pytest.raises(ErrorCarga, match="Fault Barcode"):
        cargar_export(ruta)


# Formato "DIPs Audit (23SEP2026)": fechas con otro nombre, RIR por fila y Datatime.
ENCABEZADO_AUDIT = [
    "Index", "Fault Barcode", "Area", "ATA", "Fault Name", "Fault Description", "Fault Severity",
    "Fault Status", "Found On Date", "Fault Due Date", "Complete Dt", "Dip Interval",
    "Interval Type", "Usage Remaining", "Aircraft", "Task Parent Assy", "Rir Barcode", "Rir Name",
    "Rir Driver Interval", "Rir Driver Type", "Datatime",
]


def _fila_audit(barcode, rir=(" ", " ", None, " ")):
    return [1, barcode, "Structures", 57, "DENT ON FLAP", "DENT FOUND", "DIP", "ACTV",
            datetime(2026, 9, 10, 21, 57), datetime(2026, 12, 1, 23, 59),
            datetime(2026, 9, 20, 8, 0), 600, "CYCLES", 580, "HP-9901CMP",
            "Boeing 737-9 MAX9 - HP-9901CMP", *rir, datetime(2026, 9, 23, 6, 54)]


def test_formato_dips_audit(tmp_path):
    filas = [_fila_audit("T1", ("R1", "RIR FLAP DENT", 25, "CYCLES")), _fila_audit("T2"),
             _fila_audit("T1")]
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", filas, encabezado=ENCABEZADO_AUDIT))
    assert list(lote.datos["barcode"]) == ["T1", "T2"]  # la fila repetida se omite
    assert any("repetido" in n for n in lote.notas)
    d = lote.datos.iloc[0]
    assert d["found_date"] == datetime(2026, 9, 10, 21, 57)
    assert d["complete_date"] == datetime(2026, 9, 20, 8, 0)
    assert d["intervalo"] == 600 and d["unidad"] == "FC"
    assert [str(r) for r in d["rirs"]] == ["RIR FLAP DENT (R1): 25 FC"]
    assert lote.datos.iloc[1]["rirs"] == []


def test_formato_anterior_sin_datos_de_rir(tmp_path):
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [FILA]))
    assert lote.datos.iloc[0]["rirs"] is None


def test_excel_conserva_remanente_rir_y_accion_correctiva(tmp_path):
    cabecera = ENCABEZADO_AUDIT + ["Rir Driver Usage Rem", "Corrective Action"]
    fila = _fila_audit("T1", ("R1", "RIR", 50, "HOURS")) + [-2778.4, "REPLACED S/N2: 00875"]
    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [fila], encabezado=cabecera))
    d = lote.datos.iloc[0]
    assert d["rirs_excel"][0].limites[0].restante == -2778.4
    assert d["accion_correctiva"] == "REPLACED S/N2: 00875"
    assert d["datos_referencia"]


def test_corrective_action_y_fecha_diferido_en_export_icam(tmp_path):
    from dips_audit.cargador import completar_con_icam

    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [FILA]))
    ruta = tmp_path / "icam.csv"
    ruta.write_text("barcode,corrective_action,Defer Dt\n"
                    "T40S0099FC1,REPLACED IAW AMM TASK 12-15-21-210-801,08-Jul-2026\n",
                    encoding="utf-8")
    completar_con_icam(lote, ruta)
    d = lote.datos.iloc[0]
    assert d["accion_correctiva"] == "REPLACED IAW AMM TASK 12-15-21-210-801"
    assert d["defer_date"] == datetime(2026, 7, 8)
