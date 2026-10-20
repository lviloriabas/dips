from datetime import datetime

from dips_audit.comparacion import comparar
from tests.conftest import crear_export

ENCABEZADO = [
    "Fault Barcode", "Area", "ATA", "Fault Name", "Fault Severity", "Fault Status",
    "Found On Date", "Fault Due Date", "Complete Dt", "Dip Interval", "Interval Type",
    "Aircraft", "Task Parent Assy", "DIP Open - RT Audit Completed", "DIP Open Audit User",
    "DIP Discrepancy Found", "DIP Closed - RT Audit Completed", "DIP Closed Audit User",
]
PARENT = "Boeing 737-9 MAX9 - HP-9901CMP"


def _fila(barcode, estado, due, completo, apertura, cierre, discrepancia=" ", tipo="Others"):
    return [barcode, tipo, 35, "CREW OXYGEN BOTTLE 950 PSI", "DIP", estado,
            datetime(2026, 8, 18, 10, 0), due, completo, 3, "CDY", "HP-9901CMP", PARENT,
            apertura, "AUDITOR1" if apertura else " ", discrepancia,
            cierre, "AUDITOR2" if cierre else " "]


def test_compara_apertura_y_cierre_a_la_hora_de_cada_auditoria(tmp_path, auditor_others):
    due = datetime(2026, 8, 21, 23, 59)
    filas = [
        # Auditado al abrir, antes del due: OK para ambos.
        _fila("A1", "ACTV", due, None, datetime(2026, 8, 18, 12, 0), None),
        # Cerrado un día tarde: el programa lo marca en el cierre; el auditor no.
        _fila("C1", "COMPLETE", due, datetime(2026, 8, 23, 10, 0),
              datetime(2026, 8, 18, 12, 0), datetime(2026, 8, 23, 15, 0)),
        # Con discrepancia manual.
        _fila("C2", "COMPLETE", due, datetime(2026, 8, 20, 10, 0),
              None, datetime(2026, 8, 20, 15, 0), discrepancia="Y"),
        # Sin auditoría manual y fuera de alcance: no se comparan.
        _fila("S1", "ACTV", due, None, None, None),
        _fila("P1", "ACTV", due, None, datetime(2026, 8, 18, 12, 0), None, tipo="Powerplant"),
    ]
    c = comparar(auditor_others, crear_export(tmp_path / "e.xlsx", filas, encabezado=ENCABEZADO))
    t = c.detalle.set_index("Fault Barcode")
    assert list(t.index) == ["A1", "C1", "C2"]
    assert t.loc["A1", "Apertura: resultado del programa"] == "OK"
    assert t.loc["A1", "Cierre: resultado del programa"] == ""
    assert t.loc["A1", "¿Coinciden?"] == "Sí: ambos OK"
    assert t.loc["C1", "Cierre: resultado del programa"] == "Posible discrepancia"
    assert t.loc["C1", "¿Coinciden?"].startswith("No: el programa marca")
    assert t.loc["C2", "Apertura: resultado del programa"] == ""
    assert t.loc["C2", "DIP Discrepancy Found"] == "Y"
    resumen = {titulo: df for titulo, _, df in c.tablas}
    datos = resumen["Qué se comparó"].set_index("Dato")["Cantidad"]
    assert datos["Auditorías de apertura"] == 2 and datos["Auditorías de cierre"] == 2
    sin_disc = resumen["DIPs que el auditor dio sin discrepancia (2)"].set_index("Resultado del programa")
    assert sin_disc.loc["OK", "DIPs"] == 1 and sin_disc.loc["Posible discrepancia", "DIPs"] == 1
    motivos = resumen["Por qué el programa marca DIPs que el auditor dio sin discrepancia: cierre"]
    assert "Cerrado después del due date" in set(motivos["Motivo"])


def test_exporta_excel(tmp_path, auditor):
    from dips_audit.comparacion import exportar

    due = datetime(2026, 8, 21, 23, 59)
    ruta = crear_export(tmp_path / "e.xlsx", [_fila("A1", "ACTV", due, None, datetime(2026, 8, 18, 12, 0), None)],
                        encabezado=ENCABEZADO)
    salida = exportar(comparar(auditor, ruta), tmp_path / "salida")
    assert salida.exists()


