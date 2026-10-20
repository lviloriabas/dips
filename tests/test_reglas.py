from dataclasses import replace
from datetime import date, datetime

import pytest

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


def test_comentario_intervalo_incompleto_pide_verificar_en_icam(auditor, catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", intervalo=None, unidad=None)
    assert "datos_incompletos" in codigos(r)
    comentario = auditor._comentario(r)
    assert "excel" not in comentario.lower()
    assert "Verificar el intervalo y el tipo de intervalo del T/A en ICAM." in comentario


def test_intervalo_excedido_es_posible_discrepancia(catalogo, ctx):
    r = auditar(catalogo, ctx, "FDR", nombre="FDR - REPORT", intervalo=45.0, ata=31,
                deferral_ref="31-DIP", due_date=datetime(2026, 10, 2, 23, 59))
    assert "intervalo_excedido" in codigos(r, "POSIBLE DISCREPANCIA")
    assert estado_final(r.hallazgos) == "POSIBLE DISCREPANCIA"


def test_intervalo_menor_queda_ok(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", intervalo=2.0,
                due_date=datetime(2026, 8, 20, 23, 59))
    assert "intervalo_menor" in codigos(r, "OK")
    assert estado_final(r.hallazgos) == "OK"


def test_variante_condicional_anota_psi(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", intervalo=1.0,
                due_date=datetime(2026, 8, 19, 23, 59))
    obs = [h for h in r.hallazgos if h.codigo == "variante_condicional"]
    assert obs and "950 PSI" in obs[0].mensaje


def test_tipo_de_intervalo_incorrecto(catalogo, ctx):
    r = auditar(catalogo, ctx, "BLEED_CTRL_CARD", nombre="AHM - BLEED CTRL CARD", intervalo=1.0,
                ata=36, deferral_ref="36-DIP")
    assert "tipo_intervalo_incorrecto" in codigos(r, "POSIBLE DISCREPANCIA")


def test_intervalo_cero(catalogo, ctx):
    r = auditar(catalogo, ctx, "DESGASTE_FRENOS", nombre="DIP - BRAKE #3", intervalo=0.0,
                unidad="FC", tipo_intervalo_original="CYCLES", ata=32, deferral_ref="32-DIP",
                due_date=None)
    assert "intervalo_cero" in codigos(r, "POSIBLE DISCREPANCIA")


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
    assert "due_date_posterior_a_vencimiento_item" in codigos(r, "POSIBLE DISCREPANCIA")


def test_due_date_inconsistente_con_intervalo(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", due_date=datetime(2026, 8, 30, 23, 59))
    assert "due_date_posterior_a_intervalo" in codigos(r, "POSIBLE DISCREPANCIA")
    assert estado_final(r.hallazgos) == "POSIBLE DISCREPANCIA"


def test_dip_vencido(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", found_date=datetime(2026, 8, 10),
                due_date=datetime(2026, 8, 13, 23, 59))
    assert "dip_vencido" in codigos(r, "POSIBLE DISCREPANCIA")


def test_dip_completado_no_se_marca_vencido(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", estado="COMPLETE",
                found_date=datetime(2026, 8, 10), due_date=datetime(2026, 8, 13, 23, 59))
    assert "dip_vencido" not in codigos(r)


def test_completado_fuera_de_plazo(catalogo, ctx):
    """En un DIP cerrado, Usage Remaining es lo que le quedaba al cerrarlo: negativo = tarde."""
    cierre = dict(estado="COMPLETE", complete_date=datetime(2026, 8, 23))
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", usage_remaining=-1.0, **cierre)
    assert "completado_fuera_de_plazo" in codigos(r, "POSIBLE DISCREPANCIA")
    # Caso T40S0095NQC: cerrado 06:29 UTC del día siguiente, con 0 remanente en ICAM.
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", usage_remaining=0.0, estado="COMPLETE",
                complete_date=datetime(2026, 8, 22, 6, 29),
                orig_due_date=datetime(2026, 8, 21, 23, 59))
    assert "completado_fuera_de_plazo" not in codigos(r)
    assert "cierre_deadline_extendido" not in codigos(r)  # due = original: no se extendió


def test_cierre_tarde_en_otra_tarea_queda_para_verificar(catalogo, ctx):
    """Caso T40S00992SM: el trabajo se hizo en otra tarea; la fecha que cuenta es la de esa."""
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", usage_remaining=-5.0, estado="COMPLETE",
                complete_date=datetime(2026, 8, 26), accion_correctiva=(
                    "1. JUAN PEREZ (Technician), 26-AUG-2026 17:27 UTC\nTHIS ITEM WILL BE "
                    "ACCOMPLISHED IN THIS BARCODE TRF7N0071057 STEP 9."))
    assert "completado_fuera_de_plazo" not in codigos(r)
    assert any("otra tarea (TRF7N0071057)" in m for m in r.manuales)


