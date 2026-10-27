"""Auditoría de un DIP por barcode, solo con ICAM (sin Excel de entrada)."""

import json
from datetime import datetime

import pytest

from dips_audit.__main__ import main
from dips_audit.cargador import lote_desde_icam


def _registro(barcode="T40S000FDR1", nombre="FDR - REPORT", limites=None, estado="ACTV (Active)",
              parent="Boeing 737-8V3 - HP-1837CMP"):
    limites = limites or ["\t\tCDY\tDAY\tCUSTOM\t18-AUG-2026 23:59 UTC\t45\t02-OCT-2026 23:59 UTC\t0\t"
                          "02-OCT-2026 23:59 UTC\t43\t02-OCT-2026 23:59 UTC"]
    return {
        "barcode": barcode,
        "page_title": f"Fault Details - {nombre} [{barcode}]",
        "sections": {
            "TaskExecution": "Description \n\nFDR READOUT PENDING\n\nLabor\n",
            "FaultInformation": (
                "Fault Details \n\n"
                "Fault Status:\tDEFER (Defer)\tFault Severity:\tDIP (Defer Item Project)\n"
                "Found on Date:\t18-AUG-2026 09:00 UTC\tFailure Type:\t\n"
                "Deferral Class:\tDIP-MEL\tMOC Authorization:\t\n"
                "Deferral Reference:\t31-DIP\tEvaluated:\t\n\n"
                "Fault History\n\n\t\t\t\nDate\tRecorded By\tStatus\tStage Reason\tNote\n"
                "18-AUG-2026 09:05 UTC\tTECNICO\tDEFER\t \tCorrective action was deferred.\t\n"
                "18-AUG-2026 09:00 UTC\tTECNICO\tOPEN\t \tFault was created.\t\n"),
            "TaskInformation": (
                f"Task Information \n\nParent Assembly:\t{parent}\tConfig Slot:\t31\n"
                f"Status:\t{estado}\tSubtask Of:\tPAQUETE PTY [T40S000WP01]\n"
                "Scheduled Start Date:\t20-AUG-2026 20:00 UTC\tScheduled End Date:\t\n"),
            "Scheduling": ("\tDriver1\tParameter2\tUnit\tScheduled From\tStart\tInterval\tDeadline\t"
                           "Extension\tExtended Deadline\tUsage Remaining\tEstimated Date\n"
                           + "\n".join(limites) + "\n"),
            "History": "",
        },
    }


@pytest.mark.parametrize("estado, esperado", [
    ("ACTV (Active)", "ACTV"), ("IN WORK (In Work)", "IN WORK"), ("PAUSE (Paused)", "PAUSE"),
])
def test_dip_armado_desde_icam(tmp_path, estado, esperado):
    lote = lote_desde_icam(_registro(estado=estado), tmp_path / "icam.json")
    d = lote.datos.iloc[0]
    assert (d["barcode"], d["nombre"], d["ata"], d["estado"]) == ("T40S000FDR1", "FDR - REPORT", 31, esperado)
    assert (d["avion"], d["flota"], d["intervalo"], d["unidad"]) == ("HP-1837CMP", "NG-800", 45, "DAY")
    assert d["found_date"] == datetime(2026, 8, 18, 9, 0)
    assert d["defer_date"] == datetime(2026, 8, 18, 9, 5)
    assert d["due_date"] == datetime(2026, 10, 2, 23, 59)
    assert d["work_package"] == "T40S000WP01"
    assert d["descripcion"] == "FDR READOUT PENDING"
    assert d["adjuntos"] == []                       # se leyó ICAM: sin attachments


def test_due_date_del_limite_que_vence_primero(tmp_path):
    """Un límite por uso vence en su Estimated Date; manda el que vence primero."""
    ciclos = ("\t\tCYCLES\tCYCLES\tCUSTOM\tAircraft 100 / Component 100\t180\tAircraft 280 / "
              "Component 280\t0\tAircraft 280 / Component 280\t15\t29-SEP-2026 23:59 UTC")
    dias = ("\t\tCDY\tDAY\tCUSTOM\t18-AUG-2026 23:59 UTC\t45\t02-OCT-2026 23:59 UTC\t0\t"
            "02-OCT-2026 23:59 UTC\t43\t02-OCT-2026 23:59 UTC")
    d = lote_desde_icam(_registro(limites=[ciclos, dias]), tmp_path / "icam.json").datos.iloc[0]
    assert (d["intervalo"], d["unidad"]) == (180, "FC")
    assert d["due_date"] == datetime(2026, 9, 29, 23, 59)


