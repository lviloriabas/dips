import pytest

from dips_audit.asociacion import asociar, intervalo_compatible, similares_en_tabla

# Fault Names reales del histórico y la entrada esperada del catálogo.
CASOS = [
    ("CREW OXYGEN PRESSURE BELOW 1000 PSI", "OXIGENO_TRIPULACION"),
    ("Flight Compartment Crew Oxygen System Pressure indication: 1020 psi", "OXIGENO_TRIPULACION"),
    ("35-DIP CREW OXY PRESS WITH 950 PSI", "OXIGENO_TRIPULACION"),
    ("DIP - FLIGHT COMPARTMENT OXYGEN BOTTLE WITH LESS THAN 1100 PSI", "OXIGENO_TRIPULACION"),
    ("Portable oxygen bottle hydro date", "OXIGENO_HYDRO"),
    ("DIP - PORTABLE OXYGEN BOTTLE FWD GALLEY", "OXIGENO_PORTATIL"),
    ("DIP - PORTABLE ELT BATTERY", "ELT_PORTATIL"),
    ("DIP-PORTABLE ELT2 DUE DATE", "ELT_PORTATIL"),
    ("DIP-EMERGENCY LOCATOR TRANSMITER BATTERY DUE DATE", "ELT_PORTATIL"),
    ("DIP - FIXED ELT", "ELT_FIJO"),
    ("DIP-EMK with less than 130 days of Due Date", "EMK"),
    ("DIP EMERGENCY MEDICAL KID NEXT DUE DAT", "EMK"),
    ("DIP-AFT CABIN FIRT AID KIT", "FAK"),
    ("FWD FAK with les than 130 days to due Date", "FAK"),
    ("DIP - UNIVERSAL PROTECTION KIT S/N: COPA308", "UPK"),
    ("DIP- 25 UNIVERSIAL PROTECTION KIT", "UPK"),
    ("DIP // SURVIVAL KIT", "SURVIVAL_KIT"),
    ("FDR - REPORT", "FDR"),
    ("DIP - FLIGHT COMPARTMENT HALON FIRE EXTINGUISHER BOTTLE WITH LESS THAN 120 DAYS", "HALON_PORTATIL"),
    ("WATER EXTINTOR", "EXTINTOR_AGUA"),
    ("Both Squibs on LH Engine Fire Extinguisher Bottle (FWD)", "SQUIB_MOTOR_APU"),
    ("SYSTEM-CARGO FIRE EXT. BOTTLE 1", "EXTINTOR_CARGO"),
    ("DIP- Sampling Evaluation Procedure per Microbmonitor KiT", "CRECIMIENTO_MICROBIANO"),
    ("DIP - ENGINE #2 FUEL FILTER REPLACEMENT", "FILTRO_COMBUSTIBLE_MOTOR"),
    ("DIP - CERTIFICADO DE FUMIGACION", "FUMIGACION"),
    ("DIP-CERTIFICATE OF REGISTRATION AND RADIO LICENSE", "LICENCIA_RADIO"),
    ("HYDRAULIC DECONTAMINATION - INITIAL", "DESCONTAMINACION_HID_INICIAL"),
    ("HYDRAULIC DECONTAMINATION - TERMINAL", "DESCONTAMINACION_HID_TERMINAL"),
    ("DIP-Primary Backflow Prevention Check Valve", "BACKFLOW"),
    ("DIP -  IDG Differential Pressure Indicator (DPI)", "DPI"),
    ("DIP-NLG SHOCK STRUT PRESSURE AND X DIMENSION CHECK", "AMORTIGUADOR_NLG"),
    ("DIP - LEFT MAIN LANDING GEAR SHOCK STRUT", "AMORTIGUADOR_MLG"),
    ("D.I.P. CHECK SHOCK STRUT PRESSURE AND x DIMENSION AFTER 5 LANDINGS", "AMORTIGUADOR_GENERICO"),
    ("DURING INSPECTION THE MAIN BRAKE N°4 WAS FOUND LESS THR 1/16\" WEAR PIN", "DESGASTE_FRENOS"),
    ("DIP#2-Parking Brake System - FNC FAIL", "FRENO_PARQUEO"),
    ("DIP-AILERON CABLE ABSA-L1 RETENSION CHECK", "CABLES_ALERON"),
    ("perform rudder control cable retension check and adjustment", "CABLES_TIMON"),
    ("DIP - ELEVATOR CONTROL CABLES EA AND EB RE-TENSION CHECK", "CABLES_ELEVADOR"),
    ("DIP- STA/STB CABLES RE-TENSION CHECK", "CABLES_ESTABILIZADOR"),
    ("MAREP///NOSE WHEEL TIRE #2 SHOWING SECOND PLY", "LLANTA"),
    ("055 611 00 (Lightning Strike)", "RAYO"),
    ("RADOME INTERNAL INSPECTION DUE TO BIRDSTRIKE", "RADOMO"),
    ("AHM - 361 451 41/42 BLEED CTRL CARD L & R scheduled maintenance task shows: SMT", "BLEED_CTRL_CARD"),
    ("AHM - 361 452 41 BLEED FAMV RVDT L scheduled maintenance task shows: SMT", "BLEED_FAMV"),
]