def test_vencido_segun_la_hora_de_auditoria(catalogo, ctx):
    # Vence el 20-ago 23:59: auditado ese día no está vencido; al día siguiente, sí.
    ctx.fecha_referencia = datetime(2026, 8, 20, 18, 0)
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", found_date=datetime(2026, 8, 17),
                due_date=datetime(2026, 8, 20, 23, 59))
    assert "dip_vencido" not in codigos(r)
    ctx.fecha_referencia = datetime(2026, 8, 21, 0, 30)
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", found_date=datetime(2026, 8, 17),
                due_date=datetime(2026, 8, 20, 23, 59))
    assert "dip_vencido" in codigos(r, "POSIBLE DISCREPANCIA")


def test_cierre_con_tolerancia_de_horas(catalogo, ctx):
    """Sin Usage Remaining, se compara la hora de cierre con el due date."""
    ctx.horas_cierre = 5  # Complete Dt en UTC, due en hora local
    cierre = dict(estado="COMPLETE", due_date=datetime(2026, 8, 21, 23, 59), usage_remaining=None)
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", complete_date=datetime(2026, 8, 22, 4, 12), **cierre)
    assert "completado_fuera_de_plazo" not in codigos(r)
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", complete_date=datetime(2026, 8, 22, 6, 0), **cierre)
    assert "completado_fuera_de_plazo" in codigos(r, "POSIBLE DISCREPANCIA")


@pytest.mark.parametrize("restante", [None, 0.0, 2.0])
def test_cierre_dentro_de_extension_queda_ok(catalogo, ctx, auditor, restante):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", estado="COMPLETE",
                due_date=datetime(2026, 8, 25, 23, 59), orig_due_date=datetime(2026, 8, 21, 23, 59),
                complete_date=datetime(2026, 8, 24, 10, 0), usage_remaining=restante)
    assert "cierre_deadline_extendido" in codigos(r, "OK")
    assert "completado_fuera_de_plazo" not in codigos(r)
    assert estado_final(r.hallazgos) == "OK"
    h = next(h for h in r.hallazgos if h.codigo == "cierre_deadline_extendido")
    assert "dentro del plazo extendido" in h.mensaje
    assert "exten" not in auditor._comentario(r).lower()


@pytest.mark.parametrize("due, completo, tarde", [
    (datetime(2026, 8, 25, 23, 59), datetime(2026, 8, 26, 4, 59), False),
    (datetime(2026, 8, 25, 23, 59), datetime(2026, 8, 26, 5, 0), True),
    (date(2026, 8, 25), datetime(2026, 8, 26, 4, 59, 59), False),
    (date(2026, 8, 25), datetime(2026, 8, 26, 5, 0), True),
])
def test_cierre_respeta_limite_extendido_y_tolerancia(catalogo, ctx, due, completo, tarde):
    ctx.horas_cierre = 5
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", estado="COMPLETE",
                due_date=due, orig_due_date=datetime(2026, 8, 21, 23, 59),
                complete_date=completo, usage_remaining=None)
    if tarde:
        assert "completado_fuera_de_plazo" in codigos(r, "POSIBLE DISCREPANCIA")
        assert "cierre_deadline_extendido" not in codigos(r)
    else:
        assert "cierre_deadline_extendido" in codigos(r, "OK")
        assert estado_final(r.hallazgos) == "OK"


def test_extension_con_usage_remaining_negativo_sigue_fuera_de_plazo(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", estado="COMPLETE",
                due_date=datetime(2026, 8, 25, 23, 59), orig_due_date=datetime(2026, 8, 21, 23, 59),
                complete_date=datetime(2026, 8, 24, 10, 0), usage_remaining=-1.0)
    assert "completado_fuera_de_plazo" in codigos(r, "POSIBLE DISCREPANCIA")
    assert "cierre_deadline_extendido" not in codigos(r)


