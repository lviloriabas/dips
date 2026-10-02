"""Reglas calibradas con los motivos que anotan los auditores en ICAM ("DIP DISCREPANCY
FOUND: ...") en la auditoría del 25-ago al 23-sep-2026. Cada caso es un DIP real."""

from datetime import datetime

from dips_audit.asociacion import asociar
from dips_audit.cargador import cargar_export
from dips_audit.icam import leer_ficha
from dips_audit.reglas import ResultadoReglas, estado_final
from tests.conftest import crear_export
from tests.test_reglas import auditar, codigos

# --- Attachments ------------------------------------------------------------------------


def test_sin_attachments_es_discrepancia(catalogo, ctx):
    """T40S009ELDX: sin attachments ni referencia cargada; el auditor la marcó aunque la
    descripción cite el AMM."""
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", adjuntos=[])
    assert "sin_adjuntos" in codigos(r, "NO CRITICA")
    assert estado_final(r.hallazgos) == "POSIBLE DISCREPANCIA"
    assert "sin_adjuntos" not in codigos(auditar(catalogo, ctx, "OXIGENO_TRIPULACION",
                                                 adjuntos=["captura.png"]))
    # Sin ICAM ni columnas de attachments en el Excel no se sabe: no se marca.
    assert "sin_adjuntos" not in codigos(auditar(catalogo, ctx, "OXIGENO_TRIPULACION"))


def test_corte_9_julio_para_adjuntos(catalogo, ctx):
    for dia, exigible in [(8, True), (9, False), (10, False)]:
        r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", defer_date=datetime(2026, 7, dia),
                    adjuntos=[], estado="COMPLETE", accion_correctiva="BOTTLE REPLACED")
        cod = codigos(r)
        assert ("sin_adjuntos" in cod) is exigible
        assert ("cierre_sin_adjuntos" in cod) is exigible
        assert ("cierre_sin_referencia_tecnica" in cod) is exigible
    sin_fecha = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", defer_date=None, adjuntos=[])
    assert "sin_adjuntos" not in codigos(sin_fecha)


def test_sin_attachments_segun_el_excel(catalogo, ctx):
    """Sin ICAM se usa el Excel: Attachment Status PENDING = ningún attachment."""
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", adjuntos_excel=0)
    h = next(h for h in r.hallazgos if h.codigo == "sin_adjuntos")
    assert "PENDING" in h.mensaje
    cerrado = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", adjuntos_excel=0, estado="COMPLETE",
                      complete_date=datetime(2026, 8, 20, 10, 0))
    assert "cierre_sin_adjuntos" in codigos(cerrado, "NO CRITICA")
    assert "sin_adjuntos" not in codigos(auditar(catalogo, ctx, "OXIGENO_TRIPULACION",
                                                 adjuntos_excel=2))


def test_cerrado_sin_attachments_se_comenta_una_vez(auditor, catalogo, ctx):
    """Cerrado sin attachments tiene el hallazgo de apertura y el de cierre; el comentario
    sugerido lo dice una sola vez."""
    r = auditar(catalogo, ctx, "OXIGENO_TRIPULACION", adjuntos=[], estado="COMPLETE",
                complete_date=datetime(2026, 8, 20, 10, 0))
    assert {"sin_adjuntos", "cierre_sin_adjuntos"} <= codigos(r)
    assert auditor._comentario(r).count("attachments") == 1


def test_excel_trae_la_cantidad_de_attachments(tmp_path):
    encabezado = ["Fault Barcode", "Area", "Fault Name", "Dip Interval", "Interval Type",
                  "Fault Status", "Aircraft", "Attachment Status", "Attach Docs"]
    def fila(barcode, estado, cantidad):
        return [barcode, "Others", "FAK", 30, "CDY", "ACTV", "HP-1830CMP", estado, cantidad]

    lote = cargar_export(crear_export(tmp_path / "e.xlsx", [fila("T1", "PENDING", " "),
                                                            fila("T2", "OK", 3)],
                                      encabezado=encabezado))
    assert list(lote.datos["adjuntos_excel"]) == [0, 3]


