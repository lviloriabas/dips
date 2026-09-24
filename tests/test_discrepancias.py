import re
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import pytest

from dips_audit.auditor import Auditor
from dips_audit.discrepancias import Discrepancias, cargar_discrepancias
from dips_audit.reglas import auditar_dip, estado_final
from tests.conftest import RAIZ, crear_export, hacer_dip
from tests.test_integracion import FILAS

FDR_EXCEDIDO = dict(nombre="FDR - REPORT", intervalo=45.0, ata=31, deferral_ref="31-DIP",
                    due_date=datetime(2026, 10, 2, 23, 59))


def con(ctx, discrepancias: dict):
    return replace(ctx, discrepancias=Discrepancias.desde_dict(discrepancias))


def auditar_fdr(catalogo, ctx):
    return auditar_dip(hacer_dip(**FDR_EXCEDIDO), catalogo.por_id("FDR"), ctx)


def test_todas_las_reglas_del_programa_estan_en_el_documento(auditor):
    """Cada código que el programa puede informar tiene tipo, activa y severidad."""
    fuente = "\n".join(p.read_text(encoding="utf-8")
                       for p in (RAIZ / "dips_audit").glob("*.py"))
    usados = set(re.findall(r'agregar\(\s*ctx,\s*"(\w+)"', fuente))
    usados |= set(re.findall(r'hallazgos\.append\(\(\s*"(\w+)"', fuente))  # rir.py
    usados |= set(re.findall(r'Revision\(\s*"(\w+)"', fuente))      # referencia_tecnica.py
    assert len(usados) > 30
    assert usados - set(auditor.discrepancias.reglas) == set()


def test_el_documento_mantiene_la_severidad_de_cada_regla(ctx, catalogo):
    r = auditar_fdr(catalogo, ctx)
    h = next(h for h in r.hallazgos if h.codigo == "intervalo_excedido")
    assert (h.categoria, h.severidad) == ("Incorrect DIP Interval", "CRITICA")


def test_cambiar_severidad(ctx, catalogo):
    c = con(ctx, {"Incorrect DIP Interval": {"reglas": {"intervalo_excedido": "NO CRITICA"}}})
    r = auditar_fdr(catalogo, c)
    assert next(h for h in r.hallazgos if h.codigo == "intervalo_excedido").severidad == "NO CRITICA"
    # Por ahora toda severidad que no es observación da POSIBLE DISCREPANCIA.
    assert estado_final(r.hallazgos) == "POSIBLE DISCREPANCIA"
    # Como observación, el hallazgo se anota pero el DIP queda OK.
    c = con(ctx, {"Incorrect DIP Interval": {"reglas": {"intervalo_excedido": "OBSERVACION"}}})
    assert estado_final(auditar_fdr(catalogo, c).hallazgos) == "OK"


def test_desactivar_regla(ctx, catalogo):
    c = con(ctx, {"Incorrect DIP Interval": {"reglas": {
        "intervalo_excedido": {"activa": False, "severidad": "CRITICA"}}}})
    r = auditar_fdr(catalogo, c)
    assert "intervalo_excedido" not in {h.codigo for h in r.hallazgos}
    assert estado_final(r.hallazgos) == "OK"


def test_desactivar_tipo(ctx, catalogo):
    c = con(ctx, {"Incorrect DIP Interval": {"activo": False, "reglas": {
        "intervalo_excedido": "CRITICA"}}})
    r = auditar_fdr(catalogo, c)
    assert not [h for h in r.hallazgos if h.categoria == "Incorrect DIP Interval"]


def test_regla_fuera_del_documento_es_no_critica(ctx, catalogo):
    r = auditar_fdr(catalogo, con(ctx, {}))
    h = next(h for h in r.hallazgos if h.codigo == "intervalo_excedido")
    assert (h.categoria, h.severidad) == ("Incorrect DIP Interval", "NO CRITICA")


