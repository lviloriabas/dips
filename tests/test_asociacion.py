import pytest

from dips_audit.asociacion import asociar, similares_en_tabla
from tests.conftest import hacer_dip

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
    ("PIREP - TIRE MAIN IS SHOWING CANVAS", "LLANTA"),
    # Fault Names reales del 23-sep-2026 que antes quedaban sin referencia.
    ("DIP - First Aid (Aft Passenger Compartment) Kit", "FAK"),
    ("DIP- FIRST AID KID", "FAK"),
    ("Cover life vest 2AB MISSING", "CHALECO"),
    ("LIVEVEST LATCH DOOR BROKEN SEAT 1EF", "CHALECO"),
    ("DIP - RH MAIN LANDING GEAR X DIMENSION CHECK", "AMORTIGUADOR_MLG"),
    ("DIP - Cargo Fire Extinguisher Bottle #1 AFT Squib", "SQUIB"),
    ("055 611 00 (Lightning Strike)", "RAYO"),
    ("RADOME INTERNAL INSPECTION DUE TO BIRDSTRIKE", "RADOMO"),
    ("AHM - 361 451 41/42 BLEED CTRL CARD L & R scheduled maintenance task shows: SMT", "BLEED_CTRL_CARD"),
    ("AHM - 361 452 41 BLEED FAMV RVDT L scheduled maintenance task shows: SMT", "BLEED_FAMV"),
    # Filas 49-58 y 83-93 de la tabla (Fault Names reales del 25-sep-2026).
    ("DIP - MLG #1, TIRE CHECK PRESSURE 175 PSI", "LLANTA_PRESION"),
    ("DIP - NLG #01 CHECK TIRE PRESSURE IN 24 HRS", "LLANTA_PRESION"),
    ("DIP - P-STATIC BONDING JUMPER (LH FWD) NOSE WHEEL DOOR BROKEN", "P_STATIC_JUMPER"),
    ("DIP - OXYGEN GENERATORS DUE DATE 31 JAN 2028", "GENERADOR_OXIGENO"),
    ("DIP - ASU AFT LH OXYGEN GENERATOR DUE DATE 31 JAN 2029", "GENERADOR_OXIGENO"),
    ("DIP- PASSENGER OXYGEN DUE DATE", "GENERADOR_OXIGENO"),
    ("200 - A group of Oxygen Generators (5 EA) PN:E72280-00 With DUE DATE 11/2029",
     "GENERADOR_OXIGENO"),
    ("AVIONIC - FLAP/SLAT PROXIMITY SENSORS OUT OF RANGE LH SIDE", "PROXIMIDAD_FLAP_SLAT"),
    ("DIP- LE Flap and Slat Proximity Sensor (RH)", "PROXIMIDAD_FLAP_SLAT"),
    ("DIP INSTALLATION OF NEW VERSION OF 46 NFS", "NFS_46_OAS"),
    ("DIP - EEC CREDENTIAL SYSTEM CHECK", "NFS_46_OAS"),
    ("DIP - RE-TORQUE CENTER TANK ACCESS DOOR PANELS 531AB & 531BB WITHIN 60 DAYS",
     "RETORQUE_PUERTA_TANQUE"),
    ("DIP 2 - MAIN AND CENTER TANK ACCESS DOOR RE-TORQUE", "RETORQUE_PUERTA_TANQUE"),
    ("MODERATE CONTAMINATION WAS FOUND IN THE TANKS L/H AND R/H, A NEW FUEL SAMPLE IS REQUIRED.",
     "MICROBIAL_MUESTRA_NUEVA"),
    ("SAMPLE TEST RESULT", "MICROBIAL_MUESTRA_NUEVA"),
    ("TANK 1 MICROBIAL SAMPLE", "CRECIMIENTO_MICROBIANO"),
    ("AHM - 320 451 00 AIR/GND SENSOR scheduled maintenance task shows: SMT", "AHM_AIR_GROUND"),
    ("ENGINE #2 SHORT TIME MESSAGE: 75-10452, THE VBV POSITION SIGNALS DISAGREE", "SHORT_TIME"),
    ("SHORT TIME MSG 73-30311", "MENSAJE_SHORT_TIME_73_30311"),
    ("CNR - ENG#1 EGT SYSTEM CHECK", "CNR_EGT"),
    ("CNR ENG 1 OIL SYS CK", "CNR_ACEITE"),
    ("DIP 53 OPENING - LIGHTINING STRIKE NEW THRESHOLD INSP", "UMBRAL_REPARACION"),
    ("55-DIP - DTI EVALUATION IAW MGM 5.5.11", "UMBRAL_REPARACION"),
    ("DIP - ENGINE 2 ACOUSTIC BARREL DENT AT 3 CLOCK", "DENT_PANEL_ACUSTICO"),
    ("DIP - Primary Prevention Check Valve.", "BACKFLOW"),
    ("MAREP - PORTABLE WATER WIGHT DUE DATE", "EXTINTOR_AGUA"),
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
    "CNR - ENGINE #1 VIBRATION SYSTEM CHECK",     # la tabla solo tiene los CNR de EGT y aceite
    "MAREP// WAS OPEN DIP FOR REPLACE PRESSURE LINE OF ACOUSTIC FILTER 3 DAYS",
    "DIP - SPOILER CONTROL CABLES",
])
def test_sin_asociacion_cuando_no_corresponde(catalogo, nombre):
    a = asociar(nombre, catalogo)
    assert a.entrada is None
    assert a.metodo == "NINGUNA"


