"""Benchmark: datos anónimos, avance, resultado en JSON/Markdown y sin regresiones."""

from __future__ import annotations

import json

import openpyxl
import pandas as pd
import pytest
import yaml

from dips_audit import benchmark as bm
from dips_audit.__main__ import main
from dips_audit.anonimizar import (COLUMNAS_PERSONAL, HOJA, MARCA, Tachador, anonimizar,
                                   muestrear, nombres_del_personal)
from dips_audit.auditor import RAIZ
from dips_audit.llm import ClienteOllama, ErrorLLM, Medicion
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


def test_sin_modelo_no_empeora_la_linea_base(config):
    """Si un cambio intencional baja un indicador, ejecute benchmark_sin_modelo.bat y
    copie el JSON del resultado sobre benchmark/linea_base_sin_modelo.json."""
    base = bm.cargar_linea_base("sin_modelo")
    assert base is not None, "Falta benchmark/linea_base_sin_modelo.json"
    r = bm.ejecutar(bm.preparar(config), bm.Avance())
    assert bm.comparable(r, base) == ""
    assert bm.empeoraron(r, base) == []


def test_lineas_base_de_cada_modo():
    for modo in bm.MODOS:
        base = bm.cargar_linea_base(modo)
        assert base is not None and base["modo"] == modo
    assert bm.cargar_linea_base("con_modelo")["costo_modelo"]["consultas"] > 0
    assert bm.cargar_linea_base("sin_modelo")["costo_modelo"] is None


def test_avance_estima_lo_que_falta():
    avance = bm.Avance()
    avance.previstas = 10
    assert avance.faltante is None                  # sin corrida anterior ni consultas
    avance.referencia = 30.0                        # promedio de una corrida anterior
    assert avance.faltante == 300
    avance.hecha(20.0)
    avance.hecha(40.0)
    assert avance.por_consulta == 30.0 and avance.faltante == 240
    assert avance.total == pytest.approx(avance.transcurrido + 240, abs=0.5)
    assert bm.reloj(3725) == "1:02:05" and bm.aprox(None) == "calculando..."


class ModeloFalso:
    """Simula el modelo local: elige siempre el primer candidato y "tarda" 2 s."""

    modelo = "modelo-falso"

    def __init__(self):
        self.mediciones: list[Medicion] = []

    @property
    def consultas(self) -> int:
        return len(self.mediciones)

    def cargar(self) -> float:
        return 0.5

    def memoria(self):
        return 1.5, 0.0

    def descargar_de_memoria(self) -> None:
        pass

    def elegir_categoria(self, nombre, candidatos, intervalo=""):
        self.mediciones.append(Medicion(2.0, 400, 20, 1.5, 0.5))
        return candidatos[0], "prueba"


def test_benchmark_sin_modelo(config, tmp_path):
    plan = bm.preparar(config)
    r = bm.ejecutar(plan, bm.Avance())

    assert plan.modo == r["modo"] == "sin_modelo" and plan.consultas_previstas == 0
    assert r["modelo_local"] is None and r["costo_modelo"] is None
    assert "llm" not in r["configuracion"]
    assert "indicadores_solo_reglas" not in r["auditoria"]
    assert r["datos"]["dips"] == len(r["auditoria"]["dips"]) == 50
    assert {d["metodo"] for d in r["auditoria"]["dips"]} <= {"reglas", "sin_referencia"}
    # Sin modelo, las reglas (con tolerancia a errores de escritura) no aceptan referencias
    # equivocadas; los casos que no resuelven quedan sin referencia.
    ind = r["casos"]["indicadores"]
    assert "aciertos_modelo" not in ind and "comparacion" not in r["casos"]
    assert 0 < ind["con_referencia"]["aciertos"] < ind["con_referencia"]["total"]
    assert ind["sin_referencia"]["aciertos"] == ind["sin_referencia"]["total"]
    assert ind["errores_aceptados"]["aciertos"] == 0
    assert r["tiempos"]["auditoria_consultas"] == r["tiempos"].get("casos_consultas", 0) == 0

    ruta_json, ruta_md = bm.guardar(r, r, tmp_path)
    assert ruta_json.parent == tmp_path / "sin_modelo"
    md = ruta_md.read_text(encoding="utf-8")
    assert md.startswith("# Benchmark del auditor de DIPs: sin modelo local")
    for seccion in ("## Resumen", "## Cómo se audita", "## 1. Resultado frente al auditor",
                    "## 2. Cómo se asoció", "## 3. Casos", "## 4. Tiempos",
                    "## 5. Configuración", "## 6. Desacuerdos"):
        assert seccion in md
    assert "Modelo local" not in md and "Ningún indicador empeoró" in md


