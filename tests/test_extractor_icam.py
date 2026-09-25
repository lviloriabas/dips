"""Extractor de ICAM contra un ICAM simulado en el equipo (no se conecta al ICAM real).

El simulador reproduce la estructura de ICAM: formulario frmHeaderSearch con
#idBarcodeSearchInput, POST /maintenix/servlet/ScanBarcode, página del DIP con #idBarcode,
enlaces idTab<Pestaña>_link y contenido en #idTab<Pestaña>. Cada página trae scripts,
un onload que intenta enviar datos y una imagen.
"""

import http.server
import json
import socket
import threading
import time
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("playwright")

from dips_audit.extractor_icam import (  # noqa: E402
    ErrorExtraccion, ErrorSesion, extraer, leer_registro)
from dips_audit.icam import PESTANAS, leer_ficha  # noqa: E402

TEXTOS = {
    "TaskExecution": "Description\n{barcode} CREW O2 850 PSI IAW AMM TASK 12-15-21-210-801 REV 85, "
                     "15-MAY-2026\nLabor",
    "FaultInformation": "Fault Status:\tDEFER (Defer)\tFault Severity:\tDIP (Defer Item Project)\n"
                        "Deferral Reference:\t35-DIP\tEvaluated:\t-\n"
                        "Follow-on Tasks\n"
                        "Name\tID\tTask Class\tTask Subclass\tTask Status1\tDue2\n"
                        "RIR - PARK BRAKE HOLD CHECK\t{barcode}A\tADHOC (Ad-Hoc Task)\t-\tACTV\t"
                        "19-AUG-2026 23:59 UTC\n"
                        "RIR - PARK BRAKE HOLD CHECK\t{barcode}B\tADHOC (Ad-Hoc Task)\t-\tFORECAST\t"
                        "20-AUG-2026 23:59 UTC{historico}\n"
                        "Component Faults",
    "TaskInformation": "Parent Assembly:\tBoeing 737-8V3 - HP-1837CMP\tConfig Slot:\t35\n"
                       "Technical References\nDocument Reference:\tTASK 12-15-21-210-801\n"
                       "Attachments\n-\tName\tAttachment\tType\n-\tfoto.jpg\t-\t-\nZones",
    "Scheduling": "-\tDriver1\tParameter2\tUnit\tScheduled From\tStart\tInterval\tDeadline\n"
                  "-\t-\tCDY\tDAY\tCUSTOM\t18-AUG-2026 23:59 UTC\t3\t21-AUG-2026 23:59 UTC",
    "History": "18-AUG-2026 09:05 UTC\tX\tACTV\t-\tDeferral Notes: TASK 12-15-21-210-801",
}
ESCANEO = "/maintenix/servlet/ScanBarcode"
# Fila que solo aparece en "Show Historical Tasks": un RIR ya cerrado.
HISTORICO = ("\nRIR - PARK BRAKE HOLD CHECK\t{barcode}0\tADHOC (Ad-Hoc Task)\t-\tCOMPLETE\t"
             "18-AUG-2026 23:59 UTC")
# Página de un RIR (tarea ADHOC): Scheduling y Task Information.
TEXTOS_RIR = {
    "TaskExecution": "Instructions",
    "Scheduling": "-\tDriver1\tParameter2\tUnit\tScheduled From\tStart\tInterval\tDeadline\n"
                  "-\t-\tCDY\tDAY\tCUSTOM\t18-AUG-2026 23:59 UTC\t1\t19-AUG-2026 23:59 UTC",
    "TaskInformation": "Parent Assembly:\tBoeing 737-8V3 - HP-1837CMP\tConfig Slot:\t32",
}


def _html_pestana(texto: str) -> str:
    """Líneas con tab -> filas de tabla (como en ICAM); el resto -> div."""
    partes, filas = [], []
    for linea in texto.split("\n"):
        if "\t" in linea:
            filas.append("<tr>" + "".join(f"<td>{c}</td>" for c in linea.split("\t")) + "</tr>")
            continue
        if filas:
            partes.append("<table>" + "".join(filas) + "</table>")
            filas = []
        partes.append(f"<div>{linea}</div>")
    if filas:
        partes.append("<table>" + "".join(filas) + "</table>")
    return "".join(partes)


CABECERA = (f"<form name='frmHeaderSearch' method='POST' action='{ESCANEO}'>"
            "<input id='idBarcodeSearchInput' name='aBarcodeScan'></form>")


