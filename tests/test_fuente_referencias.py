import asyncio
import os
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from openpyxl import Workbook

from dips_audit.fuente_referencias import _urls_descarga, preparar_referencias
from dips_audit.referencias import ErrorCatalogo


ENLACE = ("https://copaairlines.sharepoint.com/:x:/r/teams/VP_Tecnica/dacre/records/"
          "_layouts/15/doc2.aspx?sourcedoc=%7B71427FA7-2DB0-4851-A5BA-63F30401684E%7D"
          "&file=DIPs%20References.xlsx&action=default")


def _xlsx(descripcion="FDR REPORT"):
    wb = Workbook()
    wb.active.title = "References"
    wb.active.append(["TYPE", "AREA", "ATA", "FLEET", "DESCRIPTION", "PARENT ASSY",
                      "REFERENCES", "TA", "RIR"])
    wb.active.append(["OTHERS", "FDR", 31, "ALL", descripcion, "AIRCRAFT",
                      "AMM 31-31-00-000-801", "30 DAYS", "7 DAYS"])
    contenido = BytesIO()
    wb.save(contenido)
    return contenido.getvalue()


def test_enlace_sharepoint_usa_descarga_autenticada():
    urls = _urls_descarga(ENLACE)
    assert len(urls) == 3
    assert parse_qs(urlsplit(urls[0]).query)["download"] == ["1"]
    assert "UniqueId=" in urls[1]
    assert urlsplit(urls[1]).path == "/teams/VP_Tecnica/dacre/records/_layouts/15/download.aspx"
    assert urlsplit(urls[2]).path == "/teams/VP_Tecnica/_layouts/15/download.aspx"


def test_fuente_local_y_dominio_privado(tmp_path):
    config = {"archivo": tmp_path / "icam.json"}
    assert preparar_referencias(tmp_path / "ref.pdf", config) == tmp_path / "ref.pdf"
    with pytest.raises(ErrorCatalogo, match="SharePoint"):
        preparar_referencias("https://example.com/ref.xlsx", config)


def test_descarga_guarda_solo_formato_correcto(monkeypatch, tmp_path):
    contenido = _xlsx()
    async def descargar(*args):
        return contenido
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    ruta = preparar_referencias(ENLACE, {"archivo": tmp_path / "icam.json"})
    assert ruta.parent == tmp_path and ruta.suffix == ".xlsx"
    assert ruta.read_bytes() == contenido


@pytest.mark.parametrize("fallo", ["red", "html", "corrupto", "sin_columnas"])
def test_fallo_sharepoint_usa_ultima_copia_y_no_la_sobrescribe(monkeypatch, tmp_path, fallo):
    config = {"archivo": tmp_path / "icam.json"}
    inicial = actual = _xlsx()
    respaldo = tmp_path / "referencias.xlsx"
    respaldo.write_bytes(inicial)
    async def descargar(*args):
        return actual
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    ruta = preparar_referencias(ENLACE, config, respaldo=respaldo)
    if fallo == "red":
        async def fallar(*args):
            raise OSError("Sin conexión")
        monkeypatch.setattr("dips_audit.fuente_referencias._descargar", fallar)
    elif fallo == "html":
        actual = "<html>Inicie sesión</html>".encode()
    elif fallo == "corrupto":
        actual = b"PK\x03\x04archivo roto"
    else:
        wb = Workbook()
        wb.active.title = "References"
        wb.active.append(["Otra tabla"])
        contenido = BytesIO()
        wb.save(contenido)
        actual = contenido.getvalue()
    avisos = []
    assert preparar_referencias(ENLACE, config, avisos.append, respaldo=respaldo) == ruta
    assert ruta.read_bytes() == respaldo.read_bytes() == inicial
    assert any("Aviso:" in a and "copia local" in a and "guardada el" in a for a in avisos)
    assert not list(tmp_path.glob("*.tmp.xlsx"))


