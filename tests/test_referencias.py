import pytest

from dips_audit.referencias import (ErrorCatalogo, Limite, cargar_catalogo, interpretar_rir,
                                    interpretar_ta)


@pytest.mark.parametrize("ta, limites, hasta_venc, no_verif", [
    ("3 DAYS", [Limite(3, "DAY")], False, False),
    ("6 MONTHS", [Limite(6, "MONTH")], False, False),
    ("75 FH", [Limite(75, "FH")], False, False),
    ("45 DAYS OR 225 FC", [Limite(45, "DAY"), Limite(225, "FC")], False, False),
    ("UNTIL DUE DATE", [], True, False),
    ("UNTIL NEXT RON STATION, TIRE MAY NOT BE ABLE", [], False, True),
    ("NG: 20 FC (AFTER 5 LANDINGS, NOT LATER THAN 20 LANDINGS)", None, False, True),
    ("2.0-2.9 VIBRATION UNITS: 7 DAYS; 3.0-3.4: 5 FC", None, False, True),
])
def test_interpretar_ta(ta, limites, hasta_venc, no_verif):
    r = interpretar_ta(ta)
    assert r.hasta_vencimiento == hasta_venc
    assert r.no_verificable == no_verif
    if limites is not None:
        assert r.limites == limites


def test_interpretar_rir():
    assert interpretar_rir("1 DAY") == "1 DAY"
    assert interpretar_rir("100 FH") == "100 FH"
    assert interpretar_rir("Notas") == ""


def test_catalogo_cubre_todas_las_referencias_others(catalogo):
    sin_entrada = [a for a in catalogo.advertencias if "sin entrada en el catálogo" in a]
    assert sin_entrada == []


def test_catalogo_intervalos_condicionales_definidos(catalogo):
    frenos = catalogo.por_id("DESGASTE_FRENOS")
    assert {tuple(v.flotas) for v in frenos.variantes} >= {("NG-700",), ("MAX",)}
    oxigeno = catalogo.por_id("OXIGENO_TRIPULACION")
    assert Limite(3, "DAY") in [l for v in oxigeno.variantes for l in v.limites]


def test_catalogo_referencia_inexistente_falla(tmp_path, catalogo):
    ruta = tmp_path / "cat.yaml"
    ruta.write_text("- id: X\n  referencias: ['NO EXISTE']\n  requiere: [[X]]\n", encoding="utf-8")
    with pytest.raises(ErrorCatalogo, match="no existe"):
        cargar_catalogo(ruta, catalogo.referencias)


def test_catalogo_id_repetido_falla(tmp_path, catalogo):
    ruta = tmp_path / "cat.yaml"
    ruta.write_text("- id: X\n  referencias: ['FDR REPORT']\n  requiere: [[FDR]]\n" * 2,
                    encoding="utf-8")
    with pytest.raises(ErrorCatalogo, match="repetido"):
        cargar_catalogo(ruta, catalogo.referencias)


def test_fila_sin_entrada_en_el_catalogo_se_usa_igual(tmp_path, catalogo):
    """Una fila agregada a la tabla sin sus palabras clave en el catálogo se reconoce por
    las palabras de su DESCRIPTION y por su referencia técnica, con su TA."""
    from dips_audit.asociacion import asociar, asociar_por_codigos
    from dips_audit.referencia_tecnica import IndiceReferencias
    from dips_audit.referencias import FilaReferencia, palabras_de_la_descripcion

    fila = FilaReferencia(fila=200, tipo="OTHERS", area="FUEL", ata=28, flota="ALL",
                          descripcion="FUEL QUANTITY PROBE RECHECK (AFTER REPLACEMENT)",
                          parent_assy="AIRCRAFT", referencias="AMM TASK 28-41-11-000-801",
                          ta="15 DAYS", rir="")
    ruta = tmp_path / "cat.yaml"
    ruta.write_text("- id: FDR\n  referencias: ['FDR REPORT']\n  requiere: [[FDR]]\n",
                    encoding="utf-8")
    cat = cargar_catalogo(ruta, [f for f in catalogo.referencias
                                 if f.descripcion == "FDR REPORT"] + [fila])
    auto = cat.por_id("FILA_200")
    assert auto.automatica and [l for v in auto.variantes for l in v.limites] == [Limite(15, "DAY")]
    assert palabras_de_la_descripcion(fila.descripcion) == ["FUEL", "QUANTITY", "PROBE", "RECHECK"]
    assert any("Fila 200 sin entrada en el catálogo" in a for a in cat.advertencias)

    assert asociar("DIP - FUEL QUANTITY PROBE #2 RECHECK", cat).entrada is auto
    assert asociar("DIP - FUEL QUANTITY PROBE", cat).entrada is None   # falta RECHECK
    # Una entrada del catálogo gana a la automática.
    assert asociar("FDR REPORT FUEL QUANTITY PROBE RECHECK", cat).entrada.id == "FDR"
    indice = IndiceReferencias.desde_catalogo(cat)
    assert asociar_por_codigos(["AMM 28-41-11-000-801"], cat, indice) is auto


def test_referencia_aircraft_specific_no_fija_numeros_de_tarea(catalogo):
    """Fila 84: "[AIRCRAFT SPECIFIC] ECRA OF EACH REPAIR, E.G. ... ECRA 5300-3447C": las ECRA
    son ejemplos, cada DIP cita la de su reparación."""
    from dips_audit.referencia_tecnica import IndiceReferencias
    indice = IndiceReferencias.desde_catalogo(catalogo)
    assert indice.por_entrada["UMBRAL_REPARACION"] == set()
    assert "EC 5300-3447" not in indice.entradas


def test_ta_segun_mmel_es_revisar(catalogo):
    assert catalogo.por_id("AHM_TAILSKID").ta_segun_manual == "MMEL 32-71-01"
