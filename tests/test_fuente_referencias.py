import asyncio
from urllib.parse import parse_qs, urlsplit

import pytest

from dips_audit.fuente_referencias import _urls_descarga, preparar_referencias
from dips_audit.referencias import ErrorCatalogo


ENLACE = ("https://copaairlines.sharepoint.com/:x:/r/teams/VP_Tecnica/dacre/records/"
          "_layouts/15/doc2.aspx?sourcedoc=%7B71427FA7-2DB0-4851-A5BA-63F30401684E%7D"
          "&file=DIPs%20References.xlsx&action=default")


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
    async def descargar(*args):
        return b"PK\x03\x04XLSX"
    monkeypatch.setattr("dips_audit.fuente_referencias._descargar", descargar)
    ruta = preparar_referencias(ENLACE, {"archivo": tmp_path / "icam.json"})
    assert ruta.parent == tmp_path and ruta.suffix == ".xlsx"
    assert ruta.read_bytes() == b"PK\x03\x04XLSX"


@pytest.mark.parametrize("descarga_directa", [False, True])
def test_sharepoint_abre_pagina_en_contexto_existente(monkeypatch, descarga_directa):
    from dips_audit.fuente_referencias import _descargar

    class Pagina:
        url = "https://copa.ifs.cloud/maintenix/"
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
    assert contexto.pages[1].url == ENLACE
