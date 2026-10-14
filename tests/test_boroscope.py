"""Los DIPs de boroscope se siguen por RIR, sin controles de TA, salvo los que
piden el boroscope dentro de un plazo y lo siguen con el TA."""

from datetime import datetime

import pytest

from dips_audit.reglas import ResultadoReglas, auditar_dip
from dips_audit.reglas_descripcion import revisar_descripcion
from dips_audit.rir import Limite, RIR, revisar
from tests.conftest import crear_export, hacer_dip


def _dip(**cambios):
    base = dict(nombre="DIP - BOROSCOPE INSPECTION ENG 1", tipo="Powerplant",
                parent_tipo="ENGINE", parent_icam="ENGINE 1", intervalo=None, unidad=None,
                tipo_intervalo_original="", due_date=None, usage_remaining=None,
                rirs=[RIR("RIR BOROSCOPE", ["R1"], ["ACTV"], [Limite(400, "FC")])])
    base.update(cambios)
    return hacer_dip(**base)


@pytest.mark.parametrize("campo, texto", [
    ("nombre", "DIP - BOROSCOPE INSPECTION ENG 1"),
    ("nombre", "DIP - borescope inspection ENG 1"),
    ("descripcion", "Perform boroscope inspection ENG 1"),
    ("notas_descripcion", "Inspección de boroscopio ENG 1"),
])
def test_boroscope_no_exige_ta_aunque_la_tabla_lo_defina(catalogo, ctx, campo, texto):
    dip = _dip(nombre="ENGINE BIRDSTRIKE REPORT")
    dip[campo] = texto
    r = auditar_dip(dip, catalogo.por_id("BIRDSTRIKE_MOTOR"), ctx)
    assert "datos_incompletos" not in {h.codigo for h in r.hallazgos}
    assert r.intervalo_ok is None
    assert not any("T/A" in m or "Intervalo:" in m for m in r.manuales)


@pytest.mark.parametrize("estado", ["ACTV", "COMPLETE"])
def test_boroscope_no_valida_intervalo_inicio_ni_plazo_del_ta(catalogo, ctx, estado):
    dip = _dip(estado=estado, intervalo=900, unidad="DAY", tipo_intervalo_original="DAY",
               due_date=datetime(2026, 8, 19), orig_due_date=datetime(2026, 8, 18),
               scheduled_date=datetime(2026, 8, 25), usage_remaining=-1,
               complete_date=datetime(2026, 8, 24) if estado == "COMPLETE" else None,
               cambios_deadline=["Deadline changed"],
               icam_intervalos=[{"parameter": "CDY", "value": 900, "start": "01-AUG-2026"}])
    r = auditar_dip(dip, catalogo.por_id("BIRDSTRIKE_MOTOR"), ctx)
    codigos_ta = {"datos_incompletos", "intervalo_excedido", "tipo_intervalo_incorrecto",
                  "inicio_ta_incorrecto", "due_date_posterior_a_intervalo",
                  "due_date_anterior_a_intervalo", "dip_vencido", "programado_despues_del_due",
                  "completado_fuera_de_plazo", "cierre_deadline_extendido"}
    assert not codigos_ta & {h.codigo for h in r.hallazgos}
    assert not any("plazo" in m or "deadline" in m for m in r.manuales)
    assert r.intervalo_ok is None


def test_birdstrike_sin_boroscope_conserva_la_exigencia_de_ta(catalogo, ctx):
    r = auditar_dip(_dip(nombre="ENGINE BIRDSTRIKE REPORT"),
                    catalogo.por_id("BIRDSTRIKE_MOTOR"), ctx)
    assert "datos_incompletos" in {h.codigo for h in r.hallazgos}


def test_rir_de_boroscope_no_se_compara_con_ta_y_conserva_sus_controles():
    rir = RIR("RIR BOROSCOPE", ["R1"], ["ACTV"], [Limite(800, "FC", "Aircraft 900")],
              fuente="página del RIR", parent="ENGINE 2")
    dip = _dip(icam_intervalos=[{"parameter": "CYCLES", "start": "Aircraft 100"},
                               {"parameter": "CDY", "start": "01-AUG-2026"}])
    codigos = {codigo for codigo, _ in revisar([rir], Limite(400, "FC"), dip)}
    assert codigos == {"rir_intervalo_incorrecto", "rir_parent_distinto"}


def test_boroscope_sin_rir_se_marca_aunque_la_tabla_no_lo_defina(auditor, ctx):
    dip = _dip(nombre="DIP - BIRDSTRIKE BOROSCOPE ENGINE 1", rirs=[])
    r = ResultadoReglas()
    auditor._rir(dip, auditor._asociar(dip), ctx, r)
    assert [h.codigo for h in r.hallazgos] == ["rir_faltante"]


def test_boroscope_sin_datos_rir_deja_verificacion_manual(auditor, ctx):
    dip = _dip(rirs=None)
    r = ResultadoReglas()
    auditor._rir(dip, auditor._asociar(dip), ctx, r)
    assert not r.hallazgos
    assert any("Verificar RIR" in m for m in r.manuales)


def test_boroscope_cerrado_sin_historico_deja_rir_para_verificar(auditor, ctx):
    dip = _dip(estado="COMPLETE", rirs=[])
    r = ResultadoReglas()
    auditor._rir(dip, auditor._asociar(dip), ctx, r)
    assert not r.hallazgos
    assert any("Show Historical Tasks" in m for m in r.manuales)
    dip["historico_rir"] = True
    r = ResultadoReglas()
    auditor._rir(dip, auditor._asociar(dip), ctx, r)
    assert [h.codigo for h in r.hallazgos] == ["rir_faltante"]


