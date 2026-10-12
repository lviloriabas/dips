from datetime import date

import pytest

from dips_audit.texto import (contiene_frase, extraer_fechas, extraer_pn, extraer_psi, extraer_sn,
                              menciona_referencia_tecnica, normalizar, posiciones)


@pytest.mark.parametrize("entrada, esperado", [
    ("DIP-AFT CABIN FIRT AID KIT", "DIP AFT CABIN FIRST AID KIT"),
    ("DIP-CREW OXY BOTTLE", "DIP CREW OXYGEN BOTTLE"),
    ("CERTIFICADO DE FUMIGACIÓN", "CERTIFICATE DE FUMIGATION"),
    ("PARKING BREAK SYSTEM", "PARKING BRAKE SYSTEM"),
    ("DIP-PORTABLE ELT2 DUE DATE", "DIP PORTABLE ELT 2 DUE DATE"),
    ("DIP- RE-TENSION CHECK", "DIP RETENSION CHECK"),
    ("MAREP-MLG#3 WITH CANVAS", "MAREP MLG 3 WITH CANVAS"),
    ("DIP- 25 UNIVERSIAL PROTECTION KIT", "DIP 25 UNIVERSAL PROTECTION KIT"),
])
def test_normalizar(entrada, esperado):
    assert normalizar(entrada) == esperado


def test_contiene_frase_palabras_completas():
    t = normalizar("DIP - FWD PORTABLE ELT")
    assert contiene_frase(t, "ELT")
    assert contiene_frase(t, "portable elt")
    assert not contiene_frase(normalizar("DIP - BELT DAMAGED"), "ELT")


@pytest.mark.parametrize("texto, esperado", [
    ("CREW OXYGEN BOTTLE 950 PSI", [950]),
    ("PSI ____IS 800______ psi BELOW 1.100 PSI", [800, 1100]),
    ("CREW OXYGEN PRESSURE BELOW 1000PSI", [1000]),
    ("DURING SVC 2 CREW OXY SYS WAS FOUND WITH 1,000 PSI", [1000]),
    ("CREW OXYGEN LOW PRESS", []),
])
def test_extraer_psi(texto, esperado):
    assert extraer_psi(texto) == esperado


@pytest.mark.parametrize("texto, esperado", [
    ("DIP - FIRST AID KIT S/N: FA4AG029 Due Date: 30-NOV-2026", ["FA4AG029"]),
    ("DIP - FWD FIRST AID KIT S/N FAK082 DUE DATE 30-SEP-2026", ["FAK082"]),
    ("Portable Halon Fire Extinguisher S/N Y-604482", ["Y-604482"]),
    ("Favor agregar SN I24576831", ["I24576831"]),
    ("DIP - UNIVERSAL PROTECTION KIT S/N: COPA-7 Due Date", ["COPA-7"]),
    ("DIP - PORTABLE ELT", []),
    ("S/N DUE DATE", []),
    ("BOTTLE 2 P/N2 5500-A1 S/N2: P11101989", ["P11101989"]),
    ("P/N2: 33700002 S/N2: 00875", ["00875"]),
    ("P/N2: 33700002", []),
    ("S/N: 12345", ["12345"]),
    ("S/N12345 SN67890", ["12345", "67890"]),
])
def test_extraer_sn(texto, esperado):
    assert extraer_sn(texto) == esperado


def test_pn_numerado_se_distingue_del_serial():
    texto = "P/N2: 33700002 S/N2: 00875; PART NUMBER M30903872; PN M30903872"
    assert extraer_pn(texto) == ["33700002", "M30903872"]
    assert extraer_sn(texto) == ["00875"]


@pytest.mark.parametrize("texto, esperado", [
    ("DUE DATE 30-SEP-2026", [date(2026, 9, 30)]),
    ("CERTIFICATE OF FUMIGATION DUE 16-JUL-26", [date(2026, 7, 16)]),
    ("certificate less 7days due date 07/AUG/2026.", [date(2026, 8, 7)]),
    ("IS NEXT DUE DATE  05AUG26 IAW TASK", [date(2026, 8, 5)]),
    ("CERTIFICATE OF FUMIGATION EXPIRE JULY 24 2026", [date(2026, 7, 24)]),
    ("near to expired date (19 Jul 2026)", [date(2026, 7, 19)]),
    ("less than 4 month to expiration date (Sep-2026", [date(2026, 9, 30)]),
    ("Fecha de vencimiento of the fumigation certificate:03 AUG-2026", [date(2026, 8, 3)]),
    # Fecha exacta con la letra O en vez de cero: no se infiere el fin de mes.
    ("DUE DATE:31-MAR-2036 WEIGHT DUE DATE:O3-FEB-2027", [date(2036, 3, 31), date(2027, 2, 3)]),
    ("WEIGHT DUE DATE: 1O FEB 2027", [date(2027, 2, 10)]),
    ("ORIGINAL DATED09-OCT-2026", [date(2026, 10, 9)]),
    ("BATTERY DUE: NO SEP-2026", [date(2026, 9, 30)]),
    ("DIP - PORTABLE ELT", []),
])
def test_extraer_fechas(texto, esperado):
    assert extraer_fechas(texto) == esperado


def test_posiciones_distingue_componentes_gemelos():
    assert posiciones(normalizar("DIP - LEFT MAIN LANDING GEAR SHOCK STRUT")) != \
        posiciones(normalizar("DIP - RIGHT MAIN LANDING GEAR SHOCK STRUT"))
    assert posiciones(normalizar("DIP MLG Brake assy #(3)")) != \
        posiciones(normalizar("DIP MLG Brake assy #(4)"))
    assert posiciones(normalizar("DIP-FAK AFT 1")) != posiciones(normalizar("DIP-FAK AFT 2"))
    assert posiciones(normalizar("CREW OXYGEN 850 PSI")) == posiciones(normalizar("DIP-CREW OXYGEN"))


def test_menciona_referencia_tecnica():
    assert menciona_referencia_tecnica("PERFORM SEALANT AS PER AMM TASK 27-31-94-400-801")
    assert menciona_referencia_tecnica("OPEN A DIP ACCORDING TO ECRA 2011-01000")
    assert not menciona_referencia_tecnica("DIP - PORTABLE ELT")