def test_extension_no_oculta_due_original_incorrecto(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", estado="COMPLETE",
                due_date=datetime(2026, 8, 28, 23, 59), orig_due_date=datetime(2026, 8, 24, 23, 59),
                complete_date=datetime(2026, 8, 26, 10, 0))
    h = next(h for h in r.hallazgos if h.codigo == "due_date_posterior_a_intervalo")
    assert h.severidad == "POSIBLE DISCREPANCIA"
    assert "Due date original 24-AUG-2026" in h.mensaje
    assert "cierre_deadline_extendido" in codigos(r, "OK")


def test_cierre_con_datos_de_icam(catalogo, ctx):
    base = dict(estado="COMPLETE", complete_date=datetime(2026, 8, 21, 10, 0),
                descripcion="CREW OXYGEN BOTTLE S/N ABC123 950 PSI")
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", accion_correctiva="BOTTLE REPLACED",
                sn_removidos=[("801307-00", "XYZ999")], adjuntos=[], **base)
    assert codigos(r) >= {"cierre_sin_referencia_tecnica", "cierre_sn_distinto", "cierre_sin_adjuntos"}
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION",
                accion_correctiva="REPLACED IAW AMM 35-11-11-000-801 REV 75 DATED 15-JUN-2026",
                sn_removidos=[("801307-00", "ABC123")], adjuntos=["EVIDENCIA.PDF"], **base)
    assert not codigos(r) & {"cierre_sin_referencia_tecnica", "cierre_referencia_incompleta",
                             "cierre_sn_distinto", "cierre_sin_adjuntos"}


def test_cierre_sn_cuenta_el_numero_y_el_instalado(catalogo, ctx):
    """Mismo número con otro prefijo, o el S/N de la botella que se puso: no es distinto."""
    base = dict(estado="COMPLETE", complete_date=datetime(2026, 8, 21, 10, 0),
                descripcion="CREW OXYGEN BOTTLE S/N P11101989 950 PSI")
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", sn_removidos=[("801307-00", "11101989")], **base)
    assert "cierre_sn_distinto" not in codigos(r)
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", sn_removidos=[("801307-00", "55555")],
                sn_instalados=[("801307-00", "11101989")], **base)
    assert "cierre_sn_distinto" not in codigos(r)


def test_lote_de_squib_no_se_compara_como_serial(catalogo, ctx):
    r = auditar(catalogo, ctx, "SQUIB_MOTOR_APU", nombre="DIP - ENGINE SQUIB S/N2 00875",
                descripcion="SQUIB #2 P/N2 33700002 S/N2 00875", estado="COMPLETE",
                accion_correctiva="REPLACED SQUIB P/N M30903872 BATCH BN 335023",
                sn_removidos=[("M30903872", "BN 335023")],
                complete_date=datetime(2026, 8, 21, 10, 0))
    assert "cierre_sn_distinto" not in codigos(r)


def test_squib_con_seriales_ambiguos_y_pn_analogo(catalogo, ctx):
    r = auditar(catalogo, ctx, "SQUIB_MOTOR_APU", nombre="SQUIB S/N2: 00875",
                descripcion="SQUIB P/N2: M30903872A", notas_descripcion="S/N 99999",
                estado="COMPLETE", accion_correctiva="REPLACED P/N M30903872",
                sn_removidos=[("M30903872", "335023")],
                analogos_pn={"M30903872": ["M30903872A"]})
    assert not {"sn_inconsistente", "cierre_sn_distinto", "sin_sn_en_descripcion"} & codigos(r)
    assert any("M30903872A (análogo de M30903872 en ICAM)" in m for m in r.manuales)


def test_squib_sin_tabla_de_analogos_queda_para_verificar(catalogo, ctx):
    r = auditar(catalogo, ctx, "SQUIB", nombre="SQUIB P/N2: M30903872A")
    assert any("Verificar P/N y análogos: M30903872A" in m for m in r.manuales)


def test_cierre_sin_accion_correctiva_queda_ok(catalogo, ctx):
    """Sin acción correctiva no es discrepancia (se cierra por la validación de QC o solo con
    partes): OK. Sin cita del manual, también."""
    base = dict(estado="COMPLETE", complete_date=datetime(2026, 8, 21, 10, 0), adjuntos=["A.PDF"])
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION",
                accion_correctiva="1. JUAN PEREZ (Technician), 21-AUG-2026 10:00 UTC\n", **base)
    assert "cierre_sin_accion_correctiva" in codigos(r, "OK")
    assert estado_final(r.hallazgos) == "OK"
    assert "cierre_sin_referencia_tecnica" not in codigos(r)
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", accion_correctiva="BOTTLE REPLACED", **base)
    assert "cierre_sin_referencia_tecnica" in codigos(r, "OK")


