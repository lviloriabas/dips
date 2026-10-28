from __future__ import annotations

import os
import shutil
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pytest

from dips_audit.auditor import Auditor, cargar_configuracion
from dips_audit.reglas import Contexto

RAIZ = Path(__file__).resolve().parent.parent
HISTORICO = RAIZ / "02 - HISTORY - DIPs AUDIT (From 09Jul 15_45).xlsx"
# La carpeta temporal del sistema puede estar restringida en equipos corporativos: se usa
# una dentro del proyecto. Cada corrida tiene la suya, para que dos corridas a la vez no se
# borren los archivos entre sí.
TEMPORALES = RAIZ / ".pytest_tmp"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    if not config.option.basetemp:
        # Pytest crea la subcarpeta de la corrida, pero requiere que exista su padre.
        # .pytest_tmp no se versiona y falta en una instalacion nueva.
        TEMPORALES.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(TEMPORALES / str(os.getpid()))
        config._temporal_propia = True


def pytest_unconfigure(config):
    if getattr(config, "_temporal_propia", False):
        shutil.rmtree(config.option.basetemp, ignore_errors=True)


@pytest.fixture(scope="session")
def config():
    configuracion = cargar_configuracion()
    configuracion["referencias_sharepoint"] = ""  # las pruebas no consultan servicios corporativos
    return configuracion


@pytest.fixture(autouse=True)
def cli_sin_sharepoint_real(monkeypatch):
    from dips_audit import __main__ as cli

    cargar = cli.cargar_configuracion
    def sin_red(ruta=None):
        configuracion = cargar(ruta)
        configuracion["referencias_sharepoint"] = ""
        return configuracion
    monkeypatch.setattr(cli, "cargar_configuracion", sin_red)


@pytest.fixture(scope="session")
def auditor(config):
    return Auditor(config, fecha_auditoria=date(2026, 8, 20))


@pytest.fixture(scope="session")
def auditor_others(config):
    """Auditor que audita solo los DIPs Others (los demás quedan FUERA DE ALCANCE)."""
    return Auditor({**config, "tipos_auditados": ["Others"]}, fecha_auditoria=date(2026, 8, 20))


@pytest.fixture(scope="session")
def catalogo(auditor):
    return auditor.catalogo


@pytest.fixture
def ctx(auditor):
    return Contexto(discrepancias=auditor.discrepancias, fecha_referencia=date(2026, 8, 20))


def hacer_dip(**cambios) -> dict:
    """DIP normalizado con valores por defecto razonables (un ACTV de 3 días)."""
    base = {
        "fila": 2, "barcode": "T40S0000001", "ata": 35, "tipo": "Others",
        "nombre": "CREW OXYGEN BOTTLE 950 PSI", "descripcion": "",
        "intervalo": 3.0, "tipo_intervalo_original": "DAY", "unidad": "DAY",
        "estado": "ACTV", "avion": "HP-9901CMP",
        "parent_assy": "Boeing 737-9 MAX9 - HP-9901CMP", "parent_tipo": "AIRCRAFT",
        "severidad": "DIP", "deferral_ref": "35-DIP",
        "found_date": datetime(2026, 8, 18, 10, 0), "due_date": datetime(2026, 8, 21, 23, 59),
        # Las pruebas generales de referencia/adjuntos corresponden a DIPs desde el corte.
        "defer_date": datetime(2026, 7, 9, 10, 0),
        "scheduled_date": None, "usage_remaining": 2.0, "complete_date": None,
        "correccion_fecha": "", "flota": "MAX",
    }
    base.update(cambios)
    return base


ENCABEZADO_ENTRADA = [
    "Fault Barcode", "ATA", "Area", "Fault Name", "DIP Interval", "Interval Type",
    "Fault Status", "Aircraft", "Task Parent Assy", "Fault Severity", "Deferral Reference",
    "Fault Due Date", "Fault Found on Date", "Scheduled Date", "Usage Remaining",
]


def crear_export(ruta: Path, filas: list[list], filas_antes: int = 0,
                 encabezado: list[str] | None = None) -> Path:
    """Crea un Excel de entrada de prueba."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Export"
    for _ in range(filas_antes):
        ws.append(["Reporte de DIPs"])
    ws.append(encabezado or ENCABEZADO_ENTRADA)
    for f in filas:
        ws.append(f)
    wb.save(ruta)
    return ruta