# --- Start del T/A ("Incorrect DIP Start Values") -------------------------------------------

AMORTIGUADOR = dict(nombre="DIP-LEFT MAIN LANDING GEAR SHOCK STRUT", ata=32, deferral_ref="32-DIP",
                    unidad="FC", tipo_intervalo_original="CYCLES", due_date=None,
                    usage_remaining=None, flota="NG-800", uso_encontrado={"CYCLES": 14496.0})


def _ta_ciclos(start, intervalo):
    return [{"value": intervalo, "parameter": "CYCLES", "unit": "CYCLES",
             "start": f"Aircraft {start} / Component {start}"}]


def test_amortiguador_que_empieza_en_la_apertura_con_20_fc(catalogo, ctx):
    """T40S009GCWJ: 'after 5 landings but not to exceed 20 landings', abierto con 20 FC desde
    el uso al encontrar la falla. El auditor: INCORRECT DIP START VALUES."""
    r = auditar(catalogo, ctx, "AMORTIGUADOR_MLG", intervalo=20.0,
                icam_intervalos=_ta_ciclos(14496, 20), **AMORTIGUADOR)
    h = next(h for h in r.hallazgos if h.codigo == "inicio_ta_incorrecto")
    assert h.categoria == "Incorrect DIP Start Values"
    assert "5 FC después de la apertura, con 15 FC" in h.mensaje


def test_amortiguador_con_5_fc_mas_15_fc_es_correcto(catalogo, ctx):
    """Así lo aceptan los auditores: Start = uso al encontrar + 5, intervalo 15."""
    r = auditar(catalogo, ctx, "AMORTIGUADOR_MLG", intervalo=15.0,
                icam_intervalos=_ta_ciclos(14501, 15), **AMORTIGUADOR)
    assert not codigos(r) & {"inicio_ta_incorrecto", "intervalo_menor", "intervalo_excedido"}
    # Empieza a los 5 pero con 20 FC: vence a los 25.
    r = auditar(catalogo, ctx, "AMORTIGUADOR_MLG", intervalo=20.0,
                icam_intervalos=_ta_ciclos(14501, 20), **AMORTIGUADOR)
    assert "intervalo_excedido" in codigos(r)


def test_amortiguador_max_con_start_a_los_5_solo_marca_el_intervalo(catalogo, ctx):
    """MAX: 10 FC. Con Start + 5 y 15 FC el Start es correcto; el intervalo no."""
    r = auditar(catalogo, ctx, "AMORTIGUADOR_MLG", intervalo=15.0, icam_intervalos=_ta_ciclos(14501, 15),
                **{**AMORTIGUADOR, "flota": "MAX"})
    assert "intervalo_excedido" in codigos(r)
    assert "inicio_ta_incorrecto" not in codigos(r)


def test_otro_trabajo_sobre_el_amortiguador_empieza_en_la_apertura(catalogo, ctx):
    """'NLG STRUT COMPRESSED UNDER 5 INCHES' en 4 FC no es el chequeo después del servicio."""
    r = auditar(catalogo, ctx, "AMORTIGUADOR_MLG", intervalo=4.0,
                icam_intervalos=_ta_ciclos(14496, 4), **AMORTIGUADOR)
    assert "inicio_ta_incorrecto" not in codigos(r)


DPI = dict(nombre="DIP - IDG DPI", unidad="FH", tipo_intervalo_original="HOUR", ata=24,
           deferral_ref="24-DIP", due_date=None, usage_remaining=None, flota="NG-800",
           uso_encontrado={"HOURS": 1000.0})


def _ta_horas(start, intervalo):
    return [{"value": intervalo, "parameter": "HOURS", "unit": "HOUR",
             "start": f"Aircraft {start} / Component {start}"}]