def test_duplicado_cerrado_conserva_motivo_en_comparacion(tmp_path, auditor_others):
    due = datetime(2026, 8, 21, 23, 59)
    filas = [_fila(b, "COMPLETE", due, datetime(2026, 8, 19), None,
                   datetime(2026, 8, 20)) for b in ("A1", "B1")]
    c = comparar(auditor_others, crear_export(tmp_path / "e.xlsx", filas, encabezado=ENCABEZADO))
    detalle = c.detalle.set_index("Fault Barcode").loc["B1"]
    assert detalle["Cierre: resultado del programa"] == "Posible discrepancia"
    hallazgos = c.hallazgos[c.hallazgos["Fault Barcode"] == "B1"]
    assert "duplicado" in set(hallazgos.loc[hallazgos["Auditoría"] == "CIERRE", "Código"])
    assert "Posible duplicado de A1." in detalle["Cierre: motivos"]


def test_sin_fuente_en_dips_references_se_cuenta_en_apertura_y_cierre(tmp_path, auditor):
    due = datetime(2026, 8, 21, 23, 59)
    apertura = _fila("S1", "ACTV", due, None, datetime(2026, 8, 18, 12), None)
    cierre = _fila("S2", "COMPLETE", due, datetime(2026, 8, 20), None,
                   datetime(2026, 8, 20, 12))
    apertura[3] = cierre[3] = "DEFIBRILLATOR DUE DATE"
    entrada = crear_export(tmp_path / "entrada.xlsx", [apertura, cierre], encabezado=ENCABEZADO)
    comparacion = comparar(auditor, entrada)
    etiqueta = "SIN FUENTE EN DIPS REFERENCES"
    detalle = comparacion.detalle.set_index("Fault Barcode")
    assert detalle.loc["S1", "Apertura: resultado del programa"] == etiqueta
    assert detalle.loc["S2", "Cierre: resultado del programa"] == etiqueta
    assert (detalle["Programa: resultado"] == etiqueta).all()
    assert detalle["¿Coinciden?"].str.startswith(etiqueta).all()
    tabla = next(df for titulo, _, df in comparacion.tablas
                 if titulo == "¿El programa llega al mismo resultado que el auditor?")
    assert tabla.set_index("Respuesta").loc[etiqueta, "DIPs"] == 2


def test_modo_prueba_separa_icam_y_salida_y_marca_los_resultados(tmp_path, config, monkeypatch):
    """Un Excel dentro de la carpeta de pruebas usa pruebas/icam.json y pruebas/salida, y el
    resultado lleva el prefijo PRUEBA_ y el aviso en el Excel."""
    import copy

    import openpyxl

    from dips_audit import __main__ as cli

    config = copy.deepcopy(config)
    config["carpeta_pruebas"] = tmp_path / "pruebas"
    monkeypatch.setattr(cli, "cargar_configuracion", lambda _=None: config)
    entrada = tmp_path / "pruebas" / "entrada"
    entrada.mkdir(parents=True)
    due = datetime(2026, 8, 21, 23, 59)
    ruta = crear_export(entrada / "DIPs Audit (TEST).xlsx",
                        [_fila("A1", "ACTV", due, None, datetime(2026, 8, 18, 12, 0), None)],
                        encabezado=ENCABEZADO)
    assert cli.main(["comparar", str(ruta)]) == 0
    assert config["icam"]["archivo"] == (tmp_path / "pruebas" / "icam.json").resolve()
    salida = list((tmp_path / "pruebas" / "salida").glob("PRUEBA_*_COMPARACION_*.xlsx"))
    assert len(salida) == 1
    assert "PRUEBA" in openpyxl.load_workbook(salida[0])["Resumen"]["A3"].value

    assert cli.main(["auditar", str(ruta)]) == 0
    assert list((tmp_path / "pruebas" / "salida").glob("PRUEBA_*_AUDITORIA_*.xlsx"))


def test_fuera_de_pruebas_no_es_modo_prueba(tmp_path, config):
    import copy

    from dips_audit.__main__ import _modo_prueba

    config = copy.deepcopy(config)
    config["carpeta_pruebas"] = tmp_path / "pruebas"
    args = type("Args", (), {"archivo": str(tmp_path / "real.xlsx"), "prueba": False})()
    assert not _modo_prueba(args, config) and "modo_prueba" not in config
    args.prueba = True
    assert _modo_prueba(args, config) and config["modo_prueba"]
