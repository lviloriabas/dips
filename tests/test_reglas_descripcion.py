"""Reglas que van más allá de la auditoría manual: el DIP contra su propia descripción,
contra sus pares del archivo y contra las filas Powerplant y Structures de la tabla.
Cada caso es un DIP real de las auditorías del 23 y el 28-sep-2026."""

from datetime import date, datetime

import pytest

from dips_audit.asociacion import asociar
from dips_audit.limites_declarados import LimiteDeclarado, extraer_limites, fechas_de_vencimiento
from dips_audit.reglas import ResultadoReglas, auditar_dip
from dips_audit.reglas_descripcion import buscar_parent_distinto_de_pares, revisar_descripcion
from dips_audit.rir import RIR, Limite, _mismo_inicio, revisar
from tests.conftest import hacer_dip
from tests.test_reglas import auditar, codigos


def _lims(texto):
    return [[str(l) for l in lims] for _, lims in extraer_limites(texto).plazos]


# --- Lo que declara la descripción ----------------------------------------------------------

@pytest.mark.parametrize("texto, plazos, repetitivos", [
    ("IN NO MORE THAN 100FH,50FC OR 10 DAYS WICHEVER OCCURS FIRST", [["100 FH", "50 FC", "10 DAY"]], []),
    ("open DIP for 45 days or 225 FC to proactively replace", [["45 DAY", "225 FC"]], []),
    ("ENTER IN DIP FOR 90 DAYS AND DETAILED VISUAL INSPECTION EVERY 30 DAYS", [["90 DAY"]], [["30 DAY"]]),
    ("OPEN A DIP TO inspect within 50 flight hours and correct within 100 flight hours",
     [["100 FH"]], [["50 FH"]]),
    ("tap test inspections every 6,875 flight cycles or 30 months", [], [["6875 FC", "30 MONTH"]]),
    # FDR: "not prior to 7 days" es cuándo consultar a Ingeniería, no el plazo.
    ("contact Engineering not prior to 7 days after data download. DIP is due 30 days.", [["30 DAY"]], []),
    # Punto de miles: cincuenta mil ciclos.
    ("THRESHOLD INSPECTION IN 50.000 FC", [["50000 FC"]], []),
    ("WITH LESS THAN 130 DAYS REMAIN ON EXPIRE DATE", [], []),
])
def test_extrae_los_limites_que_declara_el_dip(texto, plazos, repetitivos):
    d = extraer_limites(texto)
    assert [[str(l) for l in lims] for _, lims in d.plazos] == plazos
    assert [[str(l) for l in lims] for _, lims in d.repetitivos] == repetitivos


@pytest.mark.parametrize("texto, fechas", [
    ("(4 E/A) DUE DATE NOVEMBER/2027 P/N E72280-00 AND (1 E/A) DUE DATE: OCTOBER/2027 P/N",
     [date(2027, 11, 30), date(2027, 10, 31)]),
    ("A group of Oxygen Generators with DUE DATE 11/2029 - SN: BEFM", [date(2029, 11, 30)]),
    ("Expire Date or Due Date : 30-SEP -2026", [date(2026, 9, 30)]),
    ("NEXT HYDRO DATE LESS THAN 60 DAYS (31-OCT-2026)", [date(2026, 10, 31)]),
    ("DIP for 4 days from 22-SEP-2026", []),        # una fecha de inicio no es vencimiento
])
def test_fechas_de_vencimiento(texto, fechas):
    assert fechas_de_vencimiento(texto) == fechas


def _revisar(**cambios):
    from dips_audit.auditor import Auditor, cargar_configuracion
    ctx = Auditor(cargar_configuracion()).contexto(date(2026, 9, 23))
    r = ResultadoReglas()
    revisar_descripcion(hacer_dip(**cambios), None, ctx, r)
    return r