def test_primer_fallo_usa_respaldo_inicial_y_luego_actualiza(monkeypatch, tmp_path):
    respaldo = tmp_path / "referencias.xlsx"
    inicial = _xlsx()
    respaldo.write_bytes(inicial)
    config = {"archivo": tmp_path / "data" / "icam.json"}
    async def fallar(*args):
        raise OSError("Sin conexión")
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", fallar)
    avisos = []
    assert preparar_referencias(ENLACE, config, avisos.append, respaldo=respaldo) == respaldo
    assert any("Sin conexión" in a and str(respaldo) in a for a in avisos)
    nuevo = _xlsx("FDR NUEVO")
    async def descargar(*args):
        return nuevo
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    ruta = preparar_referencias(ENLACE, config, avisos.append, respaldo=respaldo)
    assert ruta != respaldo and ruta.read_bytes() == nuevo
    assert respaldo.read_bytes() == nuevo


def test_consulta_online_cada_vez_y_no_reescribe_copias_identicas(monkeypatch, tmp_path):
    respaldo = tmp_path / "referencias.xlsx"
    contenido = _xlsx()
    respaldo.write_bytes(contenido)
    consultas = []
    async def descargar(*args):
        consultas.append(args[0])
        return contenido
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    config = {"archivo": tmp_path / "data" / "icam.json"}
    ruta = preparar_referencias(ENLACE, config, respaldo=respaldo)
    for copia in (ruta, respaldo):
        os.utime(copia, (1600000000, 1600000000))
    avisos = []
    assert preparar_referencias(ENLACE, config, avisos.append, respaldo=respaldo) == ruta
    assert consultas == [ENLACE, ENLACE]
    assert all(c.stat().st_mtime == 1600000000 for c in (ruta, respaldo))
    assert any("sin cambios" in a for a in avisos)


def test_cambio_online_actualiza_ambas_copias(monkeypatch, tmp_path):
    respaldo = tmp_path / "referencias.xlsx"
    respaldo.write_bytes(_xlsx())
    contenido = _xlsx()
    async def descargar(*args):
        return contenido
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    config = {"archivo": tmp_path / "data" / "icam.json"}
    ruta = preparar_referencias(ENLACE, config, respaldo=respaldo)
    contenido = _xlsx("REFERENCIA ACTUALIZADA")
    preparar_referencias(ENLACE, config, respaldo=respaldo)
    assert ruta.read_bytes() == respaldo.read_bytes() == contenido


def test_copia_principal_bloqueada_no_impide_usar_online(monkeypatch, tmp_path):
    respaldo = tmp_path / "referencias.xlsx"
    inicial = _xlsx()
    respaldo.write_bytes(inicial)
    nuevo = _xlsx("REFERENCIA ACTUALIZADA")
    async def descargar(*args):
        return nuevo
    def bloqueada(*args):
        raise PermissionError("Archivo abierto en Excel")
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    monkeypatch.setattr("dips_audit.fuente_referencias._guardar_si_cambio", bloqueada)
    avisos = []
    ruta = preparar_referencias(ENLACE, {"archivo": tmp_path / "data" / "icam.json"},
                               avisos.append, respaldo=respaldo)
    assert ruta.read_bytes() == nuevo and respaldo.read_bytes() == inicial
    assert any("no se pudo actualizar la copia local" in a for a in avisos)


def test_no_sustituye_un_respaldo_de_otro_formato(monkeypatch, tmp_path):
    respaldo = tmp_path / "referencias.pdf"
    respaldo.write_bytes(b"%PDF-copia anterior")
    async def descargar(*args):
        return _xlsx()
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    preparar_referencias(ENLACE, {"archivo": tmp_path / "icam.json"}, respaldo=respaldo)
    assert respaldo.read_bytes() == b"%PDF-copia anterior"


def test_sin_respaldo_valido_informa_error(monkeypatch, tmp_path):
    async def fallar(*args):
        raise OSError("Sin conexión")
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", fallar)
    respaldo = tmp_path / "referencias.xlsx"
    respaldo.write_bytes(b"archivo roto")
    with pytest.raises(ErrorCatalogo, match="no hay una copia local válida"):
        preparar_referencias(ENLACE, {"archivo": tmp_path / "icam.json"}, respaldo=respaldo)


