"""Referencia técnica del DIP frente a la tabla, y asociación con errores de escritura."""

from datetime import date, datetime

import pandas as pd
import pytest

from dips_audit.__main__ import main
from dips_audit.asociacion import asociar
from dips_audit.auditor import Auditor
from dips_audit.referencia_tecnica import (IndiceReferencias, buscar_referencia, cita_mgm,
                                          extraer_codigos, referencias_cargadas, revisar)
from tests.conftest import ENCABEZADO_ENTRADA, crear_export


@pytest.mark.parametrize("texto, codigos", [
    ("AMM TASK 32-44-00-790-801; ECRA 3244-0178C REV 4", ["AMM 32-44-00-790-801", "EC 3244-0178"]),
    ("B737-31-1-0003-U-JIC; MAX-31-1-0003-U-JIC", ["JIC 31-1-0003"]),
    ("AMM SUBTASK 28-11-00-839-001C1", ["AMM 28-11-00-839-001"]),
    ("AMM \t\nTASK 73-00-00-700-801-G00", ["AMM 73-00-00-700-801"]),
    ("EA 4700-0003C", ["EC 4700-0003"]),
    ("AMM 56-11-00-300-801; EC5600-0028C REV. 2", ["AMM 56-11-00-300-801", "EC 5600-0028"]),
    ("SRM 51-10-05-0G-0", ["SRM 51-10-05"]),
    ("-", []),
    (None, []),
])
def test_extraer_codigos(texto, codigos):
    assert extraer_codigos(texto) == codigos


@pytest.fixture(scope="module")
def indice(catalogo):
    return IndiceReferencias.desde_catalogo(catalogo)


def test_sin_dato_no_se_revisa(catalogo, indice):
    assert revisar(None, catalogo.por_id("OXIGENO_TRIPULACION"), catalogo, indice) is None


def test_sin_referencia_tecnica_es_discrepancia(catalogo, indice):
    r = revisar("", catalogo.por_id("OXIGENO_TRIPULACION"), catalogo, indice)
    assert r.codigo == "sin_referencia_tecnica" and "AMM 12-15-21-210-801" in r.mensaje


def test_referencia_correcta(catalogo, indice):
    r = revisar("AMM TASK 12-15-21-210-801 REV 85", catalogo.por_id("OXIGENO_TRIPULACION"),
                catalogo, indice)
    assert r.codigo is None


def test_referencia_de_otra_entrada_es_equivocada(catalogo, indice):
    """Cargaron la del amortiguador de nariz en un DIP de oxígeno de tripulación."""
    r = revisar("AMM 12-15-41-610-802", catalogo.por_id("OXIGENO_TRIPULACION"), catalogo, indice)
    assert r.codigo == "referencia_tecnica_equivocada"
    assert "NOSE LANDING GEAR SHOCK STRUT" in r.mensaje and "12-15-21-210-801" in r.mensaje


def test_referencia_de_otra_tabla_es_equivocada(catalogo, indice):
    r = revisar("ECRA 5600-0028C", catalogo.por_id("OXIGENO_TRIPULACION"), catalogo, indice)
    assert r.codigo == "referencia_tecnica_equivocada" and "Structures" in r.mensaje


def test_tarea_hermana_que_la_tabla_no_tiene(catalogo, indice):
    """Caso T40S009DV6S: la tarea de reemplazo en vez de la de servicio."""
    r = revisar("AMM 12-15-21-600-804", catalogo.por_id("OXIGENO_TRIPULACION"), catalogo, indice)
    assert r.codigo == "referencia_tecnica_mismo_tema" and "mismo tema" in r.mensaje


def test_referencia_compartida_por_varias_entradas(catalogo, indice):
    """Las SMT comparten AMM 05-00-00-750-801: es correcta para cualquiera de ellas."""
    assert revisar("AMM TASK 05-00-00-750-801", catalogo.por_id("BLEED_PM_SENSOR"),
                   catalogo, indice).codigo is None
    assert indice.entrada_unica(["AMM 05-00-00-750-801"]) is None