def test_documento_en_la_auditoria_completa(config, tmp_path):
    """También en las reglas que se revisan sobre el lote (duplicados)."""
    texto = (RAIZ / "config" / "discrepancias.yaml").read_text(encoding="utf-8")
    texto = texto.replace("  Duplicated DIP:\n    activo: true", "  Duplicated DIP:\n    activo: false")
    texto = texto.replace("intervalo_excedido:                {activa: true, severidad: CRITICA}",
                          "intervalo_excedido:                {activa: true, severidad: NO CRITICA}")
    ruta = tmp_path / "discrepancias.yaml"
    ruta.write_text(texto, encoding="utf-8")
    auditor = Auditor({**config, "discrepancias": ruta}, fecha_auditoria=date(2026, 8, 20))
    resultado = auditor.auditar_archivo(crear_export(tmp_path / "export.xlsx", FILAS))
    estados = dict(zip(resultado.filas["Fault Barcode"], resultado.filas["RESULTADO"]))
    h = resultado.hallazgos
    assert set(h[(h["Fault Barcode"] == "T2") & (h["Código"] == "intervalo_excedido")]["Severidad"])         == {"NO CRITICA"}                               # intervalo excedido, ahora no crítico
    assert estados["T2"] == "POSIBLE DISCREPANCIA"
    assert estados["T5"] == "OK"                        # duplicado, tipo desactivado
    assert "duplicado" not in set(resultado.hallazgos["Código"])


def test_filtrar_categorias(ctx, catalogo):
    d = cargar_discrepancias(Path(RAIZ / "config" / "discrepancias.yaml"))
    assert d.buscar_tipos(["technical reference"]) == {
        "Missing Technical Reference", "Incorrect Technical Reference"}
    assert d.buscar_tipos(["rir"]) == {"RIR"}  # nombre exacto antes que parte de otro
    with pytest.raises(ValueError, match="no es un tipo"):
        d.buscar_tipos(["no existe"])
    assert d.filtrar(["Incorrect ATA"]) == ["Incorrect ATA"]
    r = auditar_fdr(catalogo, replace(ctx, discrepancias=d))
    assert estado_final(r.hallazgos) == "OK"  # el intervalo excedido no se revisa
    d.filtrar(None, ["Incorrect ATA"])
    r = auditar_fdr(catalogo, replace(ctx, discrepancias=d))
    assert "intervalo_excedido" in {h.codigo for h in r.hallazgos}


def test_cli_categorias(config, tmp_path, capsys):
    from dips_audit.__main__ import main

    ruta = crear_export(tmp_path / "export.xlsx", FILAS)
    salida = tmp_path / "salida.xlsx"
    assert main(["auditar", str(ruta), "--salida", str(salida), "--fecha", "2026-08-20",
                 "--categorias", "Duplicated DIP"]) == 0
    assert "Solo se revisaron estos tipos de discrepancia" in capsys.readouterr().out
    import pandas as pd
    h = pd.read_excel(salida, sheet_name="Hallazgos")
    # Los reportes ya no muestran el tipo de discrepancia: se verifica por el código de la regla.
    assert set(h["Código"]) <= {"duplicado"}
    with pytest.raises(SystemExit, match="no es un tipo"):
        main(["auditar", str(ruta), "--sin-excel", "--categorias", "xyz"])
    assert main(["categorias"]) == 0


@pytest.mark.parametrize("datos, error", [
    ({"A": {"reglas": {"x": "GRAVE"}}}, "severidad 'GRAVE'"),
    ({"A": {"reglas": {"x": "CRITICA"}}, "B": {"reglas": {"x": "CRITICA"}}}, "en 'A' y en 'B'"),
    ({"A": {"activo": "no", "reglas": {}}}, "true o false"),
    ({"A": {"reglas": {"x": {"activa": "si"}}}}, "true o false"),
])
def test_errores_del_documento(datos, error):
    with pytest.raises(ValueError, match=re.escape(error)):
        Discrepancias.desde_dict(datos)


def test_documento_del_proyecto_es_valido():
    d = cargar_discrepancias(Path(RAIZ / "config" / "discrepancias.yaml"))
    assert all(d.tipos.values()) and all(r.activa for r in d.reglas.values())