def test_start_posterior_con_el_intervalo_descontado(catalogo, ctx):
    """DPI, 400 FH: Start 20 FH después de encontrar la falla con 380 FH vence a las 400 de la
    tabla (más horas en el Start, menos en el T/A): se acepta. Con 400 FH vence después."""
    r = auditar(catalogo, ctx, "DPI", intervalo=380.0, icam_intervalos=_ta_horas(1020, 380), **DPI)
    assert not codigos(r) & {"inicio_ta_incorrecto", "intervalo_excedido"}
    r = auditar(catalogo, ctx, "DPI", intervalo=400.0, icam_intervalos=_ta_horas(1020, 400), **DPI)
    assert "inicio_ta_incorrecto" in codigos(r, "NO CRITICA")


def test_intervalo_excedido_solo_si_vence_despues(catalogo, ctx):
    """420 FH desde 20 FH antes de encontrar la falla vence a las 400: el intervalo no se pasó
    (el Start antes de la apertura sí se marca). Desde la apertura, 420 FH se pasa."""
    r = auditar(catalogo, ctx, "DPI", intervalo=420.0, icam_intervalos=_ta_horas(980, 420), **DPI)
    assert "intervalo_excedido" not in codigos(r)
    assert "inicio_ta_incorrecto" in codigos(r, "NO CRITICA")
    r = auditar(catalogo, ctx, "DPI", intervalo=420.0, icam_intervalos=_ta_horas(1000, 420), **DPI)
    assert "intervalo_excedido" in codigos(r, "CRITICA")
    # Sin el Start de ICAM se cuenta desde la apertura.
    r = auditar(catalogo, ctx, "DPI", intervalo=420.0, **{**DPI, "uso_encontrado": {}})
    assert "intervalo_excedido" in codigos(r, "CRITICA")


def _ta_dias(start, intervalo):
    return [{"value": intervalo, "parameter": "CDY", "unit": "DAY", "start": f"{start} 23:59 UTC"}]


def test_start_antes_de_la_apertura(catalogo, ctx):
    """T40S009GQK5: muestra microbiana abierta el 11-sep con el T/A desde el 08-sep."""
    r = auditar(catalogo, ctx, "CRECIMIENTO_MICROBIANO", nombre="TANK 1 MICROBIAL SAMPLE", ata=28,
                deferral_ref="28-DIP", intervalo=4.0, found_date=datetime(2026, 9, 11, 22, 39),
                due_date=datetime(2026, 9, 12, 23, 59), icam_intervalos=_ta_dias("08-SEP-2026", 4))
    assert "inicio_ta_incorrecto" in codigos(r, "NO CRITICA")


def test_start_en_el_defer_date(catalogo, ctx):
    """T40S009G72C: 'within 4 months from the performance date of this task': encontrado el
    7-sep, diferido el 9-sep y el T/A desde el 10-sep (tolerancia de 1 día)."""
    r = auditar(catalogo, ctx, "CABLES_ALERON", nombre="DIP-AILERON CONTROL CABLE CHECK", ata=27,
                deferral_ref="27-DIP", intervalo=122.0, found_date=datetime(2026, 9, 7, 15, 40),
                defer_date=datetime(2026, 9, 9, 1, 2), due_date=datetime(2027, 1, 10, 23, 59),
                icam_intervalos=_ta_dias("10-SEP-2026", 122))
    assert "inicio_ta_incorrecto" not in codigos(r)