def test_intervalo_mayor_que_la_descripcion():
    """TRF7N0093QRX: 'replacement of the buckle within 180 days of this inspection', T/A 184 días."""
    r = _revisar(nombre="DIP-FIRST OFFICER ROTARY BUCKLE", intervalo=184.0,
                 descripcion="Open a deferral item for replacement of the buckle within 180 days of this inspection")
    assert "intervalo_mayor_a_descripcion" in codigos(r, "POSIBLE DISCREPANCIA")
    r = _revisar(nombre="DIP-FIRST OFFICER ROTARY BUCKLE", intervalo=180.0,
                 descripcion="replacement of the buckle within 180 days of this inspection")
    assert not codigos(r) and any("coincide" in m for m in r.manuales)


def test_unidad_distinta_de_la_descripcion():
    r = _revisar(nombre="DIP - ENGINE BITE", intervalo=100.0, unidad="FC", tipo_intervalo_original="CYCLES",
                 descripcion="INSPECT AND CORRECT WITHIN 100 FLIGHT HOURS")
    assert "tipo_intervalo_distinto_a_descripcion" in codigos(r)


def test_limite_dual_de_la_descripcion():
    """ECRA 7300-0132C: 'open DIP for 45 days or 225 FC'. Con ICAM se ve si el T/A tiene los dos;
    sin ICAM (el Excel solo trae el que vence primero) queda para verificar."""
    texto = "Per CFM recommendation IAW ECRA 7300-0132C, open DIP for 45 days or 225 FC"
    base = dict(nombre="ENG 2 FUEL NOZZLES FULL SET REPLACEMENT", intervalo=45.0, descripcion=texto)
    solo_dias = [{"value": 45.0, "parameter": "CDY", "start": "15-SEP-2026 23:59 UTC"}]
    assert "limite_declarado_faltante" in codigos(_revisar(icam_intervalos=solo_dias, **base))
    ambos = solo_dias + [{"value": 225.0, "parameter": "CYCLES", "start": "Aircraft 2504"}]
    assert not codigos(_revisar(icam_intervalos=ambos, **base))
    r = _revisar(**base)
    assert not codigos(r) and any("verificar en ICAM" in m for m in r.manuales)


def test_inspeccion_repetitiva_que_pide_la_descripcion():
    """T40S0098GDE: 'FOR 90 DAYS AND DETAILED VISUAL INSPECTION EVERY 30 DAYS'."""
    texto = "THIS FAULT ENTER IN DIP FOR 90 DAYS AND DETAILED VISUAL INSPECTION EVERY 30 DAYS AFTER"
    base = dict(nombre="SHEET METAL - STRUCTURE", intervalo=90.0, descripcion=texto)
    assert "rir_descripcion_faltante" in codigos(_revisar(rirs=[], **base))
    rir = RIR("RIR - DVI", ["R1"], ["ACTV"], [Limite(30, "DAY")], fuente="Excel")
    assert not codigos(_revisar(rirs=[rir], **base))
    otro = RIR("RIR - DVI", ["R1"], ["ACTV"], [Limite(60, "DAY")], fuente="Excel")
    assert "rir_descripcion_distinto" in codigos(_revisar(rirs=[otro], **base))
    # Sin datos de RIR (ni ICAM ni columnas Rir del Excel) queda para verificar.
    assert any("inspección repetitiva" in m for m in _revisar(**base).manuales)


def test_vencimiento_de_un_grupo_de_componentes():
    """TRF7N006JANB: generadores con DUE DATE NOVEMBER/2027 y uno OCTOBER/2027; el DIP vence
    el 31-ene-2028."""
    texto = ("OXYGEN GENERATORS (4 E/A). DUE DATE NOVEMBER/2027 P/N E72280-00. S/N BEND-F029-144. "
             "AND (1 E/A) DUE DATE: OCTOBER/2027 P/N E72280-00.")
    r = _revisar(nombre="200- Oxygen generators.", intervalo=1442.0, descripcion=texto,
                 found_date=datetime(2024, 2, 19), due_date=datetime(2028, 1, 31, 23, 59))
    h = next(h for h in r.hallazgos if h.codigo == "due_date_posterior_a_vencimiento_item")
    assert "31-OCT-2027" in h.mensaje