def test_sin_numero_en_la_tabla_no_se_revisa(catalogo, indice):
    """La tabla no define referencia técnica para el botiquín (FAK)."""
    assert revisar("", catalogo.por_id("FAK"), catalogo, indice) is None


@pytest.mark.parametrize("nombre, esperado", [
    ("DIP FUNIGATION DATE", "FUMIGACION"),
    ("P.O.B DUE DATE", "OXIGENO_PORTATIL"),
])
def test_asociacion_tolera_errores_de_escritura_y_siglas(catalogo, nombre, esperado):
    a = asociar(nombre, catalogo)
    assert a.metodo == "REGLAS" and a.entrada.id == esperado


def test_asociacion_aproximada_informa_la_palabra(catalogo):
    a = asociar("DIP FUNIGATION DATE", catalogo)
    assert "'FUNIGATION' se leyó como 'FUMIGATION'" in a.detalle
    assert asociar("CERTIFICATE OF FUMIGATION", catalogo).detalle == ""


def test_asociacion_aproximada_no_cambia_siglas_cortas(catalogo):
    """Un cambio de letra en una sigla es otra cosa (EMT no es EMK ni ELT)."""
    assert asociar("EMT KIT DUE", catalogo).entrada is None


AVION = "Boeing 737-8V3 - HP-1837CMP"


def _fila(barcode, nombre, intervalo, unidad, ata, referencia=None, matricula="HP-1837CMP"):
    avion = AVION.replace("HP-1837CMP", matricula)
    fila = [barcode, ata, "Others", nombre, intervalo, unidad, "ACTV", matricula, avion, "DIP",
            f"{ata}-DIP", datetime(2026, 8, 21, 23, 59), datetime(2026, 8, 18, 9, 0), None, 2]
    return fila + ([referencia] if referencia is not None else [])


def test_auditoria_con_referencia_tecnica_en_el_excel(config, tmp_path):
    filas = [
        _fila("R1", "CREW OXYGEN 850 PSI", 3, "DAY", 35,
              "AMM TASK 12-15-21-210-801 REV 85, 15-MAY-2026"),
        _fila("R2", "CREW OXYGEN 850 PSI", 3, "DAY", 35, "", "HP-1838CMP"),
        _fila("R5", "CREW OXYGEN 850 PSI", 3, "DAY", 35, "AMM TASK 12-15-21-210-801",
              "HP-1840CMP"),
        _fila("R3", "CREW OXYGEN 850 PSI", 3, "DAY", 35, "AMM TASK 12-15-41-610-802", "HP-1839CMP"),
        _fila("R4", "DIP - NOSE INTERNAL INSPECTION", 3, "CYCLES", 5, "AMM 05-51-18-210-801"),
    ]
    ruta = crear_export(tmp_path / "entrada.xlsx", filas,
                        encabezado=ENCABEZADO_ENTRADA + ["Technical References"])
    resultado = Auditor(config, fecha_auditoria=date(2026, 8, 20)).auditar_archivo(ruta)
    f = resultado.filas.set_index("Fault Barcode")
    assert "Technical Reference" not in f.loc["R1", "HALLAZGOS"]
    assert f.loc["R1", "RESULTADO"] == "OK"
    assert f.loc["R1", "REFERENCIA TÉCNICA DEL DIP"] == "AMM TASK 12-15-21-210-801 REV 85, 15-MAY-2026"
    # Sin datos de ICAM no se sabe si tiene captura adjunta: queda para verificar.
    assert f.loc["R2", "RESULTADO"] == "OK"
    assert "Verificar en ICAM la referencia técnica" in f.loc["R2", "VERIFICACIÓN MANUAL"]
    # AMM sin revisión ni fecha: no hace falta (revision_opcional en config.yaml).
    assert "Referencia técnica sin REV" not in f.loc["R5", "HALLAZGOS"]
    assert f.loc["R5", "RESULTADO"] == "OK"
    assert "NOSE LANDING GEAR SHOCK STRUT" in f.loc["R3", "HALLAZGOS"]
    # El nombre no alcanza, pero la tarea AMM del radomo identifica la referencia.
    assert f.loc["R4", "ASOCIACIÓN"] == "REF_TECNICA (ALTA)"
    assert f.loc["R4", "REFERENCIA TÉCNICA DEL DIP"] == "AMM 05-51-18-210-801"
    assert f.loc["R4", "RESULTADO"] == "OK"  # sin revisión ni fecha: solo observación


