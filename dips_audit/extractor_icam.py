"""Lectura de DIPs en ICAM por barcode (web scraping, solo lectura).

Usa el Edge de ICAM del programa (perfil `.icam_perfil/`, puerto de depuración local), que
convive con el Edge de uso diario. Ese Edge se abre directo en ICAM y la sesión se inicia
ahí antes de auditar. El programa usa esa sesión: nunca abre ni completa la página de
inicio de sesión. Sin sesión, avisa y termina.

Por cada barcode hace, con la sesión de Edge, las mismas consultas que el navegador:
  1. POST /maintenix/servlet/ScanBarcode (Barcode Search) -> página del DIP.
  2. GET de cada pestaña (Fault Information, Task Information, Scheduling, History).
El HTML se muestra en una página aislada (sin red y sin los scripts de ICAM) y se copia el
texto visible de cada pestaña (`#idTab<Pestaña>`). Se guarda en `data/icam/<barcode>.json`
con el formato de la extracción manual (`sections.<pestaña>.text`); `icam.py` lo interpreta.

Solo lectura: las únicas consultas a ICAM son la búsqueda y los GET de las pestañas. No se
abre ningún formulario de edición ni se ejecuta código de ICAM.
Rapidez: no se dibujan páginas ni se descargan imágenes; varios DIPs a la vez y las
pestañas de cada DIP en paralelo; un DIP ya leído no se vuelve a leer.
Sin errores: cada respuesta se valida (página del DIP, barcode correcto, contenido de la
pestaña); cada consulta se reintenta; un DIP incompleto no se guarda; si la sesión vence,
la lectura se detiene y lo leído queda guardado.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from .icam import PESTANAS, leer_tareas_siguientes

_RUTA_DIP = "/maintenix/web/task/TaskDetails.jsp"
# Texto que confirma que cada pestaña trae su contenido (y no una página de error).
_MARCAS = {
    "TaskExecution": ("Description",),
    "FaultInformation": ("Fault Status", "Fault Severity"),
    "TaskInformation": ("Parent Assembly", "Technical References"),
    "Scheduling": ("Deadline", "Interval", "Due"),
    "History": ("UTC",),
}
# Lee la página del DIP ya mostrada en la página aislada.
_LEER = """(pestana) => {
    const texto = (sel) => (document.querySelector(sel)?.textContent || '').replace(/\\s+/g, ' ').trim();
    const nodo = document.querySelector('#idTab' + pestana);
    return {
        titulo: document.title,
        barcode: texto('#idBarcode'),
        texto: nodo ? nodo.innerText : '',
        pestanas: Object.fromEntries(Array.from(document.querySelectorAll('a[id^="idTab"][id$="_link"]'))
            .map(a => [a.id.slice(5, -5), a.getAttribute('href')])),
        historico: (Array.from(document.querySelectorAll('a'))
            .find(a => /historical tasks/i.test(a.textContent)) || {getAttribute: () => null})
            .getAttribute('href'),
    };
}"""


class ErrorExtraccion(Exception):
    pass


class ErrorSesion(ErrorExtraccion):
    """No hay sesión iniciada en ICAM (o venció durante la lectura)."""


def ruta_cache(carpeta: Path, barcode: str) -> Path:
    return Path(carpeta) / f"{re.sub(r'[^A-Za-z0-9_-]', '_', barcode)}.json"


def pestana_valida(nombre: str, texto: str) -> bool:
    return any(m in texto for m in _MARCAS.get(nombre, ("",)))


def _sin_scripts(html: str) -> str:
    """Quita scripts y atributos on* (onload, onclick...): en la página aislada no corre
    código de ICAM."""
    html = re.sub(r"<script\b.*?</script\s*>", "", html, flags=re.I | re.S)
    return re.sub(r"\s on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", html, flags=re.I)


# ------------------------------------------------------------------ Edge de ICAM
def ruta_edge() -> str:
    candidatos = [os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
                  os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
                  shutil.which("msedge") or ""]
    for c in candidatos:
        if c and Path(c).exists():
            return c
    raise ErrorExtraccion("No se encontró Microsoft Edge en el equipo.")


def edge_activo(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/json/version", timeout=1):
            return True
    except OSError:
        return False


def abrir_edge(config: dict) -> subprocess.Popen | None:
    """Abre el Edge de ICAM directo en ICAM, si no está abierto."""
    puerto = int(config.get("puerto", 9222))
    if edge_activo(puerto):
        return None
    perfil = Path(config["perfil"])
    perfil.mkdir(parents=True, exist_ok=True)
    argumentos = [ruta_edge(), f"--remote-debugging-port={puerto}", f"--user-data-dir={perfil}",
                  "--no-first-run", "--no-default-browser-check"]
    if config.get("oculto"):
        argumentos.append("--headless=new")
    argumentos.append(config["url"])
    banderas = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED | NEW_PROCESS_GROUP
    proceso = subprocess.Popen(argumentos, creationflags=banderas, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    limite = time.monotonic() + 30
    while time.monotonic() < limite:
        if edge_activo(puerto):
            return proceso
        time.sleep(0.3)
    raise ErrorExtraccion("El Edge de ICAM no respondió.")


# ------------------------------------------------------------------ lectura
class ExtractorICAM:
    def __init__(self, config: dict, al_avanzar: Callable[[str], None] | None = None):
        self.config = config
        self.url = config["url"]
        self.origen = "{0.scheme}://{0.netloc}".format(urlparse(self.url))
        self.puerto = int(config.get("puerto", 9222))
        self.selector_busqueda = config.get("selector_busqueda") or "#idBarcodeSearchInput"
        self.espera_ms = float(config.get("espera_segundos", 30)) * 1000
        self.intentos = int(config.get("intentos", 3))
        self.al_avanzar = al_avanzar or (lambda _: None)
        self._pw = self._navegador = self._contexto = None
        self._proceso: subprocess.Popen | None = None
        self._busqueda = ""   # URL del formulario Barcode Search (ScanBarcode)

    async def __aenter__(self) -> ExtractorICAM:
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise ErrorExtraccion("Falta la librería playwright. Ejecute setup.bat.") from e
        self._proceso = abrir_edge(self.config)
        self._pw = await async_playwright().start()
        self._navegador = await self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{self.puerto}")
        self._contexto = self._navegador.contexts[0]
        return self

    async def __aexit__(self, *exc) -> None:
        cerrar = self._proceso is not None and self.config.get("cerrar_al_terminar")
        if self._navegador:
            if cerrar:  # Edge abierto solo para esta corrida (pruebas)
                sesion = await self._navegador.new_browser_cdp_session()
                try:
                    await sesion.send("Browser.close")
                except Exception:
                    pass
            await self._navegador.close()  # se desconecta; la ventana y la sesión quedan abiertas
        if self._pw:
            await self._pw.stop()
        if cerrar:
            try:
                self._proceso.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proceso.kill()

    def _en_icam(self, url: str) -> bool:
        return url.startswith(self.origen)

    async def verificar_sesion(self) -> None:
        """Abre ICAM directo (no la página de inicio de sesión) y confirma la sesión."""
        pagina = next((p for p in self._contexto.pages if self._en_icam(p.url)), None)
        propia = pagina is None
        if propia:
            pagina = await self._contexto.new_page()
            await pagina.goto(self.url, wait_until="domcontentloaded", timeout=self.espera_ms)
        try:
            caja = pagina.locator(self.selector_busqueda).first
            try:
                await caja.wait_for(state="visible", timeout=10000)
            except Exception:
                raise ErrorSesion("No hay sesión iniciada en ICAM. Abra abrir_icam.bat, inicie "
                                  "sesión y vuelva a ejecutar.") from None
            accion = await pagina.locator("form[name='frmHeaderSearch']").first.get_attribute("action")
            if not accion:
                raise ErrorExtraccion("No se encontró el formulario Barcode Search en ICAM.")
            self._busqueda = urljoin(self.origen, accion)
            if not self._en_icam(self._busqueda):
                raise ErrorExtraccion(f"Búsqueda fuera de ICAM: {self._busqueda}")
        finally:
            if propia:
                await pagina.close()

    async def pagina_aislada(self):
        """Página donde se muestra el HTML de ICAM: sin red y sin scripts."""
        pagina = await self._contexto.new_page()
        await pagina.route("**/*", lambda ruta: ruta.abort())
        return pagina

    async def _leer_respuesta(self, respuesta, aislada, pestana: str, barcode: str,
                              validar: bool = True) -> dict:
        url = respuesta.url
        if not self._en_icam(url) or "login" in url.lower():
            raise ErrorSesion("La sesión de ICAM venció. Inicie sesión en el Edge de ICAM y "
                              "vuelva a ejecutar.")
        if not respuesta.ok or _RUTA_DIP not in url:
            raise ErrorExtraccion(f"{pestana}: respuesta {respuesta.status} ({url[:80]})")
        await aislada.set_content(_sin_scripts(await respuesta.text()), wait_until="domcontentloaded")
        datos = await aislada.evaluate(_LEER, pestana)
        if datos["barcode"] and datos["barcode"] != barcode:
            raise ErrorExtraccion(f"ICAM devolvió {datos['barcode']} en vez de {barcode}")
        if validar and not pestana_valida(pestana, datos["texto"]):
            raise ErrorExtraccion(f"la pestaña {pestana} vino sin contenido")
        return datos

    async def _reintentar(self, paso: Callable, que: str):
        ultimo: Exception | None = None
        for intento in range(self.intentos):
            try:
                return await paso()
            except ErrorSesion:
                raise
            except Exception as e:
                ultimo = e
                await asyncio.sleep(0.5 * (intento + 1))
        raise ErrorExtraccion(f"{que}: {ultimo}")

    async def _buscar(self, barcode: str, validar: bool = True) -> tuple[str, dict]:
        """Barcode Search: devuelve (URL de la tarea, datos de su primera pestaña)."""
        aislada = await self.pagina_aislada()
        try:
            r = await self._contexto.request.post(
                self._busqueda, form={"aBarcodeScan": barcode, "aReturnToPage": ""},
                timeout=self.espera_ms)
            return r.url, await self._leer_respuesta(r, aislada, "TaskExecution", barcode, validar)
        finally:
            await aislada.close()

    async def _get(self, url: str, pestana: str, barcode: str, validar: bool = True) -> dict:
        aislada = await self.pagina_aislada()
        try:
            r = await self._contexto.request.get(url, timeout=self.espera_ms)
            return await self._leer_respuesta(r, aislada, pestana, barcode, validar)
        finally:
            await aislada.close()

    def _url_pestana(self, url_tarea: str, enlaces: dict, nombre: str) -> str:
        href = enlaces.get(nombre) or f"{url_tarea.split('?')[0]}?{_consulta(url_tarea, nombre)}"
        return urljoin(url_tarea, href)

    async def _leer_rir(self, rir_id: str) -> dict:
        """Página de un RIR (tarea ADHOC): Scheduling y Task Information."""
        url, primera = await self._reintentar(lambda: self._buscar(rir_id, validar=False),
                                              f"búsqueda RIR {rir_id}")
        textos = await asyncio.gather(*(
            self._reintentar(lambda n=n: self._get(self._url_pestana(url, primera["pestanas"], n),
                                                   n, rir_id), f"RIR {rir_id} {n}")
            for n in ("Scheduling", "TaskInformation")))
        return {"page_url": url, "page_title": primera["titulo"],
                "sections": {"Scheduling": {"text": textos[0]["texto"]},
                             "TaskInformation": {"text": textos[1]["texto"]}}}

    async def leer(self, barcode: str) -> dict:
        """Búsqueda, pestañas en paralelo y RIR. Cada consulta se reintenta sola."""
        url_dip, primera = await self._reintentar(lambda: self._buscar(barcode), "búsqueda")
        otras = [n for n in PESTANAS if n != "TaskExecution"]
        datos = await asyncio.gather(*(
            self._reintentar(lambda n=n: self._get(self._url_pestana(url_dip, primera["pestanas"], n),
                                                   n, barcode), n)
            for n in otras))
        secciones = {"TaskExecution": {"text": primera["texto"]}}
        secciones.update({n: {"text": d["texto"]} for n, d in zip(otras, datos)})
        registro = {"barcode": barcode, "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                    "page_title": primera["titulo"], "page_url": url_dip, "sections": secciones}

        # RIR: Follow-on Tasks cerradas (Show Historical Tasks) y la página de cada RIR vigente.
        # Un problema aquí no invalida el DIP: queda anotado en "rir_errores".
        errores: dict[str, str] = {}
        falla = dict(zip(otras, datos))["FaultInformation"]
        historico = falla.get("historico")
        if historico and not historico.lower().startswith("javascript"):
            try:
                h = await self._reintentar(lambda: self._get(urljoin(url_dip, historico),
                                                             "FaultInformation", barcode),
                                           "Show Historical Tasks")
                secciones["FollowOnHistorico"] = {"text": h["texto"]}
            except ErrorSesion:
                raise
            except Exception as e:
                errores["historico"] = str(e)
        tareas = leer_tareas_siguientes(falla["texto"])
        if "FollowOnHistorico" in secciones:
            tareas += leer_tareas_siguientes(secciones["FollowOnHistorico"]["text"])
        vigentes: dict[str, str] = {}
        for t in tareas:
            if t.es_rir and (t.nombre not in vigentes or t.estado.upper() == "ACTV"):
                vigentes[t.nombre] = t.id
        rir: dict[str, dict] = {}
        for rir_id in dict.fromkeys(vigentes.values()):
            try:
                rir[rir_id] = await self._leer_rir(rir_id)
            except ErrorSesion:
                raise
            except Exception as e:
                errores[rir_id] = str(e)
        if rir:
            registro["rir"] = rir
        if errores:
            registro["rir_errores"] = errores
        return registro


def _consulta(url: str, pestana: str) -> str:
    """Parámetros de la URL del DIP con aTab de la pestaña (si ICAM no trae el enlace)."""
    partes = [p for p in urlparse(url).query.split("&") if p and not p.startswith("aTab=")]
    return "&".join(partes + [f"aTab={PESTANAS[pestana]}"])


async def _extraer(pendientes: list[str], config: dict, carpeta: Path,
                   avisar: Callable[[str], None], estado: dict[str, str]) -> None:
    cola: asyncio.Queue[str] = asyncio.Queue()
    for b in pendientes:
        cola.put_nowait(b)
    inicio, hechos = time.monotonic(), [0]
    async with ExtractorICAM(config, avisar) as ext:
        await ext.verificar_sesion()

        async def trabajador():
            while not cola.empty():
                barcode = cola.get_nowait()
                t0 = time.monotonic()
                try:
                    registro = await ext.leer(barcode)
                    ruta = ruta_cache(carpeta, barcode)
                    temporal = ruta.with_suffix(".tmp")
                    temporal.write_text(json.dumps(registro, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
                    temporal.replace(ruta)   # nunca queda un archivo a medias
                    estado[barcode] = "leido"
                except ErrorSesion:
                    raise
                except Exception as e:
                    estado[barcode] = f"error: {e}"
                hechos[0] += 1
                falta = (time.monotonic() - inicio) / hechos[0] * (len(pendientes) - hechos[0])
                avisar(f"[{hechos[0]}/{len(pendientes)}] {barcode}: {estado[barcode]} "
                       f"({time.monotonic() - t0:.1f} s) · falta ~{falta:.0f} s")

        paralelo = max(1, min(int(config.get("paralelo", 3)), len(pendientes)))
        await asyncio.gather(*(trabajador() for _ in range(paralelo)))


def extraer(barcodes: list[str], config: dict, carpeta: Path, actualizar: bool = False,
            al_avanzar: Callable[[str], None] | None = None) -> dict[str, str]:
    """Lee en ICAM los barcodes que no están en `carpeta` (o todos si `actualizar`).

    Devuelve {barcode: "leido" | "en cache" | "error: ..."}. Sin sesión, o si la sesión
    vence, lanza ErrorSesion (lo ya leído queda guardado).
    """
    avisar = al_avanzar or (lambda _: None)
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    estado = {b: "en cache" for b in barcodes if not actualizar and ruta_cache(carpeta, b).exists()}
    pendientes = [b for b in dict.fromkeys(barcodes) if b not in estado]
    if pendientes:
        asyncio.run(_extraer(pendientes, config, carpeta, avisar, estado))
    return estado