def test_dip_sin_ta():
    assert "datos_incompletos" in codigos(_revisar(nombre="DENT ON SKIN", intervalo=None, unidad=None,
                                                   rirs=[]))
    rir = RIR("RIR 400 FC", ["R1"], ["ACTV"], [Limite(400, "FC")])
    assert not codigos(_revisar(nombre="HPT BLADES CRACK", intervalo=None, unidad=None, rirs=[rir]))
    # Abierto y cerrado el mismo día (EEC CREDENTIAL SYSTEM CHECK): se acepta.
    assert not codigos(_revisar(nombre="EEC CREDENTIAL", intervalo=None, unidad=None, rirs=[],
                                estado="COMPLETE", found_date=datetime(2026, 9, 13, 0, 24),
                                complete_date=datetime(2026, 9, 13, 0, 56)))


def test_en_la_tabla_manda_la_tabla(catalogo, ctx):
    r = ResultadoReglas()
    revisar_descripcion(hacer_dip(descripcion="within 1 days"), catalogo.por_id("OXIGENO_TRIPULACION"), ctx, r)
    assert not r.hallazgos


# --- Pares del mismo archivo ----------------------------------------------------------------

def test_parent_distinto_de_los_pares():
    """Seis cambios de toberas por la ECRA 7300-0132C: cinco en el motor y uno en el avión."""
    texto = "Per CFM recommendation and I.A.W ECRA 7300-0132C, open DIP for 45 days or 225 FC"
    motor = "(RH) ENGINE EQUIPED (MAX PART) (PN: LEAP-1B28, SN: 60A587)"
    dips = [hacer_dip(barcode=f"T{i}", descripcion=texto, parent_assy=motor) for i in range(3)]
    dips.append(hacer_dip(barcode="T9", descripcion=texto, parent_assy="Boeing 737-9 MAX9 - HP-9920CMP"))
    assert buscar_parent_distinto_de_pares(dips, [None] * 4) == {3: ("ENGINE", 3, "EC 7300-0132")}
    # Una AMM genérica (mensajes AHM de sistemas distintos) no sirve de par.
    amm = "IN REF WITH AMM 05-00-00-750-801 REV 28"
    dips = [hacer_dip(descripcion=amm, parent_assy=motor) for _ in range(3)] + [hacer_dip(descripcion=amm)]
    assert buscar_parent_distinto_de_pares(dips, [None] * 4) == {}


# --- Reglas generales nuevas ----------------------------------------------------------------

def test_paquete_programado_despues_del_due(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", scheduled_date=datetime(2026, 8, 23, 3, 0),
                work_package="T40S009DA0Q")
    h = next(h for h in r.hallazgos if h.codigo == "programado_despues_del_due")
    assert "T40S009DA0Q" in h.mensaje and h.severidad == "POSIBLE DISCREPANCIA"
    assert "programado_despues_del_due" not in codigos(
        auditar(catalogo, ctx, "OXIGENO_TRIPULACION", scheduled_date=datetime(2026, 8, 20, 13, 0)))


def test_attachment_de_otro_avion(catalogo, ctx):
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", avion="HP-1836CMP",
                adjuntos=["OXI GEN INVENTORYHP1836.png", "PASS OXY GEN HP1830.png"])
    h = next(h for h in r.hallazgos if h.codigo == "adjunto_otro_avion")
    assert "HP1830" in h.mensaje and h.severidad == "OBSERVACION"


def test_limite_dual_de_la_tabla_con_icam(catalogo, ctx):
    """Fila FUEL NOZZLE FULL SET REPLACEMENT: 45 DAYS OR 225 FC."""
    base = dict(nombre="ENG 2 FUEL NOZZLE FULL SET REPLACEMENT", ata=71, deferral_ref="71-DIP",
                intervalo=45.0, due_date=datetime(2026, 10, 2, 23, 59))
    solo_dias = [{"value": 45.0, "parameter": "CDY", "start": "18-AUG-2026 23:59 UTC"}]
    assert "limite_faltante" in codigos(auditar(catalogo, ctx, "TOBERAS_COMBUSTIBLE",
                                                icam_intervalos=solo_dias, **base))
    ambos = solo_dias + [{"value": 225.0, "parameter": "CYCLES", "start": "Aircraft 2504"}]
    assert "limite_faltante" not in codigos(auditar(catalogo, ctx, "TOBERAS_COMBUSTIBLE",
                                                    icam_intervalos=ambos, **base))


