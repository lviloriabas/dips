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