def test_cli_auditar_con_archivo_de_icam(tmp_path, capsys):
    ruta = crear_export(tmp_path / "entrada.xlsx", [
        _fila("I1", "CREW OXYGEN 850 PSI", 3, "DAY", 35, matricula="HP-1837CMP"),
        _fila("I2", "CREW OXYGEN 850 PSI", 3, "DAY", 35, matricula="HP-1838CMP"),
        _fila("I3", "CREW OXYGEN 850 PSI", 3, "DAY", 35, matricula="HP-1839CMP"),
    ])
    icam = tmp_path / "icam.csv"
    icam.write_text("barcode,technical_references\n"
                    "I1,\"AMM TASK 12-15-21-210-801 REV 85, 15-MAY-2026\"\nI2,\n",
                    encoding="utf-8")
    salida = tmp_path / "salida.xlsx"
    assert main(["auditar", str(ruta), "--icam", str(icam), "--salida", str(salida),
                 "--fecha", "2026-08-20"]) == 0
    assert "Datos de ICAM (icam.csv): 2 de 3 DIPs" in capsys.readouterr().out
    hoja = pd.read_excel(salida, sheet_name="Auditoría").set_index("Fault Barcode")
    assert hoja.loc["I1", "RESULTADO"] == "OK"
    # Sin referencia cargada, pero el CSV no dice si tiene captura adjunta: no se marca.
    assert hoja.loc["I2", "RESULTADO"] == "OK"
    assert hoja.loc["I3", "RESULTADO"] == "OK"  # no está en el archivo: no se revisa


@pytest.mark.parametrize("texto, esperado, falta", [
    ("IAW AMM TASK 12-15-21-200-801 (ADDED BY EC1215-0032C REV 2) REV 28, 15-MAY-2026",
     "AMM 12-15-21-200-801 · REV 28 · 15-MAY-2026", []),
    ("IAW 73-21-00-740-803-F00 STEP (A). C-2  Rev.90 / 15 Jun 2026",
     "AMM 73-21-00-740-803 · REV 90 · 15 JUN 2026", []),
    ("IAW FIM TASK 21-51-00-810-801 REVISION 12 DATED 01/08/2026",
     "FIM 21-51-00-810-801 · REV 12 · 01/08/2026", []),
    ("15-MAY-2026 REV 28 AMM 32-44-00-790-801", "AMM 32-44-00-790-801 · REV 28 · 15-MAY-2026", []),
    ("per AMM TASK 27-31-00-820-801 within 6 months", "AMM 27-31-00-820-801",
     ["REV", "fecha de la REV"]),
    ("AMM TASK 27-31-00-820-801 REV 90", "AMM 27-31-00-820-801 · REV 90", ["fecha de la REV"]),
])
def test_buscar_referencia(texto, esperado, falta):
    r = buscar_referencia(texto)
    assert str(r) == esperado and r.faltantes == falta