@pytest.mark.parametrize("nombre, esperado", CASOS)
def test_asociacion_por_reglas(catalogo, nombre, esperado):
    a = asociar(nombre, catalogo)
    assert a.metodo == "REGLAS", a
    assert a.entrada.id == esperado


@pytest.mark.parametrize("nombre", [
    "OXYGEN MASK CREW STOWAGE BOX",          # máscara, no botella
    "DIP-31 UNDERWATER LOCATOR BEACON(FDR)",  # ULB, no reporte FDR
    "DIP- 25 PASSENGER LIFE VEST",           # vencimiento de chaleco, no seguro de puerta
    "DEFIBRILLATOR DUE DATE",
    "DIP- wing tank # 2 access door 632AB",
])
def test_sin_asociacion_cuando_no_corresponde(catalogo, nombre):
    a = asociar(nombre, catalogo)
    assert a.entrada is None
    assert a.metodo == "NINGUNA"


def test_similares_en_tabla_detecta_otro_tipo(catalogo):
    similares = similares_en_tabla("DIP - E1 PRIMARY EXHAUST NOZZLE WITH OVERHEATING EVIDENCE",
                                   catalogo)
    assert similares and similares[0][0].tipo == "POWERPLANT"


def test_intervalo_compatible(catalogo):
    fdr = catalogo.por_id("FDR")
    assert intervalo_compatible(fdr, 30, "DAY")
    assert not intervalo_compatible(fdr, 112, "DAY")
    assert not intervalo_compatible(fdr, 30, "FH")
    cables = catalogo.por_id("CABLES_ALERON")
    assert intervalo_compatible(cables, 184, "DAY")
    assert intervalo_compatible(catalogo.por_id("FAK"), 400, "DAY")  # hasta vencimiento


class LLMFalso:
    """Simula el modelo local: siempre responde la entrada indicada."""

    def __init__(self, entrada):
        self.entrada = entrada
        self.llamadas = []

    def elegir_categoria(self, nombre, candidatos, intervalo=""):
        self.llamadas.append((nombre, [c.id for c in candidatos], intervalo))
        return self.entrada, "prueba"


def test_llm_solo_se_consulta_si_las_reglas_no_asocian(catalogo):
    llm = LLMFalso(catalogo.por_id("FDR"))
    asociar("FDR - REPORT", catalogo, llm, 30, "DAY")
    assert llm.llamadas == []


def test_llm_sugerencia_aceptada_queda_como_ia(catalogo):
    llm = LLMFalso(catalogo.por_id("RADOMO"))
    a = asociar("DIP - NOSE INTERNAL INSPECTION", catalogo, llm, 3, "FC")
    assert a.metodo == "IA" and a.entrada.id == "RADOMO"
    assert a.confianza == "MEDIA"
    assert llm.llamadas[0][2] == "3 FC"


def test_llm_sugerencia_con_intervalo_incompatible_se_descarta(catalogo):
    llm = LLMFalso(catalogo.por_id("FDR"))
    a = asociar("FLIGHT DATA RECORDER READOUT", catalogo, llm, 112, "DAY")
    assert a.entrada is None and "no es compatible" in a.detalle


def test_llm_sugerencia_con_palabra_excluida_se_descarta(catalogo):
    llm = LLMFalso(catalogo.por_id("FDR"))
    a = asociar("DIP-31 UNDERWATER LOCATOR BEACON(FDR)", catalogo, llm, 30, "DAY")
    assert a.entrada is None and "UNDERWATER" in a.detalle


def test_llm_sugerencia_sin_palabras_distintivas_se_descarta(catalogo):
    llm = LLMFalso(catalogo.por_id("ELT_PORTATIL"))
    a = asociar("AFT LAV SMOKE DETECTOR BATTERY", catalogo, llm, 30, "DAY")
    assert a.entrada is None and "palabras distintivas" in a.detalle