def test_motor_sin_matricula_usa_el_modelo_para_la_flota(tmp_path):
    lote = lote_desde_icam(_registro(parent="(RH) ENGINE EQUIPED (MAX PART) (PN: LEAP-1B28, SN: 1)"),
                           tmp_path / "icam.json")
    assert (lote.datos.iloc[0]["avion"], lote.datos.iloc[0]["flota"]) == ("", "MAX")
    assert any("matrícula" in n for n in lote.notas)


def test_cli_barcode_solo_consola(tmp_path, capsys):
    archivo = tmp_path / "icam.json"
    archivo.write_text(json.dumps({"records": [_registro()]}), encoding="utf-8")
    codigo = main(["barcode", "t40s000fdr1", "--datos-icam", str(archivo), "--fecha", "2026-08-20"])
    assert codigo == 0
    salida = " ".join(capsys.readouterr().out.split())
    assert "DIP T40S000FDR1" in salida and "FDR - REPORT" in salida
    assert "Avión: HP-1837CMP (NG-800)" in salida
    assert "Resultado: POSIBLE DISCREPANCIA" in salida
    assert sorted(p.name for p in tmp_path.iterdir()) == ["icam.json"]   # no genera archivos


def test_cli_barcode_inexistente_o_invalido(tmp_path, capsys):
    archivo = tmp_path / "icam.json"
    archivo.write_text(json.dumps({"records": [_registro()]}), encoding="utf-8")
    assert main(["barcode", "T40S000XXXX", "--datos-icam", str(archivo)]) == 1
    assert "T40S000XXXX: no está en" in capsys.readouterr().out
    assert main(["barcode", "entrada.xlsx"]) == 1
    assert "entrada.xlsx no es un barcode" in capsys.readouterr().out


def test_no_cache_en_todos_los_comandos_que_leen_icam(monkeypatch, tmp_path):
    """Por defecto se usa lo leído hace menos de 60 min; --no-cache lee todo en ICAM."""
    import dips_audit.extractor_icam as ext
    from dips_audit.__main__ import _vigencia, main as principal

    pedidos = []
    monkeypatch.setattr(ext, "extraer", lambda b, c, a, *x, vigencia_minutos=None:
                        pedidos.append(vigencia_minutos) or {})
    assert _vigencia({"icam": {}}, type("A", (), {"no_cache": False})()) == 60
    assert _vigencia({"icam": {}}, type("A", (), {"no_cache": True})()) is None
    principal(["extraer-icam", "--barcode", "T40S000FDR1"])
    principal(["extraer-icam", "--barcode", "T40S000FDR1", "--no-cache"])
    principal(["barcode", "T40S000FDR1", "--no-cache"])
    assert pedidos == [60, None, None]


def test_dip_ya_auditado_manualmente_se_anota(tmp_path, auditor):
    """Una marca AUDITDIP en Technical References: se audita igual y se anota."""
    r = _registro()
    r["sections"]["TaskInformation"] += (
        "Technical References  \n\n\xa0\tName\tHyperlink\tType\tIETM\n"
        "\tDIP OPEN - RT AUDIT COMPLETED\t\xa0\tAUDITDIP\t\xa0\n\nAttachments   \n\n")
    fila = auditor.auditar_lote(lote_desde_icam(r, tmp_path / "icam.json")).filas.iloc[0]
    assert fila["VERIFICACIÓN MANUAL"].startswith(
        "- Ya se había auditado manualmente (Technical References en ICAM): "
        "Apertura: sin discrepancia.")
    assert fila["AUDITORÍA MANUAL EN ICAM"] == "Apertura: sin discrepancia"
    assert fila["RESULTADO"] != "FUERA DE ALCANCE"
    sin_marca = auditor.auditar_lote(lote_desde_icam(_registro(), tmp_path / "icam.json")).filas.iloc[0]
    assert "auditado manualmente" not in sin_marca["VERIFICACIÓN MANUAL"]
