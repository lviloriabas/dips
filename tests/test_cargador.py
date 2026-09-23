from datetime import datetime

import pytest

from dips_audit.cargador import (ErrorCarga, cargar_export, flota_de_modelo, parse_fecha,
                                 tipo_parent)
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


def test_columnas_faltantes(tmp_path):
    ruta = crear_export(tmp_path / "e.xlsx", [["X", "Y"]], encabezado=["Fault Barcode", "Fault Name"])
    with pytest.raises(ErrorCarga, match="DIP Interval"):
        cargar_export(ruta)


def test_sin_hoja_valida(tmp_path):
    ruta = crear_export(tmp_path / "e.xlsx", [], encabezado=["A", "B"])
    with pytest.raises(ErrorCarga, match="Fault Barcode"):
        cargar_export(ruta)