def test_sellante_de_ventanas_acepta_las_dos_practicas(catalogo, ctx):
    """7 días desde la apertura, o Start + 3 días con 4 días (22 DIPs aceptados)."""
    base = dict(nombre="STRUCTURE-OPEN DIP FOR SEAL CURE ON FLIGHT COMPARTMENT WINDOW", ata=56,
                deferral_ref="56-DIP", found_date=datetime(2026, 9, 10, 0, 13), due_date=None,
                usage_remaining=None)
    for intervalo, start in [(7.0, "10-SEP-2026"), (4.0, "13-SEP-2026")]:
        ta = [{"value": intervalo, "parameter": "CDY", "start": f"{start} 23:59 UTC"}]
        r = auditar(catalogo, ctx, "SELLANTE_VENTANAS", intervalo=intervalo, icam_intervalos=ta, **base)
        assert not codigos(r) & {"inicio_ta_incorrecto", "intervalo_excedido", "intervalo_menor"}
    # Start + 3 días con 7 días: vence a los 10.
    ta = [{"value": 7.0, "parameter": "CDY", "start": "13-SEP-2026 23:59 UTC"}]
    assert "intervalo_excedido" in codigos(auditar(catalogo, ctx, "SELLANTE_VENTANAS", intervalo=7.0,
                                                   icam_intervalos=ta, **base))


def test_uso_al_encontrar_en_cero_o_de_otro_contador_no_se_compara(catalogo, ctx):
    ta = [{"value": 75.0, "parameter": "HOURS", "start": "Aircraft 11348.7 / Component 11348.7"}]
    for uso in (0.0, 4392.97):
        r = auditar(catalogo, ctx, "EEC_C1", nombre="AHM ENG 2 EEC C1", intervalo=75.0, unidad="FH",
                    tipo_intervalo_original="HOURS", due_date=None, icam_intervalos=ta,
                    uso_encontrado={"HOURS": uso})
        assert "inicio_ta_incorrecto" not in codigos(r)


def test_dip_solo_con_rir_cuando_la_tabla_no_da_plazo(catalogo, ctx):
    """EXHAUST PLUG CRACK: TA '-' y RIR según el daño. El DIP sigue solo un RIR."""
    rir = RIR("RIR TAIL CONE", ["R1"], ["ACTV"], [Limite(7, "DAY")])
    r = auditar(catalogo, ctx, "GRIETA_TAPON_ESCAPE", nombre="ENGINE #2 EXHAUST TAIL CONE WITH CRACK",
                intervalo=None, unidad=None, rirs=[rir])
    assert "datos_incompletos" not in codigos(r)


def test_rir_start_con_redondeo_y_rir_mas_seguido():
    assert _mismo_inicio("Aircraft 50890.3 / Assembly 59806.41", "Aircraft 50890.29 / Assembly 59806.41")
    assert not _mismo_inicio("Aircraft 50890.3", "Aircraft 50895.3")
    assert not _mismo_inicio("12-SEP-2026 23:59 UTC", "13-SEP-2026 23:59 UTC")
    rir = RIR("RIR SEALANT", ["R1"], ["ACTV"], [Limite(1, "DAY")])
    assert [c for c, _ in revisar([rir], Limite(2, "DAY"), {})] == ["rir_intervalo_menor"]


# --- Filas Powerplant y Structures de la tabla ---------------------------------------------

