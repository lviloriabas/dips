"""RIR en Follow-on Tasks: lectura, intervalo y reglas (casos tomados de ICAM)."""

import json
from datetime import date, datetime

import pytest

from dips_audit.auditor import Auditor
from dips_audit.icam import FichaICAM, Intervalo, TareaSiguiente, leer_tareas_siguientes
from dips_audit.rir import Limite, agrupar, requerido, revisar
from dips_audit.reglas import ResultadoReglas
from dips_audit.rir import RIR
from tests.conftest import crear_export, hacer_dip


def test_remanente_rir_inverosimil_del_excel(auditor, ctx):
    for remanente, sospechoso in [(-2778.4, True), (5000, True), (-1, False), (40, False)]:
        dip = hacer_dip(rirs=[RIR("RIR 50 FH", ["R1"], ["ACTV"],
                                  [Limite(50, "FH", restante=remanente)])])
        r = ResultadoReglas()
        auditor._rir(dip, auditor._asociar(dip), ctx, r)
        assert ("rir_restante_inverosimil" in {h.codigo for h in r.hallazgos}) is sospechoso


def test_remanente_rir_compara_cada_unidad_y_conserva_excel(auditor, ctx):
    excel = RIR("RIR", ["R1"], ["ACTV"], [Limite(50, "FH", restante=-2778.4)], "Excel")
    icam = RIR("RIR", ["R1"], ["ACTV"], [Limite(10000, "FC", restante=5000),
                                        Limite(50, "FH", restante=500)], "página del RIR")
    dip = hacer_dip(rirs=[icam], rirs_excel=[excel])
    r = ResultadoReglas()
    auditor._rir(dip, auditor._asociar(dip), ctx, r)
    mensajes = [h.mensaje for h in r.hallazgos if h.codigo == "rir_restante_inverosimil"]
    assert len(mensajes) == 2
    assert any("-2778.4 FH" in m and "Excel" in m for m in mensajes)
    assert any("500 FH" in m and "página del RIR" in m for m in mensajes)


def test_comentario_rir_no_menciona_excel_y_conserva_valores(auditor, ctx):
    dip = hacer_dip(rirs=[RIR("RIR", ["R1"], ["ACTV"],
                             [Limite(50, "FH", restante=-2778.4)], "Excel")])
    r = ResultadoReglas()
    auditor._rir(dip, auditor._asociar(dip), ctx, r)
    comentario = auditor._comentario(r)
    assert "excel" not in comentario.lower()
    assert "RIR R1 Usage Remaining -2778.4 FH" in comentario
    assert "intervalo de 50 FH" in comentario
    assert "Verificar configuración en ICAM" in comentario


def test_remanente_leido_de_scheduling_icam():
    detalle = FichaICAM(intervalos=[Intervalo("HOURS", "HOUR", "", 50, "", "", "", "-2,778.4")])
    rirs = agrupar([_t("RIR X", "A", "ACTV", "10 HOUR")], {"A": detalle})
    assert rirs[0].limites[0].restante == -2778.4


def _t(nombre, id_, estado, due, clase="ADHOC (Ad-Hoc Task)"):
    return leer_tareas_siguientes(
        "Name\tID\tTask Class\tTask Subclass\tTask Status1\tDue2\n"
        f"{nombre}\t{id_}\t{clase}\t \t{estado}\t{due}")[0]


def test_lee_follow_on_tasks_con_due_en_dos_lineas():
    texto = ("Name\tID\tTask Class\tTask Subclass\tTask Status1\tDue2\n"
             "RIR - EVERY 800FC\tT40S009BG69\tADHOC (Ad-Hoc Task)\t \tACTV\t594 CYCLES\n"
             "10-FEB-2027 23:59 UTC\n"
             "RIR - EVERY 800FC\tT40S009BG6A\tADHOC (Ad-Hoc Task)\t \tFORECAST\t1394 CYCLES\n"
             "25-AUG-2027 23:59 UTC\n"
             "TASK-11-01-SHOP-REQ (SHOP-OXYGEN CYLINDER SERVICING)\tT40S009C43H\tREQ (Requirement)\t \tACTV\t ")
    t = leer_tareas_siguientes(texto)
    assert [(x.id, x.estado, x.restante, x.unidad, x.fecha) for x in t[:2]] == [
        ("T40S009BG69", "ACTV", 594.0, "CYCLES", "10-FEB-2027 23:59 UTC"),
        ("T40S009BG6A", "FORECAST", 1394.0, "CYCLES", "25-AUG-2027 23:59 UTC")]
    assert [x.es_rir for x in t] == [True, True, False]   # REQ no es RIR


