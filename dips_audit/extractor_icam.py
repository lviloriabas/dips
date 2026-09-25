"""Lectura de DIPs en ICAM por barcode (web scraping, solo lectura).

Usa el Edge de ICAM del programa (perfil `.icam_perfil/`, puerto de depuración local), que
convive con el Edge de uso diario. Ese Edge se abre directo en ICAM y la sesión se inicia
ahí: si no hay sesión, el programa sigue apenas el usuario la inicia en esa ventana, y se
detiene apenas la página de inicio de sesión muestra un error.
Nunca completa la página de inicio de sesión.

Por cada barcode hace, con la sesión de Edge, las mismas consultas que el navegador:
  1. POST /maintenix/servlet/ScanBarcode (Barcode Search) -> página del DIP.
  2. GET de cada pestaña (Fault Information, Task Information, Scheduling, History).
El HTML se muestra en una página aislada (sin red y sin los scripts de ICAM) y se copia el
texto visible de cada pestaña (`#idTab<Pestaña>`). Todos los DIPs se guardan juntos en un solo
JSON (`data/icam.json`, `{"records": [...]}`), un registro por barcode con el formato de la
extracción manual (`sections.<pestaña>.text`); `icam.py` lo interpreta.

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
# Mensaje de error de la página de inicio de sesión (Keycloak de ICAM; Microsoft).
_ERROR_SESION = ("#input-error, .alert-error, .pf-m-danger, #usernameError, #passwordError, "
                 "#errorText")
# Lee la página del DIP ya mostrada en la página aislada.
_LEER = """(pestana) => {
    const texto = (sel) => (document.querySelector(sel)?.textContent || '').replace(/\\s+/g, ' ').trim();
    const nodo = document.querySelector('#idTab' + pestana);
    // Las pestañas no activas vienen ocultas (display:none) y las tablas con visibility:hidden
    // (las muestran los scripts de ICAM, que aquí no corren). Oculto, innerText sale sin tabs
    // ni filas de tabla: se muestran la pestaña, su contenido y sus contenedores.
    const mostrar = (el) => {
        if (!el.style) return;
        if (el.style.display === 'none') el.style.display = '';
        if (el.style.visibility === 'hidden') el.style.visibility = 'visible';
        el.removeAttribute('hidden');
    };
    if (nodo) {
        for (let el = nodo; el && el.style; el = el.parentElement) mostrar(el);
        nodo.querySelectorAll('[style], [hidden]').forEach(mostrar);
    }
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


# ------------------------------------------------------------------ JSON con todos los DIPs
def _mas_reciente(a: dict | None, b: dict) -> dict:
    return b if a is None or b.get("captured_at_utc", "") >= a.get("captured_at_utc", "") else a


def guardar_registros(archivo: Path, registros: dict[str, dict]) -> None:
    """Guarda todos los DIPs en un solo JSON, ordenados por barcode. Se escribe en un
    temporal y se reemplaza: nunca queda un archivo a medias."""
    archivo = Path(archivo)
    archivo.parent.mkdir(parents=True, exist_ok=True)
    temporal = archivo.with_suffix(".tmp")
    temporal.write_text(json.dumps({"records": [registros[b] for b in sorted(registros)]},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
    temporal.replace(archivo)


def cargar_registros(archivo: Path) -> dict[str, dict]:
    """DIPs guardados en `archivo`, por barcode. Si quedan JSON sueltos de versiones
    anteriores (un archivo por DIP en la carpeta del mismo nombre, p. ej. `data/icam/`),
    se unen a `archivo` (queda la lectura más reciente de cada DIP) y se borran."""
    archivo = Path(archivo)
    registros: dict[str, dict] = {}
    if archivo.exists():
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        for r in datos.get("records", [datos]) if isinstance(datos, dict) else datos:
            registros[r["barcode"]] = _mas_reciente(registros.get(r["barcode"]), r)
    carpeta = archivo.with_suffix("")
    sueltos = sorted(carpeta.glob("*.json")) if carpeta.is_dir() else []
    if sueltos:
        for x in sueltos:
            r = json.loads(x.read_text(encoding="utf-8"))
            registros[r["barcode"]] = _mas_reciente(registros.get(r["barcode"]), r)
        guardar_registros(archivo, registros)
        for x in sueltos:
            x.unlink()
        for x in carpeta.glob("*.tmp"):
            x.unlink()
        if not any(carpeta.iterdir()):
            carpeta.rmdir()
    return registros


def leer_registro(archivo: Path, barcode: str) -> dict | None:
    return cargar_registros(archivo).get(barcode)


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
        self.selector_error_sesion = config.get("selector_error_sesion") or _ERROR_SESION
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

    async def _estado_sesion(self) -> tuple[str, object]:
        """Estado de la ventana de ICAM, en orden de prioridad:
        ("sesion", página con Barcode Search) | ("error", mensaje de la página de inicio de
        sesión) | ("login", None) si espera usuario y contraseña | ("cargando", None) |
        ("cerrada", None) si no queda ninguna ventana."""
        estados = []
        for pagina in list(self._contexto.pages):
            try:
                if not pagina.url.startswith("http"):
                    continue
                if self._en_icam(pagina.url) and await pagina.locator(
                        self.selector_busqueda).first.is_visible():
                    return "sesion", pagina
                error = pagina.locator(self.selector_error_sesion).filter(visible=True)
                if await error.count():
                    texto = " ".join((await error.first.inner_text()).split())
                    estados.append(("error", texto or "error al iniciar sesión"))
                elif (await pagina.evaluate("document.readyState") == "complete"
                      and await pagina.locator("input:visible").count()):
                    estados.append(("login", None))
                else:
                    estados.append(("cargando", None))
            except Exception:  # la página se cerró o está navegando
                estados.append(("cargando", None))
        if not self._contexto.pages:
            return "cerrada", None
        for estado in ("error", "login"):
            for e in estados:
                if e[0] == estado:
                    return e
        return "cargando", None

    async def verificar_sesion(self) -> None:
        """Abre ICAM directo (no la página de inicio de sesión) y confirma la sesión. Sin
        sesión, el usuario la inicia en la ventana de Edge: el programa revisa esa ventana
        cada medio segundo y sigue apenas se inicia, o se detiene apenas la página de inicio
        de sesión muestra un error o se cierra la ventana. Nunca completa esa página."""
        propia = None
        # Si el programa acaba de abrir Edge, esa ventana ya arranca en ICAM.
        if self._proceso is None and not any(self._en_icam(p.url) for p in self._contexto.pages):
            propia = await self._contexto.new_page()
            await propia.goto(self.url, wait_until="domcontentloaded", timeout=self.espera_ms)
            await propia.bring_to_front()
        minutos = float(self.config.get("espera_sesion_minutos",
                                        0 if self.config.get("oculto") else 3))
        limite = time.monotonic() + self.espera_ms / 1000   # para que cargue ICAM
        avisado = False
        while True:
            estado, dato = await self._estado_sesion()
            if estado == "sesion":
                pagina = dato
                break
            if estado == "error":
                raise ErrorSesion(f"No se pudo iniciar sesión en ICAM: {dato}. Revise el usuario "
                                  "y la contraseña y vuelva a ejecutar.")
            if estado == "cerrada":
                raise ErrorSesion("Se cerró la ventana de ICAM sin iniciar sesión. Vuelva a "
                                  "ejecutar e inicie sesión en esa ventana.")
            if estado == "login" and not avisado:
                if not minutos:
                    raise ErrorSesion("No hay sesión iniciada en ICAM. Inicie sesión en la "
                                      "ventana de Edge de ICAM y vuelva a ejecutar.")
                self.al_avanzar("No hay sesión iniciada en ICAM. Inicie sesión en la ventana de "
                                "Edge que se abrió; el programa sigue apenas se inicie.")
                avisado = True
                limite = time.monotonic() + minutos * 60
            if time.monotonic() > limite:
                raise ErrorSesion(
                    f"No se inició sesión en ICAM en {minutos:g} minutos. Inicie sesión en la "
                    "ventana de Edge de ICAM y vuelva a ejecutar." if avisado else
                    "ICAM no cargó: no se vio la página de inicio ni la de inicio de sesión.")
            await asyncio.sleep(0.5)
        if avisado:
            self.al_avanzar("Sesión de ICAM iniciada.")
        accion = await pagina.locator("form[name='frmHeaderSearch']").first.get_attribute("action")
        if not accion:
            raise ErrorExtraccion("No se encontró el formulario Barcode Search en ICAM.")
        self._busqueda = urljoin(self.origen, accion)
        if not self._en_icam(self._busqueda):
            raise ErrorExtraccion(f"Búsqueda fuera de ICAM: {self._busqueda}")
        # La página que abrió el programa se cierra si queda otra de ICAM (la del usuario).
        if propia and len([p for p in self._contexto.pages if self._en_icam(p.url)]) > 1:
            await propia.close()

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


def _minutos(segundos: float) -> str:
    """Tiempo estimado como '2 min 05 s' (o '45 s' si es menos de un minuto)."""
    m, s = divmod(round(segundos), 60)
    return f"{m} min {s:02d} s" if m else f"{s} s"


async def _extraer(pendientes: list[str], config: dict, registros: dict[str, dict],
                   guardar: Callable[[], None], avisar: Callable[[str], None],
                   estado: dict[str, str]) -> None:
    cola: asyncio.Queue[str] = asyncio.Queue()
    for b in pendientes:
        cola.put_nowait(b)
    inicio, hechos = time.monotonic(), [0]
    total = len(pendientes)
    ancho, ancho_barcode = len(str(total)), max(map(len, pendientes))
    async with ExtractorICAM(config, avisar) as ext:
        await ext.verificar_sesion()

        async def trabajador():
            while not cola.empty():
                barcode = cola.get_nowait()
                try:
                    registros[barcode] = await ext.leer(barcode)
                    estado[barcode] = "leido"
                    guardar()
                except ErrorSesion:
                    raise
                except Exception as e:
                    estado[barcode] = f"error: {e}"
                hechos[0] += 1
                falta = (time.monotonic() - inicio) / hechos[0] * (total - hechos[0])
                resultado, _, detalle = estado[barcode].partition(": ")
                avisar(f"[{hechos[0]:>{ancho}}/{total}]  {barcode:<{ancho_barcode}}  "
                       f"{resultado:<5}  falta ~{_minutos(falta):>9}"
                       + (f"  {detalle}" if detalle else ""))

        paralelo = max(1, min(int(config.get("paralelo", 3)), len(pendientes)))
        await asyncio.gather(*(trabajador() for _ in range(paralelo)))


def extraer(barcodes: list[str], config: dict, archivo: Path,
            al_avanzar: Callable[[str], None] | None = None) -> dict[str, str]:
    """Lee en ICAM todos los barcodes, aunque ya estén en `archivo`, para auditar siempre
    con los datos actuales (p. ej. la acción correctiva y los adjuntos del cierre). Cada DIP
    leído se agrega (o reemplaza) en `archivo`, junto a los demás.

    Devuelve {barcode: "leido" | "error: ..."}. Sin sesión, o si la sesión vence, lanza
    ErrorSesion (lo ya leído queda guardado).
    """
    avisar = al_avanzar or (lambda _: None)
    registros = cargar_registros(archivo)
    estado: dict[str, str] = {}
    pendientes = list(dict.fromkeys(barcodes))
    ultimo = [time.monotonic()]
    cambios = [False]

    def guardar(siempre: bool = False) -> None:
        # Todo el JSON se reescribe: a lo sumo cada 5 s y al terminar (también si falla).
        cambios[0] = True
        if siempre or time.monotonic() - ultimo[0] >= 5:
            guardar_registros(archivo, registros)
            ultimo[0], cambios[0] = time.monotonic(), False

    if pendientes:
        try:
            asyncio.run(_extraer(pendientes, config, registros, guardar, avisar, estado))
        finally:
            if cambios[0]:
                guardar(siempre=True)
    return estado