@pytest.mark.parametrize("nombre, esperado", [
    ("ENG 2 FUEL NOZZLES FULL SET REPLACEMENT", "TOBERAS_COMBUSTIBLE"),
    ("AHM - ENG 1 EEC C2 scheduled maintenance task shows: SMT", "EEC_C2"),
    ("DIP - ENGINE #2 WATER WASH", "LAVADO_MOTOR"),
    ("DIP - BORESCOPE INSPECTION BY BIRDSTRIKE AT ENG #2 INLET", "BIRDSTRIKE_MOTOR"),
    ("DIP - ENGINE VIBRATION DURING CLIMB ENGINE #2 2.4", "VIBRACION_MOTOR"),
    ("DIP-MSG NBR: 77-20871 THE TOP LEFT EGT SIGNAL (T495S4) IS OUT OF RANGE", "EGT"),
    ("DIP - ENG 1  LONG TIME MSG", "MENSAJE_LONG_TIME"),
    ("DIP-ENGINE 1 VCD SEAL DETERIORATED", "VCD_SEAL"),
    ("STRUCTURE-OPEN DIP FOR SEAL CURE ON FLIGHT COMPARTMENT AND CONTROL CABIN WINDOW", "SELLANTE_VENTANAS"),
    ("STRUCTURE - OPEN DIP FOR LH 1 WINDSHIELD SEALANT", "SELLANTE_VENTANAS"),
    ("Apply an aerodynamic fillet seal to the clearance between the PITOT PROBE baseplate", "SELLANTE_PITOT"),
    ("STRUCTURE - LIGHTNING STRIKE STA 325.38 AND STR 18L +9\"", "RAYO_DANO"),
    ("DIP - TWO SPOT OF LIGHTNING STRIKE LOCATED ON EXTERNAL FUSELAGE SKIN SECTION 46", "RAYO_DANO"),
    ("IN REF TO BARCODE 2274947 (LIGHTNING STRIKE) PERFORM PHASE II", "RAYO"),
    ("055 611 00 (Lightning Strike)", "RAYO"),
    # Filas 84 y 87 de la tabla.
    ("DIP 53 OPENING - LIGHTINING STRIKE NEW THRESHOLD INSP", "UMBRAL_REPARACION"),
    ("CNR - ENG 1 EGT SYSTEM CHECK", "CNR_EGT"),
])
def test_asociacion_powerplant_y_structures(catalogo, nombre, esperado):
    assert asociar(nombre, catalogo).entrada.id == esperado


@pytest.mark.parametrize("nombre", [
    "DIP - AOA SEALANT, CAP SIDE",                               # sellante del AOA, no de ventanas
    "CNR - ENG#2 VIBRATION SYSTEM CHECK",                        # CNR de CFM sin fila en la tabla
    "IN REF TO LOG T40S009AE87 LH PITOT REPLACEMENT, PERFORM SEALANT INSTALATION WITHIN 10 DAYS",
])
def test_no_se_asocian_a_powerplant_ni_structures(catalogo, nombre):
    assert asociar(nombre, catalogo).entrada is None


def test_parent_de_la_fila_powerplant(catalogo, ctx):
    """T40S009HDNW: EEC C2 en el avión; la tabla dice ENGINE."""
    r = auditar(catalogo, ctx, "EEC_C2", nombre="AHM - ENG 1 EEC C2", ata=73, deferral_ref="73-DIP",
                intervalo=201.0, unidad="FH", tipo_intervalo_original="HOURS", due_date=None,
                parent_assy="Boeing 737-8 MAX8 - HP-9819CMP", parent_tipo="AIRCRAFT")
    assert "parent_assy_incorrecto" in codigos(r)


# --- Referencia técnica ---------------------------------------------------------------------

def _referencia(auditor, ctx, nombre, descripcion, cargada="", adjuntos=("captura.png",)):
    dip = hacer_dip(nombre=nombre, descripcion=descripcion, referencia_tecnica=cargada,
                    adjuntos=list(adjuntos), datos_referencia=True)
    r = ResultadoReglas()
    auditor._referencia_tecnica(dip, auditor._asociar(dip), ctx, r)
    return {h.codigo: h.severidad for h in r.hallazgos}