def test_cli_prefiere_sharepoint_y_respeta_fuente_explicita(monkeypatch, tmp_path):
    from dips_audit import __main__ as cli
    from dips_audit.auditor import cargar_configuracion

    config = cargar_configuracion()
    config["icam"]["archivo"] = tmp_path / "icam.json"
    config["referencias"] = tmp_path / "referencias.xlsx"
    config["referencias_sharepoint"] = ENLACE
    monkeypatch.setattr(cli, "cargar_configuracion", lambda _: dict(config))
    descargados = []
    async def descargar(enlace, *_):
        descargados.append(enlace)
        return _xlsx()
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    usadas = []
    def referencias(args, c):
        usadas.append(c["referencias"])
        return 0
    monkeypatch.setattr(cli, "cmd_referencias", referencias)
    assert cli.main(["referencias"]) == 0
    assert descargados == [ENLACE] and usadas[0].parent == tmp_path
    assert cli.main(["referencias", "--referencias", str(config["referencias"])]) == 0
    assert descargados == [ENLACE] and usadas[1] == config["referencias"]


@pytest.mark.parametrize("sharepoint, falla", [(True, False), (True, True), (False, False)])
def test_abrir_edge_actualiza_referencias_y_cierra_siempre(monkeypatch, config, sharepoint, falla):
    from dips_audit import __main__ as cli

    config = {**config, "referencias_sharepoint": ENLACE if sharepoint else ""}
    monkeypatch.setattr(cli, "cargar_configuracion", lambda _: config)
    monkeypatch.setattr("dips_audit.extractor_icam.edge_activo", lambda _: True)
    monkeypatch.setattr("dips_audit.extractor_icam.abrir_edge", lambda _: None)
    cerrados = []
    monkeypatch.setattr("dips_audit.extractor_icam.cerrar_edge", lambda p: cerrados.append(p) or 1)
    llamadas = []
    def preparar(fuente, icam, avisar, **opciones):
        llamadas.append((fuente, opciones))
        if falla:
            raise ErrorCatalogo("No se pudo actualizar ni usar un respaldo.")
        return config["referencias"]
    monkeypatch.setattr("dips_audit.fuente_referencias.preparar_referencias", preparar)
    assert cli.main(["abrir-icam"]) == (1 if falla else 0)
    assert llamadas == ([(ENLACE, {"respaldo": config["referencias"], "hoja": "References"})]
                        if sharepoint else [])
    assert cerrados == [config["icam"]["perfil"]]


@pytest.mark.parametrize("descarga_directa", [False, True])
@pytest.mark.parametrize("url_inicial", ["https://copa.ifs.cloud/maintenix/", "about:blank", ENLACE])
def test_sharepoint_abre_pagina_en_contexto_existente(monkeypatch, descarga_directa, url_inicial):
    from dips_audit.fuente_referencias import _descargar

    class Pagina:
        url = url_inicial
        async def goto(self, url, **kwargs):
            self.url = url
            if descarga_directa:
                raise RuntimeError("Download is starting")
        async def bring_to_front(self):
            pass
        def is_closed(self):
            return False
    class Respuesta:
        ok = True
        async def body(self):
            return b"PK\x03\x04XLSX"
    class Contexto:
        def __init__(self):
            self.pages = [Pagina()]
            self.request = self
        async def new_page(self):
            pagina = Pagina()
            self.pages.append(pagina)
            return pagina
        async def get(self, *args, **kwargs):
            assert kwargs["headers"] == {"Cache-Control": "no-cache"}
            return Respuesta()
    contexto = Contexto()
    class Navegador:
        selector_error_sesion = "#errorText"
        def __init__(self, config):
            self._contexto = contexto
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    monkeypatch.setattr("dips_audit.extractor_icam.ExtractorICAM", Navegador)
    assert asyncio.run(_descargar(ENLACE, {}, lambda _: None)) == b"PK\x03\x04XLSX"
    assert contexto.pages[-1].url == ENLACE
    assert len(contexto.pages) == (2 if url_inicial.startswith("https://copa.ifs.cloud") else 1)