@pytest.mark.parametrize("texto, tipo, exigidos", [
    ("per AMM TASK 27-31-00-820-801", "AMM", []),
    ("SRM 51-10-05-0G-0", "SRM", []),
    ("IAW TASK CARD B737-31-1-0003-U-JIC", "TASK CARD", []),
    ("IAW TASK CARD 0003", "TASK CARD", []),
    ("FIM TASK 21-51-00-810-801", "FIM", ["REV", "fecha de la REV"]),
    ("IAW EC/RA 3244-0178C", "EC", ["REV", "fecha de la REV"]),
])
def test_revision_opcional_en_amm_srm_y_task_card(texto, tipo, exigidos):
    r = buscar_referencia(texto)
    assert r.tipo == tipo
    assert r.faltantes_exigidos({"AMM", "SRM", "TASK CARD"}) == exigidos
    assert r.faltantes_exigidos(()) == ["REV", "fecha de la REV"]  # la opción desactivada


def test_mgm_no_es_referencia_tecnica():
    r = buscar_referencia("IAW MGM 7.7 REVISION 12 DATED 01/08/2026")
    assert r.manual is None and extraer_codigos("MGM 7.7") == []
    assert referencias_cargadas("MGM 7.7; AMM TASK 12-15-21-210-801") == [
        "AMM TASK 12-15-21-210-801"]
    assert cita_mgm("", "IAW MGM 7.7") and not cita_mgm("AMM 12-15-21-210-801")


def test_apertura_solo_con_mgm_no_tiene_referencia(auditor, ctx):
    from dips_audit.reglas import ResultadoReglas
    from tests.conftest import hacer_dip

    dip = hacer_dip(descripcion="O2 850 PSI IAW MGM 7.7 REV 12, 15-MAY-2026",
                    referencia_tecnica="MGM 7.7", adjuntos=[], datos_referencia=True)
    asoc = asociar(dip["nombre"], auditor.catalogo)
    r = ResultadoReglas()
    auditor._referencia_tecnica(dip, asoc, ctx, r)
    h = next(h for h in r.hallazgos if h.codigo == "sin_referencia_tecnica")
    assert "MGM, que no es referencia técnica" in h.mensaje


def test_opcion_revision_opcional_en_la_auditoria(config, tmp_path):
    ruta = crear_export(tmp_path / "entrada.xlsx",
                        [_fila("M2", "CREW OXYGEN 850 PSI", 3, "DAY", 35,
                               "AMM TASK 12-15-21-210-801")],
                        encabezado=ENCABEZADO_ENTRADA + ["Technical References"])
    f = (Auditor(config, fecha_auditoria=date(2026, 8, 20)).auditar_archivo(ruta)
         .filas.set_index("Fault Barcode"))
    assert "Referencia técnica sin REV" not in f.loc["M2", "HALLAZGOS"]
    # Con la lista vacía, AMM también pide revisión y fecha.
    estricto = {**config, "referencia_tecnica": {"revision_opcional": []}}
    f = (Auditor(estricto, fecha_auditoria=date(2026, 8, 20)).auditar_archivo(ruta)
         .filas.set_index("Fault Barcode"))
    assert "[OBSERVACIÓN] Referencia técnica sin REV ni fecha de la REV" in f.loc["M2", "HALLAZGOS"]


def test_fecha_de_vencimiento_no_es_fecha_de_revision():
    r = buscar_referencia("Portable ELT battery due. SN: 15749, Battery Due: 31-JAN-2027")
    assert r.manual is None and r.fecha is None and len(r.faltantes) == 3


def test_busca_en_todos_los_campos_del_dip():
    r = buscar_referencia("REPLACE CREW OXYGEN BOTTLE", "AMM TASK 12-15-21-210-801",
                          "REV 85, 15-MAY-2026")
    assert r.faltantes == []