def test_fdr_debe_empezar_7_dias_despues(catalogo, ctx):
    """FDR: 30 días, sin consultar a Ingeniería antes de 7 días. Desde el 10-sep los auditores
    exigen el T/A desde la apertura + 7 días con 23 días."""
    fdr = dict(nombre="FDR - Report", ata=31, deferral_ref="31-DIP",
               found_date=datetime(2026, 9, 10, 1, 56), due_date=datetime(2026, 10, 10, 23, 59))
    r = auditar(catalogo, ctx, "FDR", intervalo=30.0, icam_intervalos=_ta_dias("10-SEP-2026", 30), **fdr)
    assert "inicio_ta_incorrecto" in codigos(r)
    r = auditar(catalogo, ctx, "FDR", intervalo=23.0, icam_intervalos=_ta_dias("17-SEP-2026", 23), **fdr)
    assert not codigos(r) & {"inicio_ta_incorrecto", "intervalo_menor", "due_date_anterior_a_intervalo"}


def test_sin_fuente_con_start_posterior_queda_para_verificar(ctx):
    """Sin fila en la tabla no se sabe si el ítem tiene ventana: observación."""
    from dips_audit.reglas import auditar_dip
    from tests.conftest import hacer_dip

    dip = hacer_dip(nombre="DIP- NLG SWIVEL LEAK CHECK", intervalo=15.0, unidad="FC",
                    uso_encontrado={"CYCLES": 11974.0}, icam_intervalos=_ta_ciclos(11979, 15))
    r = auditar_dip(dip, None, ctx)
    assert "inicio_ta_incorrecto" in codigos(r, "OBSERVACION")
    dip["icam_intervalos"] = _ta_ciclos(11970, 15)   # antes de encontrar la falla
    assert "inicio_ta_incorrecto" in codigos(auditar_dip(dip, None, ctx), "NO CRITICA")


def test_items_con_vencimiento_no_revisan_el_start(catalogo, ctx):
    r = auditar(catalogo, ctx, "EMK", nombre="DIP-25 EMERGENCY MEDICAL KIT", intervalo=14.0, ata=25,
                deferral_ref="25-DIP", found_date=datetime(2026, 9, 12, 4, 41),
                due_date=datetime(2026, 11, 30, 23, 59), icam_intervalos=_ta_dias("16-NOV-2026", 14))
    assert "inicio_ta_incorrecto" not in codigos(r)


def test_lee_el_uso_al_encontrar_la_falla():
    historia = ("Usage At Completion\n\nInventory\tUsage Parm\tTSN\nX [Task]\tCycles ( CYCLES )\t4091\n\n"
                "Usage When Found \n\nInventory\tUsage Parm\tTSN\n"
                "32-11 - MAIN LANDING GEAR [Task]\tCycles ( CYCLES )\t14496\n"
                "\tFlying Hours ( HOURS )\t54442.44\n\n\nHistory\t\n")
    assert leer_ficha({"History": historia}).uso_encontrado == {"CYCLES": 14496.0, "HOURS": 54442.44}


# --- S/N ------------------------------------------------------------------------------------

def test_sn_distinto_de_las_notas_de_la_descripcion(catalogo, ctx):
    """Cuenta el número del S/N: P11101989 y 11101989 son el mismo; 11101998 no."""
    nombre = "DIP- AFT PORTABLE OXYGEN BOTTLE WITH NEXT HYDRO DATE (31-OCT-2026) S/N P11101989"
    for notas in ("AFT PORTABLE OXYGEN BOTTLE P/N 5500-A1A-BF23A S/N 11101989",
                  "AFT PORTABLE OXYGEN BOTTLE S/N P11101989", "BOTTLE S/N P-11101989"):
        r = auditar(catalogo, ctx, "OXIGENO_HYDRO", nombre=nombre, ata=35, notas_descripcion=notas)
        assert "sn_inconsistente" not in codigos(r), notas
    r = auditar(catalogo, ctx, "OXIGENO_HYDRO", nombre=nombre, ata=35,
                notas_descripcion="AFT PORTABLE OXYGEN BOTTLE S/N 11101998")
    assert "sn_inconsistente" in codigos(r, "NO CRITICA")


