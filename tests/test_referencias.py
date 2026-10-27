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


def test_fuel_pump_pad_plug_conserva_los_datos_de_la_tabla(catalogo):
    entrada = catalogo.por_id("TAPON_BOMBA_COMBUSTIBLE")
    assert entrada.parent_assy == {"ENGINE"}
    assert entrada.referencias_tecnicas == ""
    assert entrada.variantes == []


def test_catalogo_intervalos_condicionales_definidos(catalogo):
    frenos = catalogo.por_id("DESGASTE_FRENOS")
    assert {tuple(v.flotas) for v in frenos.variantes} >= {("NG-700",), ("MAX",)}
    oxigeno = catalogo.por_id("OXIGENO_TRIPULACION")
    assert Limite(3, "DAY") in [l for v in oxigeno.variantes for l in v.limites]


def test_catalogo_omite_referencia_eliminada_sin_detenerse(tmp_path, catalogo):
    ruta = tmp_path / "cat.yaml"
    ruta.write_text("- id: X\n  referencias: ['NO EXISTE']\n  requiere: [[X]]\n", encoding="utf-8")
    cat = cargar_catalogo(ruta, catalogo.referencias)
    assert cat.por_id("X") is None
    assert len(cat.referencias) == len(catalogo.referencias)
    assert any("retirada o renombrada" in a and "NO EXISTE" in a for a in cat.advertencias)


def test_catalogo_conserva_solo_referencias_vigentes_del_grupo(tmp_path, catalogo):
    from dips_audit.asociacion import asociar

    ruta = tmp_path / "cat.yaml"
    ruta.write_text("- id: FDR\n  referencias: ['FDR REPORT', 'ELIMINADA']\n"
                    "  requiere: [[FDR]]\n", encoding="utf-8")
    cat = cargar_catalogo(ruta, catalogo.referencias)
    entrada = asociar("FDR REPORT", cat).entrada
    assert entrada.id == "FDR"
    assert [r.descripcion for r in entrada.referencias] == ["FDR REPORT"]
    assert [v.limites for v in entrada.variantes] == [[Limite(30, "DAY")]]


def test_eliminar_fila_con_intervalos_no_resucita_su_regla(tmp_path, catalogo):
    from dips_audit.asociacion import asociar

    ruta = tmp_path / "cat.yaml"
    ruta.write_text("- id: FDR\n  referencias: ['FDR REPORT']\n  requiere: [[FDR]]\n"
                    "  intervalos:\n    - variante: 30 DAYS\n"
                    "      limites: [{valor: 30, unidad: DAY}]\n", encoding="utf-8")
    filas = [f for f in catalogo.referencias if f.descripcion != "FDR REPORT"]
    cat = cargar_catalogo(ruta, filas)
    assert cat.por_id("FDR") is None
    assert asociar("FDR REPORT", cat).entrada is None


def test_renombrar_fila_la_incorpora_con_nombre_y_datos_actuales(tmp_path, catalogo):
    from dataclasses import replace
    from dips_audit.asociacion import asociar
    from dips_audit.referencia_tecnica import IndiceReferencias

    ruta = tmp_path / "cat.yaml"
    ruta.write_text("- id: FDR\n  referencias: ['FDR REPORT']\n  requiere: [[FDR]]\n",
                    encoding="utf-8")
    original = next(f for f in catalogo.referencias if f.descripcion == "FDR REPORT")
    nueva = replace(original, descripcion="RECORDER DATA DOWNLOAD", ta="45 DAYS",
                    referencias="AMM TASK 31-31-00-000-802", rir="3 DAYS")
    cat = cargar_catalogo(ruta, [nueva])
    entrada = asociar("DIP RECORDER DATA DOWNLOAD", cat).entrada
    assert cat.por_id("FDR") is None
    assert entrada.automatica and entrada.nombre == nueva.descripcion
    assert entrada.variantes[0].limites == [Limite(45, "DAY")]
    assert entrada.variantes[0].rir == "3 DAYS"
    assert "31-31-00-000-802" in next(iter(IndiceReferencias.desde_catalogo(cat).entradas))


@pytest.mark.parametrize("ta", ["45 DAYS", "UNTIL DUE DATE", "10 DAYS IF DAMAGE IS MINOR"])
def test_ta_online_modificado_invalida_intervalos_locales(catalogo, config, ta):
    from dataclasses import replace

    filas = [replace(f, ta=ta) if f.descripcion == "FDR REPORT" else f
             for f in catalogo.referencias]
    entrada = cargar_catalogo(config["catalogo"], filas).por_id("FDR")
    assert all(Limite(30, "DAY") not in v.limites for v in entrada.variantes)
    if ta == "45 DAYS":
        assert entrada.variantes[0].limites == [Limite(45, "DAY")]
    elif ta == "UNTIL DUE DATE":
        assert entrada.hasta_vencimiento and not entrada.variantes
    else:
        assert entrada.no_verificable and not entrada.variantes


@pytest.mark.parametrize("rir", ["3 DAYS", ""])
def test_rir_online_modificado_no_conserva_valor_local(catalogo, config, rir):
    from dataclasses import replace

    filas = [replace(f, rir=rir) if f.descripcion == "SEALANT" else f
             for f in catalogo.referencias]
    entrada = cargar_catalogo(config["catalogo"], filas).por_id("SELLANTE_VENTANAS")
    assert entrada.variantes[0].rir == rir
    assert entrada.variantes[0].inicio == Limite(3, "DAY")


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


def test_pdf_de_referencias_con_tabla_de_texto(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    from dips_audit.referencias import cargar_referencias

    ancho = [12, 14, 6, 9, 28, 17, 35, 16]
    def linea(valores):
        return "".join(f"{v:<{n}}" for v, n in zip(valores, ancho)) + valores[-1]

    cabecera = linea(["TYPE", "AREA", "ATA", "FLEET", "DESCRIPTION", "PARENT ASSY",
                      "REFERENCES", "TA", "RIR"])
    fila = linea(["OTHERS", "FDR", "31", "ALL", "FDR REPORT", "AIRCRAFT",
                  "AMM 31-31-00-000-801", "30 DAYS", "7 DAYS"])
    writer = PdfWriter()
    page = writer.add_blank_page(width=1500, height=400)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Courier")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
        NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 8 Tf 20 350 Td ({cabecera}) Tj 0 -15 Td ({fila}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    ruta = tmp_path / "referencias.pdf"
    writer.write(ruta)
    [ref] = cargar_referencias(ruta)
    assert (ref.tipo, ref.ata, ref.descripcion, ref.ta, ref.rir) == (
        "OTHERS", 31, "FDR REPORT", "30 DAYS", "7 DAYS")
