"""Benchmark: datos anónimos, resultado en JSON/Markdown y sin regresiones."""

from __future__ import annotations

import json

import openpyxl
import pandas as pd
import pytest

from dips_audit import benchmark as bm
from dips_audit.__main__ import main
from dips_audit.anonimizar import (COLUMNAS_PERSONAL, HOJA, MARCA, Tachador, anonimizar,
                                   muestrear, nombres_del_personal)
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


def test_muestrear_solo_others_con_veredicto_datos_y_proporcional():
    tabla = pd.DataFrame({
        "Fault Barcode": [f"T{i}" for i in range(42)],
        "Type DIP": ["Others"] * 32 + ["Powerplant"] * 10,
        "STATUS - Apertura": ["OK"] * 20 + ["DISCREPANCIA CRÍTICA"] * 8 + ["PENDIENTES"] * 2
                             + ["OK"] * 12,
        "DIP Interval": [3] * 30 + [None, 3] + [3] * 10,
        "Interval Type": ["DAY"] * 31 + [None] + ["DAY"] * 10,
    })
    muestra = muestrear(tabla, 7)
    assert len(muestra) == 7 and set(muestra["Type DIP"]) == {"Others"}
    assert muestra["STATUS - Apertura"].value_counts().to_dict() == {
        "OK": 5, "DISCREPANCIA CRÍTICA": 2}
    assert muestra.equals(muestrear(tabla, 7))      # misma semilla, misma muestra
    # Sin cantidad: todos los Others con veredicto e intervalo (los dos últimos no tienen).
    assert len(muestrear(tabla, None)) == 28


def test_benchmark_sin_columnas_del_personal():
    wb = openpyxl.load_workbook(bm.DATOS, read_only=True)
    encabezado = [c.value for c in next(wb[HOJA].iter_rows(max_row=1))]
    wb.close()
    assert not set(encabezado) & set(COLUMNAS_PERSONAL)
    assert {"Fault Barcode", "STATUS - Apertura", "AUDIT DATE - Apertura"} <= set(encabezado)


def test_no_empeora_la_linea_base(config):
    """Si un cambio intencional baja un indicador, ejecute `python -m dips_audit benchmark` y copie el
    JSON del resultado sobre benchmark/linea_base.json."""
    base = bm.cargar_linea_base()
    assert base is not None, "Falta benchmark/linea_base.json"
    r = bm.ejecutar(config)
    assert bm.comparable(r, base) == ""
    assert bm.empeoraron(r, base) == []


def test_benchmark(config, tmp_path):
    r = bm.ejecutar(config)

    assert r["datos"]["dips"] == len(r["auditoria"]["dips"]) == 50
    assert {d["metodo"] for d in r["auditoria"]["dips"]} <= set(bm.METODOS)
    # Las reglas (con tolerancia a errores de escritura) no aceptan referencias
    # equivocadas; los casos que no resuelven quedan sin referencia.
    ind = r["casos"]["indicadores"]
    assert 0 < ind["con_referencia"]["aciertos"] < ind["con_referencia"]["total"]
    assert ind["sin_referencia"]["aciertos"] == ind["sin_referencia"]["total"]
    assert ind["errores_aceptados"]["aciertos"] == 0
    assert {"preparacion_s", "auditoria_s", "casos_s", "total_s"} == set(r["tiempos"])

    ruta_json, ruta_md = bm.guardar(r, r, tmp_path)
    assert ruta_json.parent == tmp_path
    assert json.loads(ruta_json.read_text(encoding="utf-8")) == r
    md = ruta_md.read_text(encoding="utf-8")
    assert md.startswith(f"# {bm.TITULO}")
    for seccion in ("## Resumen", "## Cómo se audita", "## 1. Resultado frente al auditor",
                    "## 2. Cómo se asoció", "## 3. Casos", "## 4. Tiempos",
                    "## 5. Configuración", "## 6. Desacuerdos"):
        assert seccion in md
    assert "Ningún indicador empeoró" in md
    # Otros datos: no se compara con la línea base.
    otra = {**r, "datos": {**r["datos"], "dips": 10}}
    assert bm.comparable(r, otra).startswith("La línea base se midió con otros datos")


def test_cli_benchmark(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bm, "RESULTADOS", tmp_path / "resultados")
    assert main(["benchmark"]) == 0
    assert "Ningún indicador empeoró" in capsys.readouterr().out
    assert len(list((tmp_path / "resultados").glob("*.json"))) == 1
    assert len(list((tmp_path / "resultados").glob("*.md"))) == 1


@pytest.mark.skipif(not HISTORICO.exists(), reason="No está el histórico de auditorías")
def test_anonimizar_reproduce_el_benchmark():
    anon = anonimizar(HISTORICO)
    guardado = pd.read_excel(bm.DATOS, sheet_name=HOJA)
    assert list(anon.tabla["Fault Barcode"]) == list(guardado["Fault Barcode"])
