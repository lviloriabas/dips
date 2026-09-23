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
from dips_audit.auditor import RAIZ, Auditor
from dips_audit.evaluacion import evaluar, indicadores
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


def test_reglas_no_empeoran_la_linea_base(config):
    """Si un cambio intencional baja un indicador, ejecute benchmark.bat y copie el
    JSON del resultado sobre benchmark/linea_base.json."""
    base = bm.cargar_linea_base()
    assert base is not None, "Falta benchmark/linea_base.json"
    actuales = indicadores(evaluar(Auditor(config), bm.DATOS).metricas)
    previos = base["auditoria"]["indicadores_solo_reglas"]
    assert actuales["coincidencia"]["total"] == previos["coincidencia"]["total"]
    assert bm.comparar_indicadores(actuales, previos) == []


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


def test_benchmark_completo_con_modelo_simulado(config, tmp_path):
    lineas: list[str] = []
    avance = bm.Avance(lineas.append)
    plan = bm.preparar(config, ModeloFalso())
    r = bm.ejecutar(plan, avance)

    assert avance.hechas == plan.consultas_previstas > 0 and lineas
    assert r["modelo_local"] == {"modelo": "modelo-falso", "disponible": True, "motivo": ""}
    assert r["datos"]["dips"] == len(r["auditoria"]["dips"]) == 50
    assert r["casos_modelo"]["indicadores"]["aciertos_finales"]["total"] == len(plan.casos)
    # El modelo falso elige el primer candidato: igual que la alternativa sin modelo.
    assert r["casos_modelo"]["indicadores"] == r["casos_modelo"]["indicadores_sin_modelo"]
    assert r["costo_modelo"]["consultas"] == plan.consultas_previstas
    assert r["costo_modelo"]["s_por_consulta"] == 2.0
    assert r["costo_modelo"]["tokens_por_s_entrada"] == pytest.approx(266.7, abs=0.1)
    assert {"preparacion_s", "carga_modelo_s", "auditoria_s", "casos_s", "total_s"} <= set(
        r["tiempos"])
    # Todo lo que el modelo asocia queda en REVISAR o peor, nunca en OK.
    assert all(d["programa"] != "OK" for d in r["auditoria"]["dips"] if d["metodo"] != "reglas")

    ruta_json, ruta_md = bm.guardar(r, r, tmp_path)
    assert json.loads(ruta_json.read_text(encoding="utf-8")) == r
    md = ruta_md.read_text(encoding="utf-8")
    for seccion in ("## Resumen", "## Cómo se audita", "## 1. Resultado frente al auditor",
                    "## 2. Cómo se asoció", "## 3. Modelo local", "## 4. Tiempos",
                    "## 5. Configuración", "## 6. Desacuerdos"):
        assert seccion in md
    assert bm.empeoraron(r, r) == []
    assert "Ningún indicador empeoró" in md


def test_cli_benchmark_sin_modelo(tmp_path, monkeypatch, capsys):
    """Sin Ollama, el benchmark mide solo las reglas y lo avisa."""
    config = yaml.safe_load((RAIZ / "config" / "config.yaml").read_text(encoding="utf-8"))
    config["llm"]["url"] = "http://127.0.0.1:9"
    ruta = tmp_path / "config.yaml"
    ruta.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(bm, "RESULTADOS", tmp_path / "resultados")

    assert main(["--config", str(ruta), "benchmark"]) == 0
    salida = capsys.readouterr().out
    assert "Modelo local no disponible" in salida and "Ningún indicador empeoró" in salida
    assert len(list((tmp_path / "resultados").glob("*.json"))) == 1
    assert len(list((tmp_path / "resultados").glob("*.md"))) == 1


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


def test_cli_benchmark_no_tiene_opciones():
    with pytest.raises(SystemExit):
        main(["benchmark", "--llm"])


@pytest.mark.skipif(not HISTORICO.exists(), reason="No está el histórico de auditorías")
def test_anonimizar_reproduce_el_benchmark():
    anon = anonimizar(HISTORICO)
    guardado = pd.read_excel(bm.DATOS, sheet_name=HOJA)
    assert list(anon.tabla["Fault Barcode"]) == list(guardado["Fault Barcode"])
