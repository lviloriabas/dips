from datetime import datetime

from dips_audit.reglas import auditar_dip, buscar_duplicados, buscar_sn_repetidos, estado_final
from tests.conftest import hacer_dip


def codigos(r, severidad=None):
    return {h.codigo for h in r.hallazgos if severidad is None or h.severidad == severidad}


def auditar(catalogo, ctx, id_entrada, **cambios):
    return auditar_dip(hacer_dip(**cambios), catalogo.por_id(id_entrada), ctx)


# --- Intervalo -------------------------------------------------------------

def test_intervalo_correcto(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION")
    assert r.intervalo_ok
    assert estado_final(r.hallazgos) == "OK"


def test_intervalo_excedido_es_critico(catalogo, ctx):
    r = auditar(catalogo, ctx, "FDR", nombre="FDR - REPORT", intervalo=45.0, ata=31,
                deferral_ref="31-DIP", due_date=datetime(2026, 10, 2, 23, 59))
    assert "intervalo_excedido" in codigos(r, "CRITICA")
    assert estado_final(r.hallazgos) == "DISCREPANCIA CRÍTICA"


def test_intervalo_menor_es_observacion(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", intervalo=2.0,
                due_date=datetime(2026, 8, 20, 23, 59))
    assert "intervalo_menor" in codigos(r, "OBSERVACION")
    assert estado_final(r.hallazgos) == "OK"


def test_variante_condicional_anota_psi(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", intervalo=1.0,
                due_date=datetime(2026, 8, 19, 23, 59))
    obs = [h for h in r.hallazgos if h.codigo == "variante_condicional"]
    assert obs and "950 PSI" in obs[0].mensaje


def test_tipo_de_intervalo_incorrecto(catalogo, ctx):
    r = auditar(catalogo, ctx, "BLEED_CTRL_CARD", nombre="AHM - BLEED CTRL CARD", intervalo=1.0,
                ata=36, deferral_ref="36-DIP")
    assert "tipo_intervalo_incorrecto" in codigos(r, "CRITICA")


def test_intervalo_cero(catalogo, ctx):
    r = auditar(catalogo, ctx, "DESGASTE_FRENOS", nombre="DIP - BRAKE #3", intervalo=0.0,
                unidad="FC", tipo_intervalo_original="CYCLES", ata=32, deferral_ref="32-DIP",
                due_date=None)
    assert "intervalo_cero" in codigos(r, "NO CRITICA")


def test_intervalo_por_flota(catalogo, ctx):
    comun = dict(nombre="DIP - BRAKE #3 WEAR PIN", unidad="FC", tipo_intervalo_original="CYCLES",
                 ata=32, deferral_ref="32-DIP", due_date=None, usage_remaining=None)
    assert auditar(catalogo, ctx, "DESGASTE_FRENOS", intervalo=42.0, flota="MAX", **comun).intervalo_ok
    r = auditar(catalogo, ctx, "DESGASTE_FRENOS", intervalo=42.0, flota="NG-800", **comun)
    assert "intervalo_excedido" in codigos(r)
    assert auditar(catalogo, ctx, "DESGASTE_FRENOS", intervalo=37.0, flota="NG-700", **comun).intervalo_ok


def test_intervalo_en_meses(catalogo, ctx):
    comun = dict(nombre="DIP- AILERON CONTROL CABLE RE-TENSION", ata=27, deferral_ref="27-DIP",
                 due_date=None, usage_remaining=None)
    for dias in (123, 179, 184):  # 4 meses o 6 meses
        assert auditar(catalogo, ctx, "CABLES_ALERON", intervalo=float(dias), **comun).intervalo_ok
    r = auditar(catalogo, ctx, "CABLES_ALERON", intervalo=200.0, **comun)
    assert "intervalo_excedido" in codigos(r)


def test_limite_dual_y_rir_quedan_como_verificacion_manual(catalogo, ctx):
    r = auditar(catalogo, ctx, "DPI", nombre="DIP - IDG DPI", intervalo=400.0, unidad="FH",
                tipo_intervalo_original="HOUR", ata=24, deferral_ref="24-DIP", due_date=None,
                usage_remaining=None)
    assert r.intervalo_ok
    assert any("RIR" in m for m in r.manuales)


# --- Fechas ----------------------------------------------------------------

def test_due_date_posterior_al_vencimiento_del_item(catalogo, ctx):
    r = auditar(catalogo, ctx, "HALON_PORTATIL",
                nombre="DIP HALON EXTINGUISHER S/N X-1 DUE DATE 20-SEP-2026", intervalo=39.0,
                ata=26, deferral_ref="26-DIP", due_date=datetime(2026, 9, 26, 23, 59),
                usage_remaining=37.0)
    assert "due_date_posterior_a_vencimiento_item" in codigos(r, "CRITICA")


def test_due_date_inconsistente_con_intervalo(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", due_date=datetime(2026, 8, 30, 23, 59))
    assert "due_date_posterior_a_intervalo" in codigos(r, "REVISAR")
    assert estado_final(r.hallazgos) == "REVISAR"


def test_dip_vencido(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", found_date=datetime(2026, 8, 10),
                due_date=datetime(2026, 8, 13, 23, 59))
    assert "dip_vencido" in codigos(r, "CRITICA")


def test_dip_completado_no_se_marca_vencido(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", estado="COMPLETE",
                found_date=datetime(2026, 8, 10), due_date=datetime(2026, 8, 13, 23, 59))
    assert "dip_vencido" not in codigos(r)


def test_completado_fuera_de_plazo(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", estado="COMPLETE",
                complete_date=datetime(2026, 8, 23))
    assert "completado_fuera_de_plazo" in codigos(r, "CRITICA")


def test_usage_remaining_mayor_que_intervalo(catalogo, ctx):
    r = auditar(catalogo, ctx, "AMORTIGUADOR_MLG", nombre="DIP-Right Main Landing Gear Shock Strut",
                intervalo=10.0, unidad="FC", tipo_intervalo_original="CYCLES", ata=32,
                deferral_ref="32-DIP", usage_remaining=20.0, due_date=None)
    assert "usage_remaining_mayor_a_intervalo" in codigos(r, "NO CRITICA")


# --- Parent assy, ATA, S/N ---------------------------------------------------

def test_parent_assy_incorrecto(catalogo, ctx):
    r = auditar(catalogo, ctx, "BLEED_FAMV", nombre="AHM - BLEED FAMV", intervalo=30.0,
                unidad="FH", tipo_intervalo_original="HOUR", ata=36, deferral_ref="36-DIP",
                due_date=None, usage_remaining=None)
    assert "parent_assy_incorrecto" in codigos(r, "CRITICA")


def test_parent_assy_flexible_es_observacion(catalogo, ctx):
    r = auditar(catalogo, ctx, "FILTRO_COMBUSTIBLE_MOTOR", nombre="DIP - ENGINE #1 FUEL FILTER",
                intervalo=75.0, unidad="FH", tipo_intervalo_original="HOUR", ata=73,
                deferral_ref="73-DIP", due_date=None, usage_remaining=None,
                parent_assy="(LH) CFM56-7B26E Engine (PN: CFM56-7B26E, SN: 660819)",
                parent_tipo="ENGINE")
    assert "parent_assy_incorrecto" in codigos(r, "OBSERVACION")


def test_deferral_reference_distinta_al_ata(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", deferral_ref="25-DIP")
    assert "deferral_reference_ata" in codigos(r, "NO CRITICA")


def test_sin_sn_es_observacion(catalogo, ctx):
    r = auditar(catalogo, ctx, "FAK", nombre="DIP-FWD FAK", intervalo=60.0, ata=25,
                deferral_ref="25-DIP", due_date=datetime(2026, 10, 17, 23, 59), usage_remaining=58.0)
    assert "sin_sn_en_descripcion" in codigos(r, "OBSERVACION")
    r = auditar(catalogo, ctx, "FAK", nombre="DIP-FWD FAK S/N FAK082", intervalo=60.0, ata=25,
                deferral_ref="25-DIP", due_date=datetime(2026, 10, 17, 23, 59), usage_remaining=58.0)
    assert "sin_sn_en_descripcion" not in codigos(r)


# --- Duplicados ------------------------------------------------------------

def test_duplicado_mismo_componente_activo(catalogo):
    oxi = catalogo.por_id("OXIGENO_TRIPULACION")
    a = hacer_dip(barcode="A", nombre="CREW OXYGEN 850 PSI")
    b = hacer_dip(barcode="B", nombre="DIP-CREW OXYGEN BOTTLE", found_date=datetime(2026, 8, 19))
    assert buscar_duplicados([a, b], [oxi, oxi]) == {1: ("A", "CREW OXYGEN 850 PSI")}


def test_no_duplicado_si_posicion_distinta(catalogo):
    mlg = catalogo.por_id("AMORTIGUADOR_MLG")
    a = hacer_dip(barcode="A", nombre="DIP - LEFT MAIN LANDING GEAR SHOCK STRUT")
    b = hacer_dip(barcode="B", nombre="DIP - RIGHT MAIN LANDING GEAR SHOCK STRUT")
    assert buscar_duplicados([a, b], [mlg, mlg]) == {}


def test_no_duplicado_si_distinto_vencimiento(catalogo):
    upk = catalogo.por_id("UPK")
    a = hacer_dip(barcode="A", nombre="DIP-UPK", due_date=datetime(2026, 11, 30))
    b = hacer_dip(barcode="B", nombre="DIP-UPK", due_date=datetime(2026, 10, 31))
    assert buscar_duplicados([a, b], [upk, upk]) == {}


def test_no_duplicado_si_uno_ya_se_cerro_otro_dia(catalogo):
    oxi = catalogo.por_id("OXIGENO_TRIPULACION")
    a = hacer_dip(barcode="A", estado="COMPLETE", found_date=datetime(2026, 8, 1))
    b = hacer_dip(barcode="B")
    assert buscar_duplicados([a, b], [oxi, oxi]) == {}


def test_sn_repetido_en_dos_dips(catalogo):
    a = hacer_dip(barcode="A", nombre="FAK 1 S/N CFAK187")
    b = hacer_dip(barcode="B", nombre="FAK 2 S/N CFAK187")
    c = hacer_dip(barcode="C", nombre="FAK 3 S/N CFAK999")
    assert buscar_sn_repetidos([a, b, c]) == {0: ["B"], 1: ["A"]}