class _ICAMSimulado(http.server.BaseHTTPRequestHandler):
    envios: list[str] = []
    fallar_una_vez: set[str] = set()   # "barcode/pestaña" que responde 500 la primera vez
    sin_sesion = False
    login_con_error = False   # la página de inicio de sesión muestra un error (clave errada)

    def log_message(self, *args):
        pass

    def _responder(self, codigo: int, html: str = "", destino: str = "") -> None:
        self.send_response(codigo)
        if destino:
            self.send_header("Location", destino)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _al_login(self) -> bool:
        if self.sin_sesion and not self.path.startswith("/login"):
            self._responder(302, destino=f"http://localhost:{self.server.server_port}/login")
            return True
        return False

    def do_GET(self):
        if self._al_login():
            return
        url = urlparse(self.path)
        if url.path == "/login" and _ICAMSimulado.login_con_error:
            self._responder(200, "<title>Login</title><input name='usuario'>"
                                 "<span id='input-error'>Invalid username or password.</span>")
        elif url.path == "/login":
            # Se recarga hacia ICAM cada segundo: simula al usuario que completa el login.
            inicio = f"http://127.0.0.1:{self.server.server_port}/maintenix/common/ToDoList.jsp"
            self._responder(200, f"<meta http-equiv='refresh' content='1;url={inicio}'>"
                                 "<title>Login</title><input name='usuario'>")
        elif url.path.endswith("TaskDetails.jsp"):
            q = parse_qs(url.query)
            barcode = q["aTask"][0]
            pestana = q["aTab"][0].replace("idTab", "")
            es_rir = barcode.endswith(("A", "B"))
            historico = "aShowHistorical" in q
            if f"{barcode}/{pestana}" in _ICAMSimulado.fallar_una_vez:
                _ICAMSimulado.fallar_una_vez.discard(f"{barcode}/{pestana}")
                self._responder(500, "error")
                return
            enlaces = "".join(f"<a id='{p}_link' href='{url.path}?aTask={barcode}&aTab={p}'>{n}</a>"
                              for n, p in PESTANAS.items())
            if es_rir:
                contenido = _html_pestana(TEXTOS_RIR.get(pestana, "-"))
            else:
                contenido = _html_pestana(TEXTOS[pestana].format(
                    barcode=barcode, historico=HISTORICO.format(barcode=barcode) if historico else ""))
                if pestana == "FaultInformation":
                    contenido += (f"<a href='{url.path}?aTask={barcode}&aTab=idTabFaultInformation"
                                  "&aShowHistorical=true'>Show Historical Tasks</a>")
            self._responder(200, (
                f"<html><head><title>Fault Details - CREW OXYGEN [{barcode}]</title>"
                "<script>fetch('/guardar', {method: 'POST', body: 'x'})</script></head>"
                "<body onload=\"fetch('/guardar-onload', {method: 'POST'})\">"
                f"{CABECERA}<img src='/logo.png'><div id='idBarcode'>{barcode}</div>{enlaces}"
                f"<div id='idTab{pestana}'>{contenido}</div></body></html>"))
        elif url.path == "/logo.png":
            _ICAMSimulado.envios.append("imagen")
            self._responder(404)
        else:  # página de inicio de ICAM (ToDoList)
            self._responder(200, f"<title>To Do List</title>{CABECERA}")

    def do_POST(self):
        if self._al_login():
            return
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(largo).decode()
        _ICAMSimulado.envios.append(self.path)
        if self.path == ESCANEO:
            barcode = parse_qs(cuerpo)["aBarcodeScan"][0]
            self._responder(302, destino=f"/maintenix/web/task/TaskDetails.jsp?aTask={barcode}"
                                         "&aTab=idTabTaskExecution")
        else:
            self._responder(200)


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def icam(tmp_path):
    _ICAMSimulado.envios, _ICAMSimulado.fallar_una_vez = [], set()
    _ICAMSimulado.sin_sesion = _ICAMSimulado.login_con_error = False
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ICAMSimulado)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    config = {"url": f"http://127.0.0.1:{servidor.server_address[1]}/maintenix/common/ToDoList.jsp",
              "perfil": tmp_path / "perfil", "puerto": _puerto_libre(), "oculto": True,
              "cerrar_al_terminar": True, "paralelo": 3, "intentos": 3, "espera_segundos": 15}
    yield config
    servidor.shutdown()


def _extraer(barcodes, config, carpeta):
    try:
        return extraer(barcodes, config, carpeta)
    except ErrorSesion:
        raise
    except Exception as e:
        if "Edge" in str(e):
            pytest.skip(f"No se pudo abrir Edge: {e}")
        raise