# Texto de las pestañas tal como lo copia el extractor (recortado de un DIP real).
SECCIONES = {
    "TaskExecution": {"text": "Description \n\nO2 850 PSI IAW AMM TASK 12-15-21-210-801 "
                              "REV 85, 15-MAY-2026\n\nLabor\n\n\tSkill\tStage\n"},
    "FaultInformation": {"text": "Selected Reference\n\nReference:\tTASK 12-15-21-210-801\n\n"
                                 "Fault Status:\tDEFER (Defer)\tFault Severity:\tDIP (Defer Item Project)\n"
                                 "Deferral Class:\tDIP-MEL\tMOC Authorization:\t\n"
                                 "Deferral Reference:\t35-DIP\tEvaluated:\t\n"},
    "TaskInformation": {"text": "Parent Assembly:\tBoeing 737-8V3 - HP-1837CMP\tConfig Slot:\t35\n"
                                "Technical References  \n\nDocument Reference:\tTASK 12-15-21-210-801\t\t\n"
                                "\xa0\tName\tHyperlink\tType\tIETM\n"
                                "\tDIP OPEN - RT AUDIT COMPLETED\t\xa0\tAUDITDIP\t\xa0\n\n"
                                "Attachments   \n\n \tName\tAttachment\tType\n"
                                "\tfoto.jpg\t\t \n\nZones\n"},
    "Scheduling": {"text": "Due\t\n\n\xa0\tDriver1\tParameter2\tUnit\tScheduled From\tStart\t"
                           "Interval\tDeadline\tExtension\tExtended Deadline\tUsage Remaining\n"
                           "\t\tCDY\tDAY\tCUSTOM\t18-AUG-2026 23:59 UTC\t3\t21-AUG-2026 23:59 UTC"
                           "\t0\t21-AUG-2026 23:59 UTC\t1"},
    "History": {"text": "18-AUG-2026 09:05 UTC\tX\tACTV\t\xa0\tDeferral Reason: Parts, "
                        "Deferral Notes: TASK 12-15-21-210-801\n\n"},
}


def test_lector_de_pestanas_de_icam():
    from dips_audit.icam import leer_ficha
    f = leer_ficha(SECCIONES, "J1")
    assert f.descripcion.startswith("O2 850 PSI")
    assert f.referencias_tecnicas == ["TASK 12-15-21-210-801"]
    assert f.marcas_auditoria == ["DIP OPEN - RT AUDIT COMPLETED"]
    assert f.adjuntos == ["foto.jpg"]
    assert [(i.valor, i.parametro) for i in f.intervalos] == [(3.0, "CDY")]
    assert f.deferral_reference == "35-DIP" and f.notas_diferimiento == "TASK 12-15-21-210-801"


def test_lector_une_limites_por_uso_en_una_fila():
    from dips_audit.icam import leer_ficha
    texto = ("\xa0\tDriver1\tParameter2\tUnit\tScheduled From\tStart\tInterval\tDeadline\n"
             "\t\tHOURS\tHOUR\tCUSTOM\t\nAircraft:\xa0\t823.6\nAssembly:\xa0\t823.6\n"
             "Component:\xa0\t823.6\n\t201\t\nAircraft:\xa0\t1024.6\n\t0")
    f = leer_ficha({"Scheduling": texto})
    assert [(i.valor, i.parametro) for i in f.intervalos] == [(201.0, "HOURS")]
    assert f.intervalos[0].inicio == "Aircraft 823.6 / Assembly 823.6 / Component 823.6"