@pytest.mark.parametrize("actual, siguiente, esperado", [
    ("594 CYCLES", "1394 CYCLES", "800 FC"),                        # T40S009BG5B
    ("175.50 HOUR", "375.50 HOUR", "200 FH"),                       # T40S009CF2Z
    ("02-OCT-2026 23:59 UTC", "16-OCT-2026 23:59 UTC", "14 DAY"),   # T40S009CDAH
])
def test_intervalo_del_rir_entre_actv_y_forecast(actual, siguiente, esperado):
    rirs = agrupar([_t("RIR X", "A", "ACTV", actual), _t("RIR X", "B", "FORECAST", siguiente)])
    assert [str(l) for l in rirs[0].limites] == [esperado] and rirs[0].fuente == "ACTV/FORECAST"


def test_intervalo_de_la_pagina_del_rir_tiene_prioridad():
    detalle = FichaICAM(parent_assembly="ENG 1 ESN 660819", intervalos=[
        Intervalo("CYCLES", "CYCLE", "Aircraft 5947", 800.0, "", "", "", "")])
    rirs = agrupar([_t("RIR X", "A", "ACTV", "594 CYCLES"), _t("RIR X", "B", "FORECAST", "1400 CYCLES")],
                   {"A": detalle})
    assert [str(l) for l in rirs[0].limites] == ["800 FC"] and rirs[0].fuente == "página del RIR"
    assert rirs[0].parent == "ENG 1 ESN 660819"


def test_rir_requerido_de_la_tabla():
    assert str(requerido("1 DAY")) == "1 DAY" and str(requerido("100 FH")) == "100 FH"
    assert str(requerido("INSPECT WITHIN 50 FH")) == "50 FH"
    assert requerido("") is None


def _rirs(actual, siguiente):
    return agrupar([_t("RIR PARK BRAKE", "A", "ACTV", actual),
                    _t("RIR PARK BRAKE", "B", "FORECAST", siguiente)])


def test_rir_correcto_sin_hallazgos():
    rirs = _rirs("19-AUG-2026 23:59 UTC", "20-AUG-2026 23:59 UTC")
    assert revisar(rirs, requerido("1 DAY"), {"estado": "ACTV"}) == []


def test_rir_con_intervalo_distinto():
    rirs = _rirs("19-AUG-2026 23:59 UTC", "21-AUG-2026 23:59 UTC")
    [(codigo, mensaje)] = revisar(rirs, requerido("1 DAY"), {"estado": "ACTV"})
    assert codigo == "rir_intervalo_incorrecto" and "2 DAY; la referencia pide 1 DAY" in mensaje


def test_rir_faltante_en_dip_abierto():
    [(codigo, mensaje)] = revisar([], requerido("1 DAY"), {"estado": "ACTV"})
    assert codigo == "rir_faltante" and "cada 1 DAY" in mensaje


def test_dip_cerrado_sin_historico_no_se_marca():
    """Los RIR cerrados no se ven en Follow-on Tasks abiertas: sin el histórico no se sabe."""
    assert revisar([], requerido("1 DAY"), {"estado": "COMPLETE"}) == []
    assert revisar([], requerido("1 DAY"), {"estado": "COMPLETE", "historico_rir": True})[0][0] == \
        "rir_faltante"


def test_rir_en_meses_contra_dias():
    """T40S0099V81: RIR de 30 meses se ve como 913 días entre ACTV y FORECAST."""
    rirs = _rirs("12-JAN-2029 23:59 UTC", "14-JUL-2031 23:59 UTC")
    assert revisar(rirs, Limite(30, "MONTH"), {"estado": "ACTV"}) == []


def _con_pagina(limites, parent="Boeing 737-8V3 - HP-1837CMP"):
    detalle = FichaICAM(parent_assembly=parent, intervalos=[
        Intervalo(p, "", inicio, v, "", "", "", "") for v, p, inicio in limites])
    return agrupar([_t("RIR FLAP", "A", "ACTV", "10 CYCLES"), _t("RIR FLAP", "B", "FORECAST", "60 CYCLES")],
                   {"A": detalle})