def test_cierre_con_mgm_o_amm_sin_revision(catalogo, ctx):
    base = dict(estado="COMPLETE", complete_date=datetime(2026, 8, 21, 10, 0), adjuntos=["A.PDF"])
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION",
                accion_correctiva="BOTTLE REPLACED IAW MGM 7.7 REV 12 15-MAY-2026", **base)
    h = next(h for h in r.hallazgos if h.codigo == "cierre_sin_referencia_tecnica")
    assert "el MGM no es referencia técnica" in h.mensaje
    accion = "BOTTLE REPLACED IAW AMM 35-11-11-000-801"
    assert "cierre_referencia_incompleta" in codigos(
        auditar(catalogo, ctx, "OXIGENO_TRIPULACION", accion_correctiva=accion, **base))
    opcional = replace(ctx, revision_opcional=frozenset({"AMM"}))
    assert "cierre_referencia_incompleta" not in codigos(
        auditar(catalogo, opcional, "OXIGENO_TRIPULACION", accion_correctiva=accion, **base))


def test_cierre_sin_icam_no_revisa_accion_correctiva(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", estado="COMPLETE",
                complete_date=datetime(2026, 8, 21, 10, 0))
    assert not {c for c in codigos(r) if c.startswith("cierre_")}


def test_usage_remaining_mayor_que_intervalo(catalogo, ctx):
    r = auditar(catalogo, ctx, "AMORTIGUADOR_MLG", nombre="DIP-Right Main Landing Gear Shock Strut",
                intervalo=10.0, unidad="FC", tipo_intervalo_original="CYCLES", ata=32,
                deferral_ref="32-DIP", usage_remaining=20.0, due_date=None)
    # Los auditores lo aceptan (el T/A empieza después de la apertura): OK.
    assert "usage_remaining_mayor_a_intervalo" in codigos(r, "OK")


def test_due_date_desde_el_start_del_ta_en_icam(catalogo, ctx):
    """FDR abierto el 19-sep con 30 días: vence el 19-oct. Con el Start de ICAM el due date
    cuenta desde ese Start; sin ICAM, desde la apertura."""
    fdr = dict(nombre="DIP - FDR - Report", intervalo=30.0, ata=31, deferral_ref="31-DIP",
               found_date=datetime(2026, 9, 19, 7, 52), due_date=datetime(2026, 10, 19, 23, 59),
               usage_remaining=27.0)
    fechas = {"due_date_posterior_a_intervalo", "due_date_anterior_a_intervalo"}
    r = auditar(catalogo, ctx, "FDR", **fdr)
    assert not codigos(r) & fechas
    assert "intervalo_menor" not in codigos(r)
    icam = [{"value": 30.0, "parameter": "CDY", "unit": "DAY", "start": "19-SEP-2026 23:59 UTC"}]
    r = auditar(catalogo, ctx, "FDR", icam_intervalos=icam, **fdr)
    assert not codigos(r) & (fechas | {"inicio_ta_incorrecto"})
    # Con el due date de otro mes, sí.
    r = auditar(catalogo, ctx, "FDR", **{**fdr, "due_date": datetime(2026, 11, 19, 23, 59)})
    assert "due_date_posterior_a_intervalo" in codigos(r, "POSIBLE DISCREPANCIA")


def test_due_date_de_items_con_vencimiento_no_se_cuenta_por_intervalo(catalogo, ctx):
    """EMK: el due date es el vencimiento del kit, no apertura + intervalo."""
    r = auditar(catalogo, ctx, "EMK", nombre="DIP-25 EMERGENCY MEDICAL KIT", intervalo=14.0,
                ata=25, deferral_ref="25-DIP", found_date=datetime(2026, 9, 12, 4, 41),
                due_date=datetime(2026, 11, 30, 23, 59), usage_remaining=69.0,
                descripcion="EMK S/N:EMK-JY31 DUE DATE:30-NOV-26")
    assert not codigos(r) & {"due_date_posterior_a_intervalo", "due_date_posterior_a_vencimiento_item"}


# --- Parent assy, ATA, S/N ---------------------------------------------------