def test_referencia_distinta_segun_lo_que_pide_la_tabla(auditor, ctx):
    # La tabla pide la ECRA 2901-0036C y el DIP solo cita la AMM: posible discrepancia.
    h = _referencia(auditor, ctx, "HYDRAULIC DECONTAMINATION - TERMINAL",
                    "resample the hydraulic fluid within 300FH per AMM 29-11-00-200-801")
    assert h.get("referencia_tecnica_distinta") == "POSIBLE DISCREPANCIA"
    # El DIP cita la ECRA que lo originó y la tabla da la AMM del procedimiento: observación.
    h = _referencia(auditor, ctx, "DIP - ENGINE #2 WATER WASH",
                    "PERFORM ENGINE WATER WASH IAW ECRA 7200-0641C IN NO MORE THAN 100FH,50FC OR 10 DAYS")
    assert h.get("referencia_tecnica_distinta") == "OBSERVACION"


def test_la_task_card_es_referencia_tecnica(auditor, ctx):
    """La task card es referencia técnica: citada en la descripción o en un attachment."""
    # T40S009G29M: 'Per AMM 73-11-02' y la captura de la task card.
    h = _referencia(auditor, ctx, "DIP - No. 1 ENGINE FUEL FILTER",
                    "Replace the No. 1 engine fuel filter after 10 hours but prior to 75 hours Per AMM "
                    "73-11-02 REV 90", adjuntos=["DIP B737-28-1-9001-U-JIC (Fuel Tanks - Refuel.png"])
    assert "sin_referencia_tecnica" not in h
    # T40S009BE17 y T40S009C6DB: solo la task card, sin attachments.
    for descripcion in ("FORWARD PAX PORTABLE OXIGEN BOTTLE NEXT HYDRO DUE DATE 09-2026, IAW TASK "
                        "B737-05-1-0005-U-JIC (Passenger Cabin Inspection)",
                        "FWD POB WAS FOUND WITH HYDRO DUE DATE LESS THAN 60 DAYS, IN REFERENCE TASK "
                        "B737-05-1-0005-U-JIC WAS OPEN DIP FOR REPLACE.",
                        "DURING SV-2 TASK CARD B737-73-1-0001-JIC FOUND ENGINE #2 SHORT TIME MESSAGE",
                        "DUE ACCOMPLISHMENT TASKCARD 32-020-02-U-JIC (Right Main Landing Gear)"):
        h = _referencia(auditor, ctx, "DIP-FORWARD PAX PORTABLE OXIGEN BOTTLE", descripcion, adjuntos=[])
        assert "sin_referencia_tecnica" not in h, descripcion
    # T40S009H9BB: sin cita y como attachment solo la captura de un barcode de trabajo.
    h = _referencia(auditor, ctx, "STRUCTURE-OPEN DIP FOR SEAL CURE ON CONTROL CABIN WINDOW",
                    "OPEN a DIP to visually inspect the tape/sealant repair in TWO (2) DAY INTERVAL.",
                    adjuntos=["T40S00993NB 2 DAY INTERVALS.png"])
    assert "sin_referencia_tecnica" in h


def test_la_descripcion_manda_sobre_una_referencia_cargada_de_otro_item(auditor, ctx):
    """T40S009GSNA: mensaje LONG TIME con la AMM del EGT cargada en Technical References."""
    dip = hacer_dip(nombre="DIP-MSG NBR 78-21491 THE R REVERSER SLEEVE POSITION SIGNAL IS OUT OF RANGE",
                    descripcion="FOUND ENGINE #1 LONG TIME MESSAGE 78-21491. THIS ITEM ENTER IN DIP TO "
                                "INSPECT WITHIN 200 FLIGHT HOURS AND CORRECT WITHIN 400 FLIGHT HOURS.",
                    referencia_tecnica="AMM TASK 73-21-00-740-803-F00 REV 90")
    assert auditor._asociar(dip).entrada.id == "MENSAJE_LONG_TIME"


def test_una_srm_no_asocia(auditor):
    """SRM 53-00-01 es el capítulo de daños admisibles del fuselaje, no un ítem."""
    dip = hacer_dip(nombre="Sheet Metal-APU Fwd Hinge Skin", descripcion="APU door hinge skin found bent",
                    referencia_tecnica="SRM 53-00-01-1A-1 REV66 10-NOV-2018")
    assert auditor._asociar(dip).entrada is None