def test_rir_sin_un_limite_del_ta():
    """T40S0099V81: 'RIRs aperturados solo con limitantes de ciclos. Agregar limitante de 30 Meses'."""
    dip = {"estado": "ACTV", "icam_intervalos": [{"parameter": "CYCLES", "start": "Aircraft 100"},
                                                 {"parameter": "CDY", "start": "01-AUG-2026"}]}
    hallazgos = revisar(_con_pagina([(50.0, "CYCLES", "Aircraft 100")]), None, dip)
    assert [c for c, _ in hallazgos] == ["rir_limite_faltante"] and "DAY" in hallazgos[0][1]


def test_rir_con_start_distinto_del_ta():
    """T40S009C3F0: 'RIRs de 200FH con START values diferentes al T/A ocasiona que corran mal'."""
    dip = {"estado": "ACTV", "icam_intervalos": [{"parameter": "HOURS", "start": "Aircraft 823.6"}]}
    hallazgos = revisar(_con_pagina([(200.0, "HOURS", "Aircraft 900.1")]), None, dip)
    assert [c for c, _ in hallazgos] == ["rir_inicio_distinto"]


@pytest.mark.parametrize("parametro", ["CDY", "CMON"])
@pytest.mark.parametrize("inicio_rir, inicio_ta, discrepancia", [
    ("18-AUG-2026 23:59 UTC", "21-AUG-2026 23:59 UTC", False),
    ("30-SEP-2026 23:59 UTC", "02-OCT-2026 23:59 UTC", False),
    ("30-DEC-2025 23:59 UTC", "02-JAN-2026 23:59 UTC", False),
    ("18-AUG-2026 10:00 UTC", "18-AUG-2026 23:59 UTC", False),
    ("21-AUG-2026 23:59 UTC", "18-AUG-2026 23:59 UTC", True),
])
def test_inicio_rir_calendario_puede_ser_anterior_al_ta(
        parametro, inicio_rir, inicio_ta, discrepancia):
    dip = {"estado": "ACTV", "icam_intervalos": [{"parameter": parametro, "start": inicio_ta}]}
    hallazgos = revisar(_con_pagina([(1.0, parametro, inicio_rir)]), None, dip)
    assert [c for c, _ in hallazgos] == (["rir_inicio_distinto"] if discrepancia else [])


@pytest.mark.parametrize("parametro", ["HOURS", "CYCLES"])
@pytest.mark.parametrize("inicio_rir, discrepancia", [
    ("Aircraft 90", True), ("Aircraft 110", True), ("Aircraft 100.01", False),
])
def test_inicio_rir_por_uso_conserva_comparacion_con_ta(parametro, inicio_rir, discrepancia):
    dip = {"estado": "ACTV", "icam_intervalos": [{"parameter": parametro, "start": "Aircraft 100"}]}
    hallazgos = revisar(_con_pagina([(50.0, parametro, inicio_rir)]), None, dip)
    assert [c for c, _ in hallazgos] == (["rir_inicio_distinto"] if discrepancia else [])


def test_auditor_acepta_ta_que_empieza_dias_despues_del_rir(auditor, ctx):
    dip = hacer_dip(nombre="DIP - PARKING BRAKE SYSTEM FNC FAIL HOLD CHECK",
                    icam_intervalos=[{"parameter": "CDY", "start": "21-AUG-2026 23:59 UTC"}],
                    rirs=_con_pagina([(1.0, "CDY", "18-AUG-2026 23:59 UTC")]))
    r = ResultadoReglas()
    auditor._rir(dip, auditor._asociar(dip), ctx, r)
    assert r.hallazgos == []


def test_rir_en_otro_parent_assembly():
    dip = {"estado": "ACTV", "parent_icam": "ENGINE 1 ESN 660819"}
    hallazgos = revisar(_con_pagina([(50.0, "CYCLES", "")], parent="Boeing 737-8V3 - HP-1837CMP"),
                        None, dip)
    assert [c for c, _ in hallazgos] == ["rir_parent_distinto"]


# ------------------------------------------------------------------ de punta a punta
FOLLOW_ON = ("Fault Status:\tDEFER (Defer)\tFault Severity:\tDIP (Defer Item Project)\n"
             "Follow-on Tasks\n"
             "Name\tID\tTask Class\tTask Subclass\tTask Status1\tDue2\n{filas}\n"
             "Component Faults")


