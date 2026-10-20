"""Serial de motor obligatorio y distinto para cada posición."""

import pytest

from dips_audit.cargador import cargar_export, completar_con_icam
from dips_audit.reglas import auditar_dip
from tests.conftest import ENCABEZADO_ENTRADA, crear_export, hacer_dip
from tests.test_cargador import FILA


MOTOR_1 = "(LH) ENGINE EQUIPED (PN: LEAP-1B28, SN: 60B611)"
MOTOR_2 = "(RH) ENGINE EQUIPED (PN: LEAP-1B28, SN: 60B552)"
CODIGOS = {"sin_sn_motor_en_descripcion", "sn_motor_incorrecto"}


def revisar(ctx, **cambios):
    base = dict(nombre="DIP - ENGINE #1 CHECK", descripcion="",
                parent_assy=MOTOR_1, parent_tipo="ENGINE")
    base.update(cambios)
    return auditar_dip(hacer_dip(**base), None, ctx)


@pytest.mark.parametrize("nombre", ["engine #1 filter", "DIP - ENGINE No. 2 CHECK",
                                  "ENGINE/APU SQUIB", "DIP ENGINE S/N 60B611"])
def test_engine_sin_sn_en_descripcion_es_discrepancia(ctx, nombre):
    r = revisar(ctx, nombre=nombre, descripcion="INSPECTION REQUIRED")
    assert any(h.codigo == "sin_sn_motor_en_descripcion" and
               h.severidad == "POSIBLE DISCREPANCIA" for h in r.hallazgos)


@pytest.mark.parametrize("descripcion,incorrecto", [
    ("ENGINE #1 S/N 60B611", False),
    ("Engine No. 1 SN: 60B-611", False),
    ("S/N 60B611", False),
    ("ENGINE #1 S/N 60B552", True),
    ("ENGINE #1 S/N 60C611", True),  # mismos dígitos, otro motor
    ("ENGINE #1 FILTER S/N FILTER123", True),
    ("ENGINE #1 S/N 60B611. FILTER S/N FILTER123", False),
    ("ENGINE #1 S/N 60B552; ENGINE #2 S/N 60B611", True),
    ("ENGINE #1 S/N 60B611; ENGINE #2 S/N 60B552", False),
    ("ENGINE #2 S/N 60B611", True),
])
def test_compara_serial_completo_y_posicion(ctx, descripcion, incorrecto):
    r = revisar(ctx, descripcion=descripcion)
    h = [h for h in r.hallazgos if h.codigo == "sn_motor_incorrecto"]
    assert bool(h) == incorrecto
    assert all(h.severidad == "POSIBLE DISCREPANCIA" for h in h)


def test_motor_2_tiene_su_propio_serial(ctx):
    r = revisar(ctx, nombre="DIP - ENGINE #2 CHECK", parent_assy=MOTOR_2,
                descripcion="ENGINE #2 SN 60B552")
    assert not CODIGOS & {h.codigo for h in r.hallazgos}
    r = revisar(ctx, nombre="DIP - ENGINE #2 CHECK", parent_assy=MOTOR_2,
                descripcion="ENGINE #2 SN 60B611")
    assert "sn_motor_incorrecto" in {h.codigo for h in r.hallazgos}


def test_titulo_motor_1_con_parent_motor_2_no_se_valida(ctx):
    r = revisar(ctx, parent_assy=MOTOR_2, descripcion="ENGINE #1 SN 60B552")
    assert "sn_motor_incorrecto" in {h.codigo for h in r.hallazgos}


def test_parent_del_avion_se_completa_con_motor_de_icam(ctx):
    r = revisar(ctx, parent_assy="Boeing HP-1853CMP", parent_tipo="AIRCRAFT",
                parent_icam=MOTOR_1, descripcion="ENGINE #1 SN 60B552")
    assert "sn_motor_incorrecto" in {h.codigo for h in r.hallazgos}


def test_sin_identidad_del_motor_pide_verificar(ctx):
    r = revisar(ctx, parent_assy="Boeing HP-1853CMP", parent_tipo="AIRCRAFT",
                descripcion="S/N 60B611")
    assert not CODIGOS & {h.codigo for h in r.hallazgos}
    assert any("sin S/N de motor en Parent Assembly" in m for m in r.manuales)


def test_sin_engine_en_titulo_no_aplica(ctx):
    r = revisar(ctx, nombre="ENGINEERING CHECK", descripcion="CHECK ENGINE #1")
    assert not CODIGOS & {h.codigo for h in r.hallazgos}


def test_no_confunde_descripcion_no_leida_con_vacia(ctx, tmp_path):
    lote = cargar_export(crear_export(tmp_path / "export.xlsx", [
        [*FILA[:3], "DIP ENGINE #1 CHECK", *FILA[4:]]]))
    r = auditar_dip(lote.datos.iloc[0].to_dict(), None, ctx)
    assert not CODIGOS & {h.codigo for h in r.hallazgos}
    assert any("el Excel no trae esa columna" in m for m in r.manuales)

    # ICAM sí aporta la descripción, aunque esté vacía: ahora la ausencia es real.
    icam = tmp_path / "icam.csv"
    icam.write_text(f"barcode,description\n{FILA[0]},\n", encoding="utf-8")
    completar_con_icam(lote, icam)
    r = auditar_dip(lote.datos.iloc[0].to_dict(), None, ctx)
    assert "sin_sn_motor_en_descripcion" in {h.codigo for h in r.hallazgos}


def test_columna_descripcion_vacia_exige_serial(ctx, tmp_path):
    lote = cargar_export(crear_export(tmp_path / "export.xlsx", [
        [*FILA[:3], "DIP ENGINE #1 CHECK", *FILA[4:], ""]],
        encabezado=[*ENCABEZADO_ENTRADA, "Fault Description"]))
    r = auditar_dip(lote.datos.iloc[0].to_dict(), None, ctx)
    assert "sin_sn_motor_en_descripcion" in {h.codigo for h in r.hallazgos}