def test_parent_assy_incorrecto(catalogo, ctx):
    # BLEED PRSOV CTRL: ENGINE en la tabla (fila 46); el DIP está en el avión.
    r = auditar(catalogo, ctx, "BLEED_PRSOV", nombre="AHM - BLEED PRSOV CTRL", intervalo=2902.0,
                unidad="FH", tipo_intervalo_original="HOUR", ata=36, deferral_ref="36-DIP",
                due_date=None, usage_remaining=None)
    assert "parent_assy_incorrecto" in codigos(r, "POSIBLE DISCREPANCIA")


def test_parent_assy_flexible_queda_ok(catalogo, ctx):
    r = auditar(catalogo, ctx, "FILTRO_COMBUSTIBLE_MOTOR", nombre="DIP - ENGINE #1 FUEL FILTER",
                intervalo=75.0, unidad="FH", tipo_intervalo_original="HOUR", ata=73,
                deferral_ref="73-DIP", due_date=None, usage_remaining=None,
                parent_assy="(LH) CFM56-7B26E Engine (PN: CFM56-7B26E, SN: 660819)",
                parent_tipo="ENGINE")
    assert "parent_assy_incorrecto" in codigos(r, "OK")


_LONG_TIME = dict(intervalo=400.0, unidad="FH", tipo_intervalo_original="HOURS", ata=78,
                  deferral_ref="78-DIP", due_date=None, usage_remaining=None, flota="NG-800")
_MOTOR = dict(parent_assy="(RH) CFM56-7B26/3 Engine (PN: CFM56-7B26/3, SN: 805540)",
              parent_tipo="ENGINE")


def test_long_time_del_reversor_va_en_el_avion(catalogo, ctx):
    """T40S009L5CA: la tabla dice ENGINE, pero el reversor es del avión."""
    reversor = ("During engine 2 bite check MSG NBR 78-11482 was shows. 78-11482 THE L REVERSER "
                "SLEEVE POSITION SIGNAL IS OUT OF RANGE 78-36 TASK 802.")
    nombre = "DIP- ENG 2 LONG TIME MSG NBR 78-11482"
    en_avion = auditar(catalogo, ctx, "MENSAJE_LONG_TIME", nombre=nombre, descripcion=reversor,
                       parent_assy="Boeing 737-86N - HP-1824CMP", **_LONG_TIME)
    assert "parent_assy_incorrecto" not in codigos(en_avion)
    en_motor = auditar(catalogo, ctx, "MENSAJE_LONG_TIME", nombre=nombre, descripcion=reversor,
                       **_LONG_TIME, **_MOTOR)
    assert "parent_assy_incorrecto" in codigos(en_motor, "POSIBLE DISCREPANCIA")
    # "REVERSE SLEEVE" en el Fault Name (T40S009JB2T).
    r = auditar(catalogo, ctx, "MENSAJE_LONG_TIME", **_LONG_TIME, **_MOTOR,
                nombre="MAREP - ENG 1 LONG TIME MESSAGE L REVERSE SLEEVE")
    assert "parent_assy_incorrecto" in codigos(r, "POSIBLE DISCREPANCIA")


def test_long_time_de_otro_sistema_sigue_en_el_motor(catalogo, ctx):
    tbv = "MSG NBR 75-20592 THE TBV POSITION SIGNAL IS OUT OF RANGE 75-23 TASK 802"
    nombre = "DIP- ENG 2 LONG TIME MSG NUMBER 75-20592"
    en_motor = auditar(catalogo, ctx, "MENSAJE_LONG_TIME", nombre=nombre, descripcion=tbv,
                       **_LONG_TIME, **_MOTOR)
    assert "parent_assy_incorrecto" not in codigos(en_motor)
    en_avion = auditar(catalogo, ctx, "MENSAJE_LONG_TIME", nombre=nombre, descripcion=tbv,
                       parent_assy="Boeing 737-86N - HP-1824CMP", **_LONG_TIME)
    assert "parent_assy_incorrecto" in codigos(en_avion, "POSIBLE DISCREPANCIA")


def test_deferral_reference_distinta_al_ata(catalogo, ctx):
    """El ATA del DIP no es relevante para la auditoría: OK."""
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", deferral_ref="25-DIP")
    assert "deferral_reference_ata" in codigos(r, "OK")
    assert estado_final(r.hallazgos) == "OK"


def test_sin_sn_queda_ok(catalogo, ctx):
    r = auditar(catalogo, ctx, "FAK", nombre="DIP-FWD FAK", intervalo=60.0, ata=25,
                deferral_ref="25-DIP", due_date=datetime(2026, 10, 17, 23, 59), usage_remaining=58.0)
    assert "sin_sn_en_descripcion" in codigos(r, "OK")
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