def _registro(barcode, filas):
    return {"barcode": barcode, "sections": {
        "TaskExecution": {"text": "Description\nPARK BRK FAIL HOLD CHECK IAW AMM TASK 32-44-00-790-801 "
                                  "REV 90, 15-JUN-2026\nLabor"},
        "FaultInformation": {"text": FOLLOW_ON.format(filas=filas)},
        "TaskInformation": {"text": "Parent Assembly:\tBoeing 737-8V3 - HP-1837CMP\n\n"
                                    "Attachments\n\tName\tAttachment\tType\n\tAMM.png\t\tPIC\n"},
        "Scheduling": {"text": "\tDriver1\tParameter2\tUnit\tScheduled From\tStart\tInterval\tDeadline\n"
                               "\t\tCDY\tDAY\tCUSTOM\t18-AUG-2026 23:59 UTC\t3\t21-AUG-2026 23:59 UTC"},
        "History": {"text": "18-AUG-2026 09:05 UTC"}}}


def test_auditoria_con_rir_de_icam(config, tmp_path):
    avion = "Boeing 737-8V3 - HP-{}CMP"
    filas = []
    for n, b in enumerate(["P1", "P2", "P3"]):
        matricula = f"HP-18{n}0CMP"
        filas.append([b, 32, "Others", "DIP - PARKING BRAKE SYSTEM FNC FAIL HOLD CHECK", 3, "DAY", "ACTV",
                      matricula, avion.format(f"18{n}0"), "DIP", "32-DIP", datetime(2026, 8, 21, 23, 59),
                      datetime(2026, 8, 18, 23, 59), None, 2])
    ruta = crear_export(tmp_path / "entrada.xlsx", filas)
    rir = "RIR - PARK BRAKE\t{0}A\tADHOC (Ad-Hoc Task)\t \tACTV\t19-AUG-2026 23:59 UTC\n" \
          "RIR - PARK BRAKE\t{0}B\tADHOC (Ad-Hoc Task)\t \tFORECAST\t{1}-AUG-2026 23:59 UTC"
    carpeta = tmp_path / "icam"
    carpeta.mkdir()
    for b, filas_rir in [("P1", rir.format("P1", 20)), ("P2", rir.format("P2", 21)), ("P3", "")]:
        (carpeta / f"{b}.json").write_text(json.dumps(_registro(b, filas_rir)), encoding="utf-8")
    resultado = Auditor(config, fecha_auditoria=date(2026, 8, 20)).auditar_archivo(ruta, icam=carpeta)
    f = resultado.filas.set_index("Fault Barcode")
    assert f.loc["P1", "RESULTADO"] == "OK"
    assert f.loc["P1", "RIR EN ICAM"] == "RIR - PARK BRAKE (P1A, P1B): 1 DAY"
    assert "la referencia pide 1 DAY" in f.loc["P2", "HALLAZGOS"]
    assert f.loc["P2", "RESULTADO"] == "POSIBLE DISCREPANCIA"
    assert "Sin RIR; la referencia pide" in f.loc["P3", "HALLAZGOS"]
    assert f.loc["P3", "RIR EN ICAM"] == "Sin RIR"


def test_tablas_de_abiertas_e_historicas_en_la_misma_pagina():
    """ICAM trae seguidas la tabla de tareas abiertas y la de históricas, cada una con su
    encabezado: el segundo encabezado no es una tarea."""
    texto = ("Name\tID\tTask Class\tTask Subclass\tTask Status1\tDue2\n"
             "RIR - PARK BRAKE\tP1B\tADHOC (Ad-Hoc Task)\t\xa0\tACTV\t02-OCT-2026 23:59 UTC\n"
             "TASK-03-02-SHOP-REQ (SHOP)\tT1\tREQ (Requirement)\t\xa0\tACTV\t\xa0\n"
             "Name\tID\tTask Class\tTask Subclass\tTask Status\tCompleted\n"
             "RIR - PARK BRAKE\tP1A\tADHOC (Ad-Hoc Task)\t\xa0\tCOMPLETE\t01-OCT-2026 10:00 UTC\n"
             "\n"
             "Component Faults\n")
    tareas = leer_tareas_siguientes(texto)
    assert [(t.id, t.estado) for t in tareas] == [("P1B", "ACTV"), ("T1", "ACTV"), ("P1A", "COMPLETE")]
    assert [t.id for t in tareas if t.es_rir] == ["P1B", "P1A"]
    assert tareas[0].fecha == "02-OCT-2026 23:59 UTC"
    sin_historicas = texto.split("RIR - PARK BRAKE\tP1A")[0] + "There are no historical tasks.\n\n"
    assert [t.id for t in leer_tareas_siguientes(sin_historicas)] == ["P1B", "T1"]
