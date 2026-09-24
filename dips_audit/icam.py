"""Lectura del texto de las pestañas de un DIP en ICAM (Maintenix).

Recibe el texto visible de cada pestaña (Task Execution, Fault Information, Task
Information, Scheduling, History) tal como lo copia el extractor, y devuelve los datos
que usa la auditoría. No depende de cómo se obtuvo el texto.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

PESTANAS = {  # nombre en el JSON -> valor del parámetro aTab de la URL de ICAM
    "TaskExecution": "idTabTaskExecution",
    "FaultInformation": "idTabFaultInformation",
    "TaskInformation": "idTabTaskInformation",
    "Scheduling": "idTabScheduling",
    "History": "idTabHistory",
}
# Encabezados de bloque dentro de Task Execution, en el orden en que aparecen.
_BLOQUES_EJECUCION = ["Description", "Steps", "Labor", "Corrective Action", "Part Requirements",
                      "Measurements", "Tool Requirements"]


@dataclass
class Intervalo:
    parametro: str          # CDY, HOURS, CYCLES
    unidad: str             # DAY, HOUR, CYCLE
    inicio: str
    valor: float | None
    deadline: str
    extension: str
    deadline_extendido: str
    restante: str


@dataclass
class FichaICAM:
    barcode: str = ""
    titulo: str = ""
    descripcion: str = ""
    notas_diferimiento: str = ""     # "Deferral Notes" del historial (parte de la apertura)
    accion_correctiva: str = ""      # cierre: no se usa en la auditoría de apertura
    referencias_tecnicas: list[str] = field(default_factory=list)
    marcas_auditoria: list[str] = field(default_factory=list)   # tipo AUDITDIP
    adjuntos: list[str] = field(default_factory=list)
    intervalos: list[Intervalo] = field(default_factory=list)
    cambios_deadline: list[str] = field(default_factory=list)
    sn_removidos: list[tuple[str, str]] = field(default_factory=list)   # (P/N, S/N)
    sn_instalados: list[tuple[str, str]] = field(default_factory=list)
    fault_status: str = ""
    severidad: str = ""
    deferral_class: str = ""
    deferral_reference: str = ""
    found_on: str = ""
    parent_assembly: str = ""
    estado_tarea: str = ""
    fin_real: str = ""

    def como_dict(self) -> dict:
        return asdict(self)


def _limpio(texto: str) -> str:
    return texto.replace("\xa0", " ").strip()


def _pares(texto: str) -> dict[str, str]:
    """Campos 'Nombre:<TAB>valor' (puede haber varios por línea)."""
    salida: dict[str, str] = {}
    for linea in texto.splitlines():
        partes = linea.split("\t")
        for i, p in enumerate(partes[:-1]):
            clave = _limpio(p)
            if clave.endswith(":") and clave[:-1] not in salida:
                salida[clave[:-1]] = _limpio(partes[i + 1])
    return salida


def _bloque(texto: str, inicio: str, siguientes: list[str]) -> str:
    """Texto entre una línea que empieza con `inicio` y la primera de `siguientes`."""
    lineas = texto.splitlines()
    desde = next((i for i, l in enumerate(lineas) if _limpio(l).startswith(inicio)), None)
    if desde is None:
        return ""
    hasta = next((i for i in range(desde + 1, len(lineas))
                  if any(_limpio(lineas[i]).startswith(s) for s in siguientes)), len(lineas))
    return "\n".join(lineas[desde + 1:hasta])


def _tabla(texto: str, columnas: list[str]) -> tuple[list[str], list[list[str]]]:
    """Encabezado y filas de la primera tabla (separada por tabs) que tiene esas columnas."""
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        celdas = [_limpio(c) for c in linea.split("\t")]
        if all(c in celdas for c in columnas):
            filas = []
            for l in lineas[i + 1:]:
                if "\t" not in l or not _limpio(l):
                    break
                filas.append([_limpio(c) for c in l.split("\t")])
            return celdas, filas
    return [], []


def _celda(fila: list[str], i: int | None) -> str:
    return fila[i] if i is not None and i < len(fila) else ""


def _numero(texto: str) -> float | None:
    try:
        return float(texto.replace(",", ""))
    except ValueError:
        return None


def leer_ficha(secciones: dict, barcode: str = "", titulo: str = "") -> FichaICAM:
    """`secciones`: {pestaña: texto} o {pestaña: {"text": texto}} (formato del extractor)."""
    def texto(nombre: str) -> str:
        s = secciones.get(nombre) or ""
        return s.get("text", "") if isinstance(s, dict) else str(s)

    f = FichaICAM(barcode=barcode, titulo=titulo)
    ejecucion = texto("TaskExecution")
    f.descripcion = _limpio(_bloque(ejecucion, "Description", _BLOQUES_EJECUCION[1:]))
    f.accion_correctiva = _limpio(_bloque(ejecucion, "Corrective Action",
                                          ["Part Requirements", "Measurements", "Tool Requirements"]))
    enc, filas = _tabla(ejecucion, ["Part No", "Serial No / Batch No"])
    if enc:
        pn = [i for i, c in enumerate(enc) if c == "Part No"]
        sn = [i for i, c in enumerate(enc) if c == "Serial No / Batch No"]
        for fila in filas:
            if len(pn) > 0 and _celda(fila, sn[0]):
                f.sn_removidos.append((_celda(fila, pn[0]), _celda(fila, sn[0])))
            if len(pn) > 1 and len(sn) > 1 and _celda(fila, sn[1]):
                f.sn_instalados.append((_celda(fila, pn[1]), _celda(fila, sn[1])))

    falla = texto("FaultInformation")
    campos = _pares(falla)
    f.fault_status = campos.get("Fault Status", "")
    f.severidad = campos.get("Fault Severity", "")
    f.found_on = campos.get("Found on Date", "")
    f.deferral_class = campos.get("Deferral Class", "")
    f.deferral_reference = campos.get("Deferral Reference", "")
    seleccionada = campos.get("Reference", "")

    tarea = texto("TaskInformation")
    campos = _pares(tarea)
    f.parent_assembly = campos.get("Parent Assembly", "")
    f.estado_tarea = campos.get("Status", "")
    f.fin_real = campos.get("Actual End Date", "")
    refs = _bloque(tarea, "Technical References", ["Attachments"])
    documentos = [v for k, v in _pares(refs).items() if k.startswith("Document Reference") and v]
    documentos += [_limpio(m) for m in re.findall(r"Document Reference:\t([^\t\n]+)", refs)]
    enc, filas = _tabla(refs, ["Name", "Type"])
    for fila in filas:
        nombre, tipo = _celda(fila, enc.index("Name")), _celda(fila, enc.index("Type"))
        if not nombre:
            continue
        (f.marcas_auditoria if tipo.upper() == "AUDITDIP" else documentos).append(nombre)
    if seleccionada:
        documentos.append(seleccionada)
    f.referencias_tecnicas = list(dict.fromkeys(d for d in documentos if d))
    enc, filas = _tabla(_bloque(tarea, "Attachments", ["Zones", "Panels", "Labor Summary"]),
                        ["Name", "Type"])
    f.adjuntos = [_celda(fila, enc.index("Name")) for fila in filas
                  if _celda(fila, enc.index("Name"))]

    # En límites por uso (FH, FC), Start/Deadline traen "Aircraft: n", "Assembly: n" y
    # "Component: n" en líneas aparte: se unen en una celda para que la fila quede en una línea.
    agenda = re.sub(r"(?:\n?(?:Aircraft|Assembly|Component):[ \t\xa0]*[^\n\t]*)+\n?",
                    lambda m: " / ".join(re.sub(r"[:\t\xa0 ]+", " ", x).strip()
                                         for x in m.group(0).split("\n") if _limpio(x)),
                    texto("Scheduling"))
    enc, filas = _tabla(agenda, ["Parameter2", "Interval", "Deadline"])
    if enc:
        i = {c: enc.index(c) for c in enc if c}
        for fila in filas:
            f.intervalos.append(Intervalo(
                parametro=_celda(fila, i.get("Parameter2")), unidad=_celda(fila, i.get("Unit")),
                inicio=_celda(fila, i.get("Start")),
                valor=_numero(_celda(fila, i.get("Interval"))),
                deadline=_celda(fila, i.get("Deadline")),
                extension=_celda(fila, i.get("Extension")),
                deadline_extendido=_celda(fila, i.get("Extended Deadline")),
                restante=_celda(fila, i.get("Usage Remaining"))))

    historial = texto("History") + "\n\n" + falla
    f.cambios_deadline = list(dict.fromkeys(
        _limpio(l) for l in historial.splitlines()
        if re.search(r"deadline (has been|was) (modified|added|removed|extended)", l, re.I)))
    notas = re.findall(r"Deferral Notes:\s*(.+?)(?:\t|\n\n|$)", historial, re.S)
    f.notas_diferimiento = " | ".join(dict.fromkeys(_limpio(n) for n in notas if _limpio(n)))
    return f
