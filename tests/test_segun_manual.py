"""Referencias con TA o RIR según el daño o el tipo: el DIP queda en REVISAR (ir al manual)."""

import pytest

from dips_audit.asociacion import Asociacion
from dips_audit.referencias import remite_al_manual
from dips_audit.reglas import Hallazgo, ResultadoReglas, auditar_dip, estado_final
from dips_audit.rir import RIR, Limite
from tests.conftest import hacer_dip


@pytest.mark.parametrize("texto, esperado", [
    ("25 FC DEPENDING ON MEASUREMENTS", True),
    ("7 DAYS OR 1 DAY, DEPENDING ON DAMAGE ZONE AND SIZE (CONSULT REF.)", True),
    ("10 FC, 350 FC OR BEFORE NEXT REVENUE FLIGHT. CONSULT SRM 53-00-01", True),
    ("DEPENDS ON DAMAGE SIZE", True),
    ("3 DAYS", False),
    ("2.0-2.9 VIBRATION UNITS: 7 DAYS; 3.0-3.4: 5 FC", False),
    ("", False),
])
def test_remite_al_manual(texto, esperado):
    assert remite_al_manual(texto) == esperado


def test_catalogo_marca_las_referencias_que_remiten_al_manual(catalogo):
    assert "DEPENDING" in catalogo.por_id("PLATAFORMA_ALABE").ta_segun_manual
    assert "DEPENDING" in catalogo.por_id("PLATAFORMA_ALABE").rir_segun_manual
    assert not catalogo.por_id("RAYO_DANO").ta_segun_manual
    assert "DEPENDING" in catalogo.por_id("GRIETA_TAPON_ESCAPE").rir_segun_manual
    # Resueltas en el catálogo con 'intervalos' (por presión, por vibración): no remiten.
    assert not catalogo.por_id("OXIGENO_TRIPULACION").ta_segun_manual
    assert not catalogo.por_id("VIBRACION_MOTOR").ta_segun_manual
    assert not catalogo.por_id("FDR").ta_segun_manual
    assert not any("PLATAFORMA_ALABE" in a or "RAYO_DANO" in a for a in catalogo.advertencias)


@pytest.mark.parametrize("intervalo, excedido", [(350, False), (351, True)])
def test_rayo_dano_usa_el_limite_vigente_de_350_fc(catalogo, ctx, intervalo, excedido):
    entrada = catalogo.por_id("RAYO_DANO")
    assert entrada.referencias_tecnicas == "SRM 53-00-01-1A-1"
    assert [(l.valor, l.unidad) for v in entrada.variantes for l in v.limites] == [(350, "FC")]
    dip = hacer_dip(nombre="LIGHTNING STRIKE FOUND", tipo="Structures", ata=53,
                    deferral_ref="53-DIP", intervalo=intervalo, unidad="FC",
                    tipo_intervalo_original="CYCLES", due_date=None, usage_remaining=None)
    resultado = auditar_dip(dip, entrada, ctx)
    codigos = {h.codigo for h in resultado.hallazgos}
    assert ("intervalo_excedido" in codigos) is excedido
    assert "intervalo_segun_manual" not in codigos


def _plataforma(**cambios):
    base = dict(nombre="DIP - ENG 1 OUTER PLATFORM LE AREA MISSING MATERIAL", intervalo=400.0,
                unidad="FC", tipo_intervalo_original="CYCLES", ata=72, deferral_ref="72-DIP",
                tipo="Powerplant", parent_tipo="ENGINE", due_date=None, usage_remaining=None)
    base.update(cambios)
    return hacer_dip(**base)


def test_ta_segun_el_dano_queda_en_revisar(catalogo, ctx):
    r = auditar_dip(_plataforma(), catalogo.por_id("PLATAFORMA_ALABE"), ctx)
    h = next(h for h in r.hallazgos if h.codigo == "intervalo_segun_manual")
    assert h.severidad == "REVISAR"
    assert "DEPENDING ON MEASUREMENTS" in h.mensaje and "72-00-00-200-818" in h.mensaje
    # No se compara con los 25 FC de la tabla: depende de la medición.
    assert not {x.codigo for x in r.hallazgos} & {"intervalo_excedido", "intervalo_menor"}
    assert not r.intervalo_ok


def test_revisar_pesa_menos_que_una_posible_discrepancia():
    manual = Hallazgo("intervalo_segun_manual", "Incorrect DIP Interval", "REVISAR", "")
    assert estado_final([manual]) == "REVISAR"
    assert estado_final([manual, Hallazgo("x", "", "OK", "")]) == "REVISAR"
    assert estado_final([manual, Hallazgo("x", "", "POSIBLE DISCREPANCIA", "")]) == "POSIBLE DISCREPANCIA"
    assert estado_final([manual, Hallazgo("x", "", "SIN FUENTE EN DIPS REFERENCES", "")]) == "REVISAR"


def test_rir_segun_el_dano_no_se_compara(auditor, catalogo, ctx):
    entrada = catalogo.por_id("GRIETA_TAPON_ESCAPE")
    dip = hacer_dip(nombre="EXHAUST PLUG CRACK", intervalo=None, unidad=None, rirs=[
        RIR("EXHAUST PLUG CRACK RIR", ["T1", "T2"], ["ACTV", "FORECAST"], [Limite(3, "DAY")])])
    r = ResultadoReglas(manuales=["Verificar RIR cada 7 DAYS."])
    auditor._rir(dip, Asociacion(entrada, "REGLAS"), ctx, r)
    assert [h.codigo for h in r.hallazgos] == ["rir_segun_manual"]
    assert r.hallazgos[0].severidad == "REVISAR"
    assert "DAMAGE ZONE" in r.hallazgos[0].mensaje and "3 DAY" in r.hallazgos[0].mensaje
    assert r.manuales == []
    # "Revisar en el manual" no va en el comentario sugerido.
    assert auditor._comentario(r) == ""


def test_rir_segun_el_dano_sin_datos_de_icam(auditor, catalogo, ctx):
    r = ResultadoReglas()
    auditor._rir(hacer_dip(), Asociacion(catalogo.por_id("GRIETA_TAPON_ESCAPE"), "REGLAS"), ctx, r)
    assert [h.codigo for h in r.hallazgos] == ["rir_segun_manual"]
    assert "En ICAM" not in r.hallazgos[0].mensaje