def test_asociacion_por_la_descripcion(auditor):
    """Si el Fault Name no alcanza, la descripción dice qué es (T40S00971LS)."""
    dip = hacer_dip(nombre="AFT PASSENGER CABIN  LESS THAN 130 DAYS FOR DUE DATE",
                    descripcion="DURING PERFORMANCE TASK CARD MAIN CABIN EMERGENCY EQUIPMENT "
                                "INSPECTIONS WAS FOUND FIRST AID KIT WITH LESS THAN 130 DAYS")
    a = auditor._asociar(dip)
    assert a.metodo == "DESCRIPCION" and a.entrada.id == "FAK"


def test_asociacion_por_el_nombre_y_la_descripcion_juntos(auditor):
    """T40S009GJV2: el nombre dice la ventana y la descripción el sellante."""
    dip = hacer_dip(nombre="STRUCTURE - OPEN DIP FOR FLIGHT COMPARTMENT AND CONTROL CABIN "
                           "WINDOWS R/H #1",
                    descripcion="If you must send the airplane before the sealant fully cures, "
                                "do the step that follows")
    a = auditor._asociar(dip)
    assert a.metodo == "DESCRIPCION" and a.entrada.id == "SELLANTE_VENTANAS"


def test_descripcion_que_cita_otra_tarea_queda_sin_fuente(auditor):
    """T40S009FH6U: la muestra nueva de combustible sigue la SUBTASK 28-10-00-280-056 (10
    días, fila 90), no la referencia FUEL MICROBIAL GROWTH (AMM 28-10-00-200-802, 4 días)."""
    dip = hacer_dip(nombre="DIP-MODERATE CONTAMINATION WAS FOUND IN THE TANK #1, A NEW FUEL "
                           "SAMPLE IS REQUIRED.",
                    descripcion="SUBTASK 28-10-00-280-056 (3) If the initial test results are "
                                "positive for moderate or heavy levels of microbial contamination")
    assert auditor._asociar(dip).entrada.id == "MICROBIAL_MUESTRA_NUEVA"
    # La descripción dice "microbial" pero cita una tarea que no está en la tabla.
    dip = hacer_dip(nombre="DIP - FUEL TANK #1",
                    descripcion="SUBTASK 28-10-00-280-099 (3) If the initial test results are "
                                "positive for moderate or heavy levels of microbial contamination")
    assert auditor._asociar(dip).entrada is None


def test_asociacion_por_la_tarea_citada_en_la_descripcion(auditor):
    """"IAW EC/RA 2500-0538C" es la referencia del seguro de la puerta del chaleco."""
    dip = hacer_dip(nombre="DIP - SEAT 2AB MISSING ITEM",
                    descripcion="This item entre dip 60 days iaw ec/ra 2500-0538c Rev2, 26dec2014")
    a = auditor._asociar(dip)
    assert a.metodo == "REF_TECNICA" and a.entrada.id == "CHALECO"


def test_tarea_compartida_elige_la_referencia_mas_especifica(auditor):
    """La AMM 12-15-31-610-802 está en MAIN LANDING GEAR SHOCK STRUT y en el genérico."""
    dip = hacer_dip(nombre="DIP - RH GEAR CHECK", referencia_tecnica="TASK 12-15-31-610-802")
    a = auditor._asociar(dip)
    assert a.metodo == "REF_TECNICA" and a.entrada.id == "AMORTIGUADOR_MLG"


def test_similares_en_tabla_detecta_otro_tipo(catalogo):
    similares = similares_en_tabla("DIP - E1 PRIMARY EXHAUST NOZZLE WITH OVERHEATING EVIDENCE",
                                   catalogo)
    assert similares and similares[0][0].tipo == "POWERPLANT"

