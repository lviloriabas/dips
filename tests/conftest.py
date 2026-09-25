from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import openpyxl
import pytest

from dips_audit.auditor import Auditor, cargar_configuracion
from dips_audit.reglas import Contexto

RAIZ = Path(__file__).resolve().parent.parent
HISTORICO = RAIZ / "02 - HISTORY - DIPs AUDIT (From 09Jul 15_45).xlsx"


@pytest.fixture(scope="session")
def config():
    return cargar_configuracion()


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