def test_json_de_icam_completa_referencia_descripcion_e_intervalo(config, tmp_path):
    import json
    ruta = crear_export(tmp_path / "entrada.xlsx", [
        _fila("J1", "CREW OXYGEN 850 PSI", None, None, 35, matricula="HP-1837CMP"),
        _fila("J2", "CREW OXYGEN 850 PSI", 3, "DAY", 35, matricula="HP-1838CMP"),
    ])
    datos = {"records": [
        {"barcode": "J1", "icam_capture_status": "six_tabs", "icam_detail": {"sections": SECCIONES}},
        {"barcode": "J2", "icam_capture_status": "excel_only"},
    ]}
    icam = tmp_path / "icam.json"
    icam.write_text(json.dumps(datos), encoding="utf-8")
    resultado = Auditor(config, fecha_auditoria=date(2026, 8, 20)).auditar_archivo(ruta, icam=icam)
    f = resultado.filas.set_index("Fault Barcode")
    assert f.loc["J1", "DIP Interval"] == 3
    assert "se usó el de ICAM" in f.loc["J1", "HALLAZGOS"]
    assert f.loc["J1", "RESULTADO"] == "OK"
    assert f.loc["J1", "ADJUNTOS EN ICAM"] == "1: foto.jpg"
    # J2 solo vino del Excel: no hay datos de ICAM y no se revisa la referencia.
    assert f.loc["J2", "REFERENCIA TÉCNICA DEL DIP"] == "" and f.loc["J2", "ADJUNTOS EN ICAM"] == ""
    assert any("intervalo tomado de ICAM en 1" in n for n in resultado.advertencias)


def test_carpeta_del_extractor(config, tmp_path):
    """El extractor deja un JSON por DIP en una carpeta; --icam acepta la carpeta."""
    import json
    carpeta = tmp_path / "icam"
    carpeta.mkdir()
    (carpeta / "J1.json").write_text(json.dumps({"barcode": "J1", "sections": SECCIONES}),
                                     encoding="utf-8")
    ruta = crear_export(tmp_path / "entrada.xlsx", [_fila("J1", "CREW OXYGEN 850 PSI", 3, "DAY", 35)])
    resultado = Auditor(config, fecha_auditoria=date(2026, 8, 20)).auditar_archivo(ruta, icam=carpeta)
    fila = resultado.filas.set_index("Fault Barcode").loc["J1"]
    assert fila["REFERENCIA TÉCNICA DEL DIP"] == "TASK 12-15-21-210-801; Adjunto: foto.jpg"


def test_sin_referencia_con_datos_de_icam(config, tmp_path):
    """Con ICAM: sin referencia cargada, sin captura adjunta y sin cita, es discrepancia.
    La task card JIC de la descripción es donde se encontró la falla, no la referencia."""
    import json
    secciones = dict(SECCIONES)
    secciones["TaskExecution"] = ("Description\nDURING TASK CARD B737-35-1-0001-U-JIC WAS FOUND "
                                  "CREW OXYGEN 850 PSI\n\nLabor\n")
    secciones["TaskInformation"] = "Parent Assembly:\tBoeing 737-8V3 - HP-1837CMP\n"
    secciones["FaultInformation"] = "Fault Status:\tDEFER (Defer)\n"
    secciones["History"] = ""
    carpeta = tmp_path / "icam"
    carpeta.mkdir()
    (carpeta / "J1.json").write_text(json.dumps({"barcode": "J1", "sections": secciones}),
                                     encoding="utf-8")
    ruta = crear_export(tmp_path / "entrada.xlsx", [_fila("J1", "CREW OXYGEN 850 PSI", 3, "DAY", 35)])
    resultado = Auditor(config, fecha_auditoria=date(2026, 8, 20)).auditar_archivo(ruta, icam=carpeta)
    fila = resultado.filas.set_index("Fault Barcode").loc["J1"]
    assert "Sin referencia técnica: no está cargada en ICAM" in fila["HALLAZGOS"]
    codigos = set(resultado.hallazgos["Código"])
    assert not codigos & {"referencia_tecnica_equivocada", "referencia_tecnica_distinta"}


def test_url_de_pestana_sin_enlace():
    """Si ICAM no trae el enlace de una pestaña, se arma con aTab sobre la URL del DIP."""
    from dips_audit.extractor_icam import _consulta
    url = "https://x.ifs.cloud/maintenix/web/task/TaskDetails.jsp?aTask=%7BA%7D&aTab=idTabTaskExecution"
    consulta = _consulta(url, "Scheduling")
    assert consulta == "aTask=%7BA%7D&aTab=idTabScheduling"