def test_lee_por_barcode_rapido_y_solo_lectura(icam, tmp_path):
    barcodes = [f"T40S009T{n:03d}" for n in range(12)]
    _ICAMSimulado.fallar_una_vez = {"T40S009T003/Scheduling"}
    inicio = time.monotonic()
    estado = _extraer(barcodes, icam, tmp_path / "icam.json")
    segundos = time.monotonic() - inicio
    assert estado == {b: "leido" for b in barcodes}
    # Solo llegaron búsquedas (DIP y RIR vigente): sin scripts de ICAM, sin onload y sin imágenes.
    assert _ICAMSimulado.envios == [ESCANEO] * (2 * len(barcodes))
    assert segundos < 30, f"12 DIPs con RIR en {segundos:.1f} s"

    # Todos los DIPs quedan juntos en un solo JSON.
    datos = json.loads((tmp_path / "icam.json").read_text(encoding="utf-8"))
    assert [r["barcode"] for r in datos["records"]] == barcodes
    registro = leer_registro(tmp_path / "icam.json", "T40S009T003")
    ficha = leer_ficha(registro["sections"], registro["barcode"])
    assert ficha.descripcion.startswith("T40S009T003 CREW O2 850 PSI")
    assert ficha.referencias_tecnicas == ["TASK 12-15-21-210-801"]
    assert ficha.adjuntos == ["foto.jpg"]
    assert [(i.valor, i.parametro) for i in ficha.intervalos] == [(3.0, "CDY")]
    assert ficha.deferral_reference == "35-DIP"
    assert ficha.notas_diferimiento == "TASK 12-15-21-210-801"
    # RIR: vigente, siguiente y el cerrado de Show Historical Tasks; página del RIR vigente.
    assert [(t.id, t.estado) for t in ficha.tareas_siguientes] == [
        ("T40S009T003A", "ACTV"), ("T40S009T003B", "FORECAST"), ("T40S009T0030", "COMPLETE")]
    rir = leer_ficha(registro["rir"]["T40S009T003A"]["sections"])
    assert [(i.valor, i.parametro, i.inicio) for i in rir.intervalos] == [
        (1.0, "CDY", "18-AUG-2026 23:59 UTC")]
    assert rir.parent_assembly == "Boeing 737-8V3 - HP-1837CMP"
    assert "rir_errores" not in registro

    # Segunda corrida: aunque ya estén leídos, se vuelven a leer todos.
    _ICAMSimulado.envios.clear()
    assert _extraer(barcodes, icam, tmp_path / "icam.json") == {b: "leido" for b in barcodes}
    assert _ICAMSimulado.envios == [ESCANEO] * (2 * len(barcodes))


def test_sin_sesion_avisa_y_no_se_queda_en_el_login(icam, tmp_path):
    _ICAMSimulado.sin_sesion = True
    with pytest.raises(ErrorSesion, match="No hay sesión iniciada en ICAM"):
        _extraer(["T40S009T000"], icam, tmp_path / "icam.json")
    assert not (tmp_path / "icam.json").exists()


def test_sin_sesion_espera_a_que_el_usuario_la_inicie(icam, tmp_path):
    _ICAMSimulado.sin_sesion = True
    icam["espera_sesion_minutos"] = 1
    avisos = []
    threading.Timer(6, lambda: setattr(_ICAMSimulado, "sin_sesion", False)).start()
    try:
        estado = extraer(["T40S009T000"], icam, tmp_path / "icam.json", al_avanzar=avisos.append)
    except ErrorExtraccion as e:
        if "Edge" in str(e):
            pytest.skip(f"No se pudo abrir Edge: {e}")
        raise
    assert estado == {"T40S009T000": "leido"}
    assert any("Inicie sesión" in a for a in avisos)
    assert "Sesión de ICAM iniciada." in avisos


def test_error_al_iniciar_sesion_se_detecta_de_inmediato(icam, tmp_path):
    _ICAMSimulado.sin_sesion = _ICAMSimulado.login_con_error = True
    icam["espera_sesion_minutos"] = 1
    inicio = time.monotonic()
    with pytest.raises(ErrorSesion, match="No se pudo iniciar sesión en ICAM: Invalid username"):
        _extraer(["T40S009T000"], icam, tmp_path / "icam.json")
    assert time.monotonic() - inicio < 20
    assert not (tmp_path / "icam.json").exists()