def test_sn_de_mas_en_un_texto_no_es_inconsistente(catalogo, ctx):
    """Dos kits en la descripción y uno en las notas: el que está coincide."""
    r = auditar(catalogo, ctx, "FAK", nombre="DIP - FAK", ata=25,
                descripcion="FAK S/N CFAK322 AND FAK S/N FAK028", notas_descripcion="FAK S/N CFAK322")
    assert "sn_inconsistente" not in codigos(r)


# --- Referencia no específica ---------------------------------------------------------------

def _revisar_referencia(auditor, ctx, descripcion, adjuntos=("captura.png",)):
    from tests.conftest import hacer_dip

    dip = hacer_dip(nombre="LE Flap and Slat Proximity Sensor (LH) Out of range.",
                    descripcion=descripcion, referencia_tecnica="", adjuntos=list(adjuntos),
                    datos_referencia=True)
    r = ResultadoReglas()
    auditor._referencia_tecnica(dip, asociar(dip["nombre"], auditor.catalogo), ctx, r)
    return codigos(r)


def test_barcode_de_trabajo_como_referencia(auditor, ctx):
    """T40S009GK7T: 'IAW BARCODE: TRF7N00900V4, STEP 63'. El auditor: NON SPECIFIC TECHNICAL
    REFERENCE."""
    assert "referencia_tecnica_no_especifica" in _revisar_referencia(
        auditor, ctx, "THIS ITEM ENTER DIP TO BE ACOMPLISHED IN 500FH IAW BARCODE: TRF7N00900V4, STEP 63.")
    # La task card del Service Visit sí se acepta, y un barcode junto al AMM también.
    assert not _revisar_referencia(
        auditor, ctx, "DURING SV2 WAS FOUND CREW OXYGEN 900 PSI REF TASK CARD B737-05-1-0001-U-JIC STEP 3")
    assert "referencia_tecnica_no_especifica" not in _revisar_referencia(
        auditor, ctx, "IN REF T40S009FH6U PERFORMED MICROBIAL TEST IAW AMM 28-10-00-200-802 REV 90")


def test_marcas_del_auditor_no_son_referencias():
    """AUDITTR (o sin tipo) es la marca que pone el auditor al terminar: se ignora."""
    tarea = ("Technical References\n\n\tName\tHyperlink\tType\tIETM\tDescription\n"
             "\tDIP OPEN - RT AUDIT COMPLETED\t \tAUDITTR\t \tDIP DISCREPANCY FOUND: X\n"
             "\tDIP CLOSED - RT AUDIT COMPLETED\t \t \t \t \n"
             "\tAMM TASK 12-15-21-210-801\t \tAMM\t \t \n\nAttachments\n")
    f = leer_ficha({"TaskInformation": tarea})
    assert f.referencias_tecnicas == ["AMM TASK 12-15-21-210-801"]
    assert len(f.marcas_auditoria) == 2
    assert f.marcas_auditdip == []  # AUDITTR o sin tipo: no cuenta como auditado manualmente
    assert f.auditoria_manual == ["Apertura: DISCREPANCIA (X)", "Cierre: sin discrepancia"]


def test_veredicto_del_auditor_en_la_marca():
    """T40S009E421 y T40S009J53J: la descripción de la marca dice si hubo discrepancia (ICAM
    la muestra dos veces seguidas). Vacía, el auditor no encontró ninguna. T40S009J3BH: otra
    nota del auditor, sin discrepancia."""
    tarea = ("Technical References\n\n\tName\tHyperlink\tType\tIETM\tDescription\tNotes\n"
             "\tDIP CLOSED - RT AUDIT COMPLETED\t\xa0\tAUDITDIP\t\xa0\t\xa0\t\xa0\n"
             "\tDIP OPEN - RT AUDIT COMPLETED\t\xa0\tAUDITDIP\t\xa0\t"
             "DIP DISCREPANCY FOUND: Missing Technical Reference."
             "DIP DISCREPANCY FOUND: Missing Technical Reference.\t\xa0\n\nAttachments\n")
    f = leer_ficha({"TaskInformation": tarea})
    assert f.auditoria_manual == ["Apertura: DISCREPANCIA (Missing Technical Reference)",
                                  "Cierre: sin discrepancia"]
    from dips_audit.icam import _veredicto
    nota = "DIP DUPLICATED, REFERENCE TO BC T40S009J3HP"
    assert _veredicto("DIP CLOSED - RT AUDIT COMPLETED", nota * 2) == (
        f"Cierre: sin discrepancia ({nota})")
    # La descripción que repite el nombre de la marca no es una nota.
    assert _veredicto("DIP OPEN - RT AUDIT COMPLETED", "DIP OPEN - RT AUDIT COMPLETED" * 2) == (
        "Apertura: sin discrepancia")


