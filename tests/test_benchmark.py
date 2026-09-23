"""Benchmark anónimo: sin datos del personal y sin regresiones frente a la línea base."""

from __future__ import annotations

import openpyxl
import pandas as pd
import pytest

from dips_audit.__main__ import DATOS_BENCHMARK, LINEA_BASE, main
from dips_audit.anonimizar import (COLUMNAS_PERSONAL, HOJA, MARCA, Tachador, anonimizar,
                                   muestrear, nombres_del_personal)
from dips_audit.evaluacion import cargar_linea_base, empeoraron, evaluar, indicadores
from tests.conftest import HISTORICO


def test_tachador_reemplaza_nombre_y_apellidos():
    t = Tachador({"QUINTERO"}, ["T/A CORREGIDO AL 15-OCT-2026"] * 5)
    texto, n = t.tachar("T/A CORREGIDO AL 15-OCT-2026 POR JOEL XAVIER QUINTERO.")
    assert (texto, n) == (f"T/A CORREGIDO AL 15-OCT-2026 POR {MARCA}.", 1)


def test_tachador_no_toca_terminos_tecnicos():
    t = Tachador(set(), [])
    texto = "BOEING 737-8 MAX8 APU FIRE BOTTLE DUE 30-JAN-2027"
    assert t.tachar(texto) == (texto, 0)


def test_nombres_del_personal_ignora_meses_y_palabras_cortas():
    datos = pd.DataFrame({"AUDITOR - Apertura": ["ANA JAN QUINTERO"], "Otra": ["XAVIER"]})
    assert nombres_del_personal(datos) == {"QUINTERO"}


def test_muestrear_solo_others_con_veredicto_y_proporcional():
    tabla = pd.DataFrame({
        "Fault Barcode": [f"T{i}" for i in range(40)],
        "Type DIP": ["Others"] * 30 + ["Powerplant"] * 10,
        "STATUS - Apertura": ["OK"] * 20 + ["DISCREPANCIA CRÍTICA"] * 8 + ["PENDIENTES"] * 2
                             + ["OK"] * 10,
    })
    muestra = muestrear(tabla, 7)
    assert len(muestra) == 7 and set(muestra["Type DIP"]) == {"Others"}
    assert muestra["STATUS - Apertura"].value_counts().to_dict() == {
        "OK": 5, "DISCREPANCIA CRÍTICA": 2}
    assert muestra.equals(muestrear(tabla, 7))      # misma semilla, misma muestra
    assert len(muestrear(tabla, None)) == 28        # sin cantidad: todos los Others con veredicto


def test_benchmark_sin_columnas_del_personal():
    wb = openpyxl.load_workbook(DATOS_BENCHMARK, read_only=True)
    encabezado = [c.value for c in next(wb[HOJA].iter_rows(max_row=1))]
    wb.close()
    assert not set(encabezado) & set(COLUMNAS_PERSONAL)
    assert {"Fault Barcode", "STATUS - Apertura", "AUDIT DATE - Apertura"} <= set(encabezado)


def test_benchmark_no_empeora_la_linea_base(config):
    """Si un cambio intencional baja un indicador, actualice la línea base:
    python -m dips_audit benchmark --guardar-linea-base"""
    from dips_audit.auditor import Auditor

    base = cargar_linea_base(LINEA_BASE)
    assert base is not None, "Falta benchmark/linea_base.json"
    actuales = indicadores(evaluar(Auditor(config), DATOS_BENCHMARK).metricas)
    assert actuales["coincidencia"]["total"] == base["indicadores"]["coincidencia"]["total"]
    assert empeoraron(actuales, base) == []


def test_cli_benchmark(capsys):
    assert main(["benchmark", "--sin-excel"]) == 0
    assert "Ningún indicador empeoró" in capsys.readouterr().out


@pytest.mark.skipif(not HISTORICO.exists(), reason="No está el histórico de auditorías")
def test_anonimizar_reproduce_el_benchmark():
    anon = anonimizar(HISTORICO)
    guardado = pd.read_excel(DATOS_BENCHMARK, sheet_name=HOJA)
    assert list(anon.tabla["Fault Barcode"]) == list(guardado["Fault Barcode"])
