"""Descarga una tabla de referencias de SharePoint con la sesión del Edge de ICAM."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .referencias import ErrorCatalogo, cargar_referencias


def es_sharepoint(valor: object) -> bool:
    url = urlsplit(str(valor))
    return url.scheme == "https" and bool(url.hostname) and url.hostname.endswith(".sharepoint.com")


def _urls_descarga(enlace: str) -> list[str]:
    url = urlsplit(enlace.replace("\\&", "&"))
    query = dict(parse_qsl(url.query, keep_blank_values=True))
    query.pop("action", None)
    query["download"] = "1"
    urls = [urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), ""))]
    if "sourcedoc" in query and "/_layouts/" in url.path:
        sitio = re.sub(r"^/:[a-z]:/r", "", url.path.split("/_layouts/", 1)[0], flags=re.I)
        consulta = urlencode({"UniqueId": query["sourcedoc"]})
        urls.append(urlunsplit((url.scheme, url.netloc, sitio + "/_layouts/15/download.aspx",
                               consulta, "")))
        segmentos = sitio.strip("/").split("/")
        if len(segmentos) >= 2 and segmentos[0] in {"teams", "sites"}:
            sitio = "/" + "/".join(segmentos[:2])
            urls.append(urlunsplit((url.scheme, url.netloc, sitio + "/_layouts/15/download.aspx",
                                   consulta, "")))
    return list(dict.fromkeys(urls))


async def _descargar(enlace: str, config_icam: dict, avisar) -> bytes:
    from .extractor_icam import ExtractorICAM

    async with ExtractorICAM({**config_icam, "url": enlace}) as navegador:
        paginas = navegador._contexto.pages
        pagina = next((p for p in paginas if es_sharepoint(p.url)), None)
        pagina = pagina or next((p for p in paginas if p.url == "about:blank"), None)
        pagina = pagina or await navegador._contexto.new_page()
        try:
            await pagina.goto(enlace, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            # Un enlace directo a XLSX inicia una descarga y cancela la navegación.
            if "download is starting" not in str(e).lower():
                raise ErrorCatalogo("No se pudo abrir SharePoint en Edge. Compruebe el enlace y "
                                    "el acceso a la red corporativa.") from e
        await pagina.bring_to_front()
        avisado = False
        minutos = float(config_icam.get("espera_sesion_minutos", 3))
        limite = time.monotonic() + max(1, minutos * 60)
        candidatos = _urls_descarga(enlace)
        while time.monotonic() < limite:
            if pagina.is_closed():
                raise ErrorCatalogo("Se cerró SharePoint antes de descargar las referencias.")
            for url in candidatos:
                try:
                    respuesta = await navegador._contexto.request.get(
                        url, timeout=20000, headers={"Cache-Control": "no-cache"})
                    if respuesta.ok:
                        contenido = await respuesta.body()
                        if contenido.startswith((b"PK\x03\x04", b"%PDF-")):
                            return contenido
                except Exception:
                    pass  # puede estar esperando el inicio de sesión en la ventana
            for p in list(navegador._contexto.pages):
                error = p.locator(navegador.selector_error_sesion).filter(visible=True)
                if await error.count():
                    raise ErrorCatalogo("No se pudo iniciar sesión en SharePoint: "
                                        + " ".join((await error.first.inner_text()).split()))
            if not avisado:
                avisar("Inicie sesión en SharePoint en la ventana de Edge; la descarga seguirá "
                       "automáticamente cuando tenga acceso.")
                avisado = True
            await asyncio.sleep(2)
    raise ErrorCatalogo("No se pudo descargar la referencia de SharePoint dentro del tiempo de espera. "
                        "Compruebe el acceso o descargue el XLSX/PDF y use --referencias RUTA.")


def _guardar_si_cambio(ruta: Path, contenido: bytes) -> bool:
    """Sustituye una copia atómicamente, sin reescribirla si ya coincide con la descarga."""
    if ruta.is_file() and ruta.read_bytes() == contenido:
        return False
    temporal = ruta.with_name(ruta.stem + ".tmp" + ruta.suffix)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal.write_bytes(contenido)
        temporal.replace(ruta)
    finally:
        temporal.unlink(missing_ok=True)
    return True


def preparar_referencias(fuente: str | Path, config_icam: dict, avisar=print, *,
                         respaldo: str | Path | None = None, hoja: str = "References") -> Path:
    """Consulta siempre SharePoint y sincroniza las copias locales solo si cambiaron.

    El respaldo principal se actualiza si tiene el mismo formato que la fuente online.
    Si SharePoint falla, se conserva y utiliza la última copia válida, con un aviso.
    """
    texto = str(fuente).replace("\\&", "&")
    if not texto.lower().startswith(("http://", "https://")):
        return Path(fuente)
    if not es_sharepoint(texto):
        raise ErrorCatalogo("Solo se admiten enlaces HTTPS de SharePoint o archivos locales.")
    query = dict(parse_qsl(urlsplit(texto.replace("\\&", "&")).query))
    nombre = query.get("file") or Path(urlsplit(texto).path).name
    extension = Path(nombre).suffix.lower()
    if extension not in {".xlsx", ".pdf"}:
        raise ErrorCatalogo("El enlace de SharePoint debe indicar un archivo XLSX o PDF.")
    destino = Path(config_icam["archivo"]).parent / (
        "referencias_sharepoint_" + hashlib.sha256(texto.encode()).hexdigest()[:12] + extension)
    temporal = destino.with_name(destino.stem + ".tmp" + extension)
    try:
        contenido = asyncio.run(_descargar(texto, config_icam, avisar))
        if ((extension == ".pdf" and not contenido.startswith(b"%PDF-")) or
                (extension == ".xlsx" and not contenido.startswith(b"PK\x03\x04"))):
            raise ErrorCatalogo("SharePoint devolvió un formato distinto al archivo solicitado.")
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal.write_bytes(contenido)
        if not cargar_referencias(temporal, hoja):
            raise ErrorCatalogo("La tabla descargada de SharePoint está vacía.")
        cambio = not destino.is_file() or destino.read_bytes() != contenido
        if cambio:
            temporal.replace(destino)
    except Exception as error:
        # Una respuesta de login, archivo corrupto o fallo de escritura no reemplaza el respaldo.
        for copia in dict.fromkeys([destino, *([Path(respaldo)] if respaldo else [])]):
            try:
                if not copia.is_file() or not cargar_referencias(copia, hoja):
                    continue
                fecha = datetime.fromtimestamp(copia.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            except Exception:
                continue
            motivo = str(error).rstrip(". ")
            avisar(f"Aviso: no se pudieron actualizar las referencias de SharePoint: {motivo}. "
                   f"Se usará la copia local {copia} (guardada el {fecha}); "
                   "puede estar desactualizada.")
            return copia
        raise ErrorCatalogo(f"No se pudieron actualizar las referencias de SharePoint y no hay "
                            f"una copia local válida. Motivo: {error}") from error
    finally:
        try:
            temporal.unlink(missing_ok=True)
        except OSError:
            pass  # un temporal bloqueado no impide utilizar el respaldo válido
    if respaldo and not str(respaldo).lower().startswith(("http://", "https://")):
        local = Path(respaldo)
        if local.suffix.lower() == extension and local != destino:
            try:
                if _guardar_si_cambio(local, contenido):
                    avisar(f"Copia local principal actualizada desde SharePoint: {local}")
            except OSError as error:
                avisar(f"Aviso: no se pudo actualizar la copia local {local}: {error}. "
                       f"Se usará la descarga verificada de SharePoint en {destino}.")
    estado = "actualizadas" if cambio else "comprobadas, sin cambios"
    avisar(f"Referencias {estado} desde SharePoint. Copia local: {destino}")
    return destino