def test_no_duplicado_si_es_otra_etapa_de_la_referencia(catalogo):
    """T40S009FEV9 / FEVN: 1er re-torque a los 60 días y 2do a los 12 meses, misma puerta."""
    puerta = catalogo.por_id("RETORQUE_PUERTA_TANQUE")
    a = hacer_dip(barcode="A", nombre="DIP - RE-TORQUE CENTER TANK ACCESS DOOR PANELS 531AB",
                  intervalo=60.0, unidad="DAY")
    b = hacer_dip(barcode="B", nombre="DIP - RE-TORQUE CENTER TANK ACCESS DOOR PANELS 531AB",
                  intervalo=365.0, unidad="DAY")
    assert buscar_duplicados([a, b], [puerta, puerta]) == {}


def test_no_duplicado_si_son_otros_mensajes(catalogo):
    """T40S009J2CX / J2CZ: SHORT TIME 75-20451 y 75-10451 del mismo motor."""
    st = catalogo.por_id("SHORT_TIME")
    a = hacer_dip(barcode="A", nombre="DIP-ENGINE 1 BITE TEST RECENT FAULTS",
                  descripcion="SHORTIME MSG NUMBER 75-20451", intervalo=100.0, unidad="FH")
    b = hacer_dip(barcode="B", nombre="DIP-ENGINE 1 BITE TEST RECENT FAULTS",
                  descripcion="SHORTIME MSG NUMBER 75-10451", intervalo=100.0, unidad="FH")
    assert buscar_duplicados([a, b], [st, st]) == {}
    b["descripcion"] = "SHORTIME MSG NUMBER 75-20451"
    assert buscar_duplicados([a, b], [st, st]) == {1: ("A", a["nombre"])}


def test_no_duplicado_si_uno_ya_se_cerro_otro_dia(catalogo):
    oxi = catalogo.por_id("OXIGENO_TRIPULACION")
    a = hacer_dip(barcode="A", estado="COMPLETE", found_date=datetime(2026, 8, 1))
    b = hacer_dip(barcode="B")
    assert buscar_duplicados([a, b], [oxi, oxi]) == {}


def test_no_duplicado_si_se_cerro_antes_de_abrir_el_otro(catalogo):
    """Caso T40S009J1RE / J29L: cerrado "OPEN BY MISTAKE" a las 05:29, reabierto a las 05:32."""
    oxi = catalogo.por_id("OXIGENO_TRIPULACION")
    a = hacer_dip(barcode="A", estado="COMPLETE", found_date=datetime(2026, 9, 23, 3, 18),
                  complete_date=datetime(2026, 9, 23, 5, 29))
    b = hacer_dip(barcode="B", found_date=datetime(2026, 9, 23, 5, 32))
    assert buscar_duplicados([a, b], [oxi, oxi]) == {}
    a["complete_date"] = datetime(2026, 9, 23, 13, 7)  # se solapan: sí es duplicado
    assert buscar_duplicados([a, b], [oxi, oxi]) == {1: ("A", a["nombre"])}


def test_no_duplicado_si_la_descripcion_dice_otro_componente(catalogo):
    """Caso T40S009HA18 / HA20: los dos squibs (LEFT y RIGHT) de la misma botella."""
    squib = catalogo.por_id("SQUIB_MOTOR_APU")
    nombre = "DIP-Engine LEFT Fire Extinguisher Bottle SQUIB"
    a = hacer_dip(barcode="A", nombre=nombre,
                  descripcion="WAS FOUND (LEFT SQUIB) OF LEFT Engine Fire Extinguisher Bottle")
    b = hacer_dip(barcode="B", nombre=nombre,
                  descripcion="WAS FOUND (RIGHT SQUIB) OF LEFT Engine Fire Extinguisher Bottle")
    assert buscar_duplicados([a, b], [squib, squib]) == {}
    b["descripcion"] = a["descripcion"] + " SERVICE VISIT #2 STEP 3"  # los números no cuentan
    assert buscar_duplicados([a, b], [squib, squib]) == {1: ("A", nombre)}


def test_sn_repetido_en_dos_dips(catalogo):
    a = hacer_dip(barcode="A", nombre="FAK 1 S/N CFAK187")
    b = hacer_dip(barcode="B", nombre="FAK 2 S/N CFAK187")
    c = hacer_dip(barcode="C", nombre="FAK 3 S/N CFAK999")
    assert buscar_sn_repetidos([a, b, c]) == {0: ["B"], 1: ["A"]}