def test_benchmark_completo_con_modelo_simulado(config, tmp_path):
    lineas: list[str] = []
    avance = bm.Avance(lineas.append)
    plan = bm.preparar(config, ModeloFalso())
    r = bm.ejecutar(plan, avance)

    assert avance.hechas == plan.consultas_previstas > 0 and lineas
    assert r["modo"] == "con_modelo" and r["modelo_local"] == "modelo-falso"
    assert r["datos"]["dips"] == len(r["auditoria"]["dips"]) == 50
    casos = r["casos"]
    assert casos["indicadores"]["aciertos_finales"]["total"] == len(plan.casos)
    # El modelo falso elige el primer candidato: igual que la alternativa más parecida.
    sin_aciertos_modelo = {k: v for k, v in casos["indicadores"].items() if k != "aciertos_modelo"}
    assert sin_aciertos_modelo == casos["comparacion"]["mas_parecido"]
    # Solo reglas es lo que mide el modo sin modelo con los mismos casos.
    sin_modelo = bm.ejecutar(bm.preparar(config), bm.Avance())
    assert casos["comparacion"]["solo_reglas"] == sin_modelo["casos"]["indicadores"]
    assert r["auditoria"]["indicadores_solo_reglas"] == sin_modelo["auditoria"]["indicadores"]
    assert r["costo_modelo"]["consultas"] == plan.consultas_previstas
    assert r["costo_modelo"]["s_por_consulta"] == 2.0
    assert r["costo_modelo"]["tokens_por_s_entrada"] == pytest.approx(266.7, abs=0.1)
    assert {"preparacion_s", "carga_modelo_s", "auditoria_s", "casos_s", "total_s"} <= set(
        r["tiempos"])
    # Todo lo que el modelo asocia queda en REVISAR o peor, nunca en OK.
    assert all(d["programa"] != "OK" for d in r["auditoria"]["dips"] if d["metodo"] != "reglas")

    ruta_json, ruta_md = bm.guardar(r, r, tmp_path)
    assert ruta_json.parent == tmp_path / "con_modelo"
    assert json.loads(ruta_json.read_text(encoding="utf-8")) == r
    md = ruta_md.read_text(encoding="utf-8")
    assert md.startswith("# Benchmark del auditor de DIPs: con modelo local")
    for seccion in ("## Resumen", "## Cómo se audita", "## 1. Resultado frente al auditor",
                    "## 2. Cómo se asoció", "## 3. Casos", "## 4. Tiempos",
                    "## 5. Configuración", "## 6. Desacuerdos"):
        assert seccion in md
    assert "Solo reglas" in md and "Más parecido" in md
    assert bm.empeoraron(r, r) == []
    assert "Ningún indicador empeoró" in md
    # Un resultado no se compara con la línea base del otro modo.
    assert bm.comparable(r, sin_modelo) == "La línea base es de otro modo."


def _config_sin_ollama(tmp_path) -> str:
    config = yaml.safe_load((RAIZ / "config" / "config.yaml").read_text(encoding="utf-8"))
    config["llm"]["url"] = "http://127.0.0.1:9"
    ruta = tmp_path / "config.yaml"
    ruta.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return str(ruta)


def test_cli_benchmark_sin_modelo_no_usa_ollama(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bm, "RESULTADOS", tmp_path / "resultados")
    assert main(["--config", _config_sin_ollama(tmp_path), "benchmark", "sin-modelo"]) == 0
    salida = capsys.readouterr().out
    assert "Ningún indicador empeoró" in salida and "Modelo local no disponible" not in salida
    assert len(list((tmp_path / "resultados" / "sin_modelo").glob("*.json"))) == 1
    assert len(list((tmp_path / "resultados" / "sin_modelo").glob("*.md"))) == 1


def test_cli_benchmark_con_modelo_exige_ollama(tmp_path, monkeypatch, capsys):
    """Sin Ollama, el modo con modelo no se degrada a solo reglas: avisa y termina."""
    monkeypatch.setattr(bm, "RESULTADOS", tmp_path / "resultados")
    assert main(["--config", _config_sin_ollama(tmp_path), "benchmark", "con-modelo"]) == 1
    salida = capsys.readouterr().out
    assert "Modelo local no disponible" in salida and "benchmark_sin_modelo.bat" in salida
    assert not (tmp_path / "resultados").exists()


def test_consulta_al_modelo_se_reintenta_una_vez(catalogo, monkeypatch):
    """Una consulta que excede el tiempo (p. ej. el equipo se suspendió) se repite."""
    cliente = ClienteOllama("http://localhost:1", "modelo")
    llamadas = []

    def post(ruta, cuerpo):
        llamadas.append(ruta)
        if len(llamadas) % 2:
            raise TimeoutError("timed out")
        return {"message": {"content": '{"categoria": "FDR"}'}, "prompt_eval_count": 10}

    monkeypatch.setattr(cliente, "_post", post)
    elegido, _ = cliente.elegir_categoria("FDR REPORT", [catalogo.por_id("FDR")])
    assert elegido.id == "FDR" and len(llamadas) == 2 and cliente.consultas == 1

    monkeypatch.setattr(cliente, "_post", lambda ruta, cuerpo: (_ for _ in ()).throw(
        TimeoutError("timed out")))
    with pytest.raises(ErrorLLM, match="dos intentos"):
        cliente.elegir_categoria("OTRO", [catalogo.por_id("FDR")])


def test_cli_benchmark_exige_el_modo():
    for argumentos in (["benchmark"], ["benchmark", "--llm"], ["benchmark", "otro"]):
        with pytest.raises(SystemExit):
            main(argumentos)


@pytest.mark.skipif(not HISTORICO.exists(), reason="No está el histórico de auditorías")
def test_anonimizar_reproduce_el_benchmark():
    anon = anonimizar(HISTORICO)
    guardado = pd.read_excel(bm.DATOS, sheet_name=HOJA)
    assert list(anon.tabla["Fault Barcode"]) == list(guardado["Fault Barcode"])