# --- DIP duplicado o creado por error ----------------------------------------------------


def test_dip_marcado_como_duplicado_o_por_error():
    """T40S009J6FT ("ENTERED BY MISTAKE"), T40S009J1RE ("DIP OPEN BY MISTAKE IN WRONG WP") y
    T40S009J3BH, que el auditor anotó "DIP DUPLICATED, REFERENCE TO BC T40S009J3HP"."""
    from dips_audit.reglas import dip_por_error
    from tests.conftest import hacer_dip

    accion = "1. ALEXIS ARBOLEDA (Technician), 24-SEP-2026 06:45 UTC\nENTERED BY MISTAKE"
    assert dip_por_error(hacer_dip(estado="COMPLETE", accion_correctiva=accion)) == \
        "DIP creado por error."
    assert dip_por_error(hacer_dip(estado="COMPLETE", accion_correctiva=(
        "DIP OPEN BY MISTAKE IN WRONG WP"))) == "DIP creado por error."
    assert dip_por_error(hacer_dip(estado="COMPLETE", accion_correctiva=(
        "DIP DUPLICATED, REFERENCE TO BC T40S009J3HP"))) == "DIP duplicado (ver T40S009J3HP)."
    assert dip_por_error(hacer_dip(descripcion="DIP DUPLICADO DEL T40S009J3HP")) == \
        "DIP duplicado (ver T40S009J3HP); sigue abierto."
    # En la descripción, "BY MISTAKE" suelto es la falla, no el DIP.
    assert dip_por_error(hacer_dip(descripcion="OXYGEN MASK DEPLOYED BY MISTAKE")) is None
    assert dip_por_error(hacer_dip(estado="COMPLETE", accion_correctiva=(
        "BOTTLE REPLACED IAW AMM TASK 35-11-11-000-801"))) is None


def test_dip_por_error_no_se_audita(config, tmp_path):
    """Cerrado como creado por error: basta anotarlo, sin los hallazgos del resto de la
    auditoría (aquí, sin attachments ni referencia técnica). El comentario es solo eso."""
    from dips_audit.auditor import Auditor
    from dips_audit.cargador import lote_desde_icam
    from tests.test_barcode import _registro

    registro = _registro(estado="COMPLETE (Complete)")
    registro["sections"]["TaskExecution"] = (
        "Description \n\nFDR READOUT PENDING\n\nLabor\n\nCorrective Action\n\n"
        "1. TECNICO (Technician), 24-SEP-2026 06:45 UTC\nENTERED BY MISTAKE\n\nPart Requirements \n")
    lote = lote_desde_icam(registro, tmp_path / "icam.json")
    resultado = Auditor(config, fecha_auditoria=datetime(2026, 9, 25, 12, 0)).auditar_lote(lote)
    fila = resultado.filas.iloc[0]
    assert list(resultado.hallazgos["Código"]) == ["duplicado_declarado"]
    assert fila["RESULTADO"] == "OK"                 # cerrado: ya está corregido
    assert fila["COMENTARIO SUGERIDO"] == "DIP creado por error."
