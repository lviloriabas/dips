"""Comprueba ejemplos ejecutables y que el generador no cambia la detección."""

import importlib.util
from datetime import date
from pathlib import Path

import pytest
import yaml

from dips_audit.discrepancias import Discrepancias
from dips_audit.reglas import Contexto, ResultadoReglas

spec = importlib.util.spec_from_file_location("generador_guia", Path(__file__).with_name("generar_regla.py"))
generador = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generador)


def ejemplo(**cambios):
    valores = dict(codigo="ejemplo_descripcion", tipo="Datos requeridos",
                   campo="descripcion", condicion="vacio", texto="", etapa="APERTURA",
                   severidad="OBSERVACION", mensaje="Descripción vacía.")
    return generador.generar(**{**valores, **cambios})


def ejecutar(archivos, dip, activa=True):
    espacio = {}
    exec(compile(archivos["regla.py.txt"], "ejemplo", "exec"), espacio)
    d = Discrepancias.desde_dict({"Datos requeridos": {"reglas": {
        "ejemplo_descripcion": {"activa": activa, "severidad": "OBSERVACION"}}}})
    r = ResultadoReglas()
    espacio["regla_ejemplo_descripcion"](dip, Contexto(date(2026, 10, 5), d), r)
    return r


def test_ejemplo_detecta_solo_ausencia_y_respeta_interruptor():
    archivos = ejemplo()
    assert ejecutar(archivos, {"estado": "ACTV", "descripcion": ""}).hallazgos
    assert not ejecutar(archivos, {"estado": "ACTV", "descripcion": "Dato"}).hallazgos
    assert not ejecutar(archivos, {"estado": "ACTV", "descripcion": ""}, activa=False).hallazgos
    assert not ejecutar(archivos, {"estado": "COMPLETE", "descripcion": ""}).hallazgos
    sin_dato = ejecutar(archivos, {"estado": "ACTV"})
    assert sin_dato.manuales and not sin_dato.hallazgos


def test_texto_literal_y_etapa_cierre():
    archivos = ejemplo(condicion="no_contiene", texto="AMM 'TASK'", etapa="CIERRE")
    assert not ejecutar(archivos, {"estado": "COMPLETE", "descripcion": "IAW amm 'task'"}).hallazgos
    assert ejecutar(archivos, {"estado": "COMPLETE", "descripcion": "Otra"}).hallazgos
    assert not ejecutar(archivos, {"estado": "ACTV", "descripcion": "Otra"}).hallazgos
    assert "CODIGOS_CIERRE" in archivos["LEEME.md"]
    assert "auditar_dip" in archivos["prueba.py.txt"]


def test_guardado_separado_y_no_sobrescribe(tmp_path):
    destino = tmp_path / "ejemplo"
    generador.guardar(ejemplo(), destino)
    assert {p.name for p in destino.iterdir()} == {
        "regla.py.txt", "prueba.py.txt", "discrepancias.yaml.txt", "LEEME.md"}
    with pytest.raises(FileExistsError):
        generador.guardar(ejemplo(), destino)


def test_yaml_conserva_codigos_y_nombres_con_comillas():
    archivos = ejemplo(codigo="null", tipo="Datos 'especiales': auditor")
    d = Discrepancias.desde_dict(yaml.safe_load(archivos["discrepancias.yaml.txt"]))
    assert d.reglas["null"].tipo == "Datos 'especiales': auditor"


@pytest.mark.parametrize("cambios", [
    {"codigo": "intervalo_excedido"}, {"codigo": "../regla"},
    {"tipo": ""}, {"condicion": "no_contiene"}, {"campo": "inventado"},
    {"mensaje": "dos\nlineas"}, {"severidad": "GRAVE"},
])
def test_rechaza_datos_invalidos(cambios):
    with pytest.raises(ValueError):
        ejemplo(**cambios)