def test_boroscope_sin_tabla_revisa_rir_de_descripcion_y_omite_ta(ctx):
    dip = _dip(descripcion="OPEN DIP FOR 5 DAYS. REPEAT INSPECTION EVERY 400 FC.",
               intervalo=100, unidad="DAY", tipo_intervalo_original="DAY",
               rirs=[RIR("RIR BOROSCOPE", ["R1"], ["ACTV"], [Limite(800, "FC")])])
    r = ResultadoReglas()
    revisar_descripcion(dip, None, ctx, r)
    assert {h.codigo for h in r.hallazgos} == {"rir_descripcion_distinto"}


def test_boroscope_no_omite_adjuntos_de_cierre(catalogo, ctx):
    dip = _dip(estado="COMPLETE", complete_date=datetime(2026, 8, 20), adjuntos=[])
    r = auditar_dip(dip, catalogo.por_id("BIRDSTRIKE_MOTOR"), ctx)
    assert "cierre_sin_adjuntos" in {h.codigo for h in r.hallazgos}


def test_boroscope_con_tabla_sin_rir_usa_el_periodo_de_la_descripcion(catalogo, ctx):
    dip = _dip(descripcion="REPEAT INSPECTION EVERY 400 FC.",
               rirs=[RIR("RIR BOROSCOPE", ["R1"], ["ACTV"], [Limite(800, "FC")])])
    r = ResultadoReglas()
    revisar_descripcion(dip, catalogo.por_id("BIRDSTRIKE_MOTOR"), ctx, r)
    assert {h.codigo for h in r.hallazgos} == {"rir_descripcion_distinto"}


_PLAZO = ("IN ACCORDANCE TO BC T40S009LALB OPEN DIP TO PERFORM A BOROSCOPE ON ENG 1 IN THE "
          "NEXT 25FH OR 10FC, WICH OCCURS FIRST IAW AMM 71-00-00-200-802-G00 REV 29")
_TA_DOBLE = [{"parameter": "CYCLES", "value": 10, "start": "Aircraft 2540"},
             {"parameter": "HOURS", "value": 25, "start": "Aircraft 7329.84"}]


def test_boroscope_con_plazo_y_ta_sin_rir_se_audita_por_el_ta(auditor, ctx):
    dip = _dip(nombre=_PLAZO, descripcion=_PLAZO, rirs=[], intervalo=10, unidad="FC",
               tipo_intervalo_original="CYCLES", icam_intervalos=_TA_DOBLE)
    r = ResultadoReglas()
    auditor._rir(dip, auditor._asociar(dip), ctx, r)
    revisar_descripcion(dip, None, ctx, r)
    assert not r.hallazgos
    assert any("coincide con el plazo de la descripción" in m for m in r.manuales)


def test_boroscope_con_plazo_revisa_que_el_ta_tenga_los_dos_limites(ctx):
    dip = _dip(nombre=_PLAZO, descripcion=_PLAZO, rirs=[], intervalo=10, unidad="FC",
               tipo_intervalo_original="CYCLES", icam_intervalos=_TA_DOBLE[:1])
    r = ResultadoReglas()
    revisar_descripcion(dip, None, ctx, r)
    assert {h.codigo for h in r.hallazgos} == {"limite_declarado_faltante"}


def test_boroscope_con_plazo_y_rir_se_sigue_por_el_rir(ctx):
    dip = _dip(nombre=_PLAZO, descripcion=_PLAZO, icam_intervalos=_TA_DOBLE[:1])
    r = ResultadoReglas()
    revisar_descripcion(dip, None, ctx, r)
    assert "limite_declarado_faltante" not in {h.codigo for h in r.hallazgos}


@pytest.mark.parametrize("rir_barcode, esperado", [("R1", "OK"),
                                                  (None, "POSIBLE DISCREPANCIA")])
def test_auditoria_excel_de_boroscope_sin_ta(auditor, tmp_path, rir_barcode, esperado):
    encabezado = ["Fault Barcode", "Fault Name", "Area", "DIP Interval", "Interval Type",
                  "Fault Status", "Aircraft", "Task Parent Assy", "Fault Description",
                  "Rir Barcode", "Rir Driver Interval", "Rir Driver Type"]
    fila = ["B1", "DIP - BIRDSTRIKE BOROSCOPE ENGINE 1", "Powerplant", None, None, "ACTV",
            "HP-1837CMP", "ENGINE 1", "REPEAT INSPECTION EVERY 400 FC.",
            rir_barcode, 400 if rir_barcode else None, "CYCLES" if rir_barcode else None]
    entrada = crear_export(tmp_path / "entrada.xlsx", [fila], encabezado=encabezado)
    resultado = auditor.auditar_archivo(entrada)
    actual = resultado.filas.iloc[0]
    assert actual["RESULTADO"] == esperado
    assert actual["TA SEGÚN REFERENCIA"] == "No aplica: solo RIR (boroscope)."
    assert "T/A aperturado correctamente" not in actual["COMENTARIO SUGERIDO"]
    codigos = set(resultado.hallazgos["Código"])
    assert "datos_incompletos" not in codigos
    assert "intervalo_segun_manual" not in codigos
    if not rir_barcode:
        assert "rir_faltante" in codigos
        assert "rir_descripcion_faltante" not in codigos
