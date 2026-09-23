"""Interfaz de consola.

    python -m dips_audit auditar  "export_icam.xlsx" [--hoja HOJA] [--llm]
    python -m dips_audit evaluar  [--historico ARCHIVO] [--llm]
    python -m dips_audit referencias
    python -m dips_audit probar-llm
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .auditor import RAIZ, Auditor, cargar_configuracion
from .cargador import ErrorCarga
from .llm import ClienteOllama, ErrorLLM
from .referencias import ErrorCatalogo

consola = Console()
ESTILOS = {
    "DISCREPANCIA CRÍTICA": "bold red",
    "DISCREPANCIA NO CRÍTICA": "bold yellow",
    "REVISAR": "bold cyan",
    "OK": "bold green",
    "FUERA DE ALCANCE": "dim",
}
HISTORICO = RAIZ / "02 - HISTORY - DIPs AUDIT (From 09Jul 15_45).xlsx"


def _cliente_llm(config: dict, modelo: str | None) -> ClienteOllama:
    c = config["llm"]
    cliente = ClienteOllama(c["url"], modelo or c["modelo"], c.get("timeout_segundos", 120),
                            solo_cpu=c.get("solo_cpu", False))
    cliente.verificar()
    return cliente


def _tabla_estados(conteo: dict[str, int]) -> Table:
    t = Table(title="Resultado por estado", show_lines=False)
    t.add_column("Estado")
    t.add_column("DIPs", justify="right")
    for estado, estilo in ESTILOS.items():
        if conteo.get(estado):
            t.add_row(f"[{estilo}]{estado}[/]", str(conteo[estado]))
    return t


def cmd_auditar(args, config) -> int:
    llm = _cliente_llm(config, args.modelo) if args.llm else None
    fecha = datetime.strptime(args.fecha, "%Y-%m-%d").date() if args.fecha else date.today()
    auditor = Auditor(config, llm=llm, fecha_auditoria=fecha)
    with consola.status("Auditando..."):
        resultado = auditor.auditar_archivo(Path(args.archivo), args.hoja)

    lote = resultado.lote
    consola.print(Panel.fit(
        f"[bold]Archivo:[/] {lote.ruta.name}\n[bold]Hoja:[/] {lote.hoja} "
        f"(encabezado en fila {lote.fila_encabezado})\n[bold]DIPs:[/] {len(resultado.filas)}   "
        f"[bold]Fecha de auditoría:[/] {fecha:%d-%b-%Y}   "
        f"[bold]Modelo local:[/] {llm.modelo if llm else 'no usado'}",
        title=f"Auditor de DIPs v{__version__}"))
    consola.print(_tabla_estados(resultado.conteo_estados()))

    filas = resultado.filas
    marcadas = filas[filas["ESTADO IA"].isin(["DISCREPANCIA CRÍTICA", "DISCREPANCIA NO CRÍTICA",
                                               "REVISAR"])]
    if not marcadas.empty:
        orden = {"DISCREPANCIA CRÍTICA": 0, "DISCREPANCIA NO CRÍTICA": 1, "REVISAR": 2}
        marcadas = marcadas.sort_values("ESTADO IA", key=lambda s: s.map(orden))
        t = Table(title="DIPs con posibles discrepancias", show_lines=True, expand=True)
        t.add_column("Fila", justify="right", no_wrap=True)
        t.add_column("Barcode", no_wrap=True)
        t.add_column("Avión", no_wrap=True)
        t.add_column("Fault Name", ratio=2)
        t.add_column("Estado", no_wrap=True)
        t.add_column("Hallazgos", ratio=4)
        for _, f in marcadas.head(args.max_filas).iterrows():
            hallazgos = "\n".join(l for l in f["HALLAZGOS"].splitlines()
                                  if not l.startswith("[OBSERVACION]"))
            t.add_row(str(f["Fila Excel"]), f["Fault Barcode"], f["Aircraft"],
                      f["Fault Name"][:90], f"[{ESTILOS[f['ESTADO IA']]}]{f['ESTADO IA']}[/]",
                      hallazgos)
        consola.print(t)
        if len(marcadas) > args.max_filas:
            consola.print(f"[dim]... y {len(marcadas) - args.max_filas} más en el Excel.[/]")

    for nota in resultado.advertencias:
        consola.print(f"[yellow]Nota:[/] {nota}")

    if not args.sin_excel:
        from .reporte import exportar_excel, ruta_salida
        ruta = Path(args.salida) if args.salida else ruta_salida(resultado, config["carpeta_salida"])
        exportar_excel(resultado, ruta)
        consola.print(f"\n[bold green]Reporte guardado en:[/] {ruta}")
    consola.print(f"[dim]Tiempo: {resultado.segundos:.1f} s"
                  + (f", consultas al modelo: {resultado.consultas_llm}" if llm else "") + "[/]")
    return 0


def cmd_evaluar(args, config) -> int:
    from .evaluacion import evaluar, exportar_evaluacion

    llm = _cliente_llm(config, args.modelo) if args.llm else None
    auditor = Auditor(config, llm=llm)
    with consola.status("Evaluando contra el histórico..."):
        ev = evaluar(auditor, Path(args.historico))
    m = ev.metricas

    t = Table(title="Matriz: auditor humano (filas) vs automático (columnas)")
    t.add_column("Humano \\ IA")
    for c in ev.matriz.columns:
        t.add_column(c, justify="right")
    for estado, fila in ev.matriz.iterrows():
        t.add_row(estado, *[str(v) for v in fila])
    consola.print(t)

    def pct(a, b):
        return f"{a}/{b} ({a / b * 100:.0f}%)" if b else "0/0"

    consola.print(Panel(
        f"DIPs Others comparados: {m['dips_comparados']}\n"
        f"Asociados a una referencia por reglas: {pct(m['asociados_por_reglas'], m['dips_comparados'])}\n\n"
        f"Discrepancias humanas marcadas por el auditor automático (discrepancia o revisar): "
        f"{pct(m['humano_disc_marcadas_ia'], m['humano_discrepancias'])}\n"
        f"  ... excluyendo attachments/RIR (no vienen en el Excel): "
        f"{pct(m['humano_disc_detectables_marcadas'], m['humano_disc_detectables'])}\n\n"
        f"DIPs OK para el humano y OK para el automático: {pct(m['humano_ok_ia_ok'], m['humano_ok'])}\n"
        f"DIPs OK para el humano con discrepancia automática: "
        f"{pct(m['humano_ok_ia_discrepancia'], m['humano_ok'])}\n"
        f"DIPs OK para el humano marcados REVISAR: {pct(m['humano_ok_ia_revisar'], m['humano_ok'])}\n\n"
        f"Hallazgos automáticos en DIPs que el humano dio OK: {m['codigos_en_humano_ok']}\n"
        f"Tiempo: {m['segundos']:.1f} s",
        title="Evaluación contra el histórico"))

    t = Table(title="Discrepancias humanas por tema del comentario")
    t.add_column("Tema")
    t.add_column("Humano", justify="right")
    t.add_column("Automático: discrepancia/revisar", justify="right")
    t.add_column("Automático: cualquier hallazgo (incl. observación)", justify="right")
    for tema, (total, marca, algun) in sorted(m["por_tema"].items(), key=lambda x: -x[1][0]):
        t.add_row(tema, str(total), str(marca), str(algun))
    consola.print(t)

    carpeta = config["carpeta_salida"]
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"EVALUACION_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    exportar_evaluacion(ev, ruta)
    consola.print(f"[bold green]Detalle guardado en:[/] {ruta}")
    return 0


def cmd_referencias(args, config) -> int:
    auditor = Auditor(config)
    cat = auditor.catalogo
    t = Table(title=f"Catálogo Others ({len(cat.entradas)} entradas)", show_lines=False)
    t.add_column("ID", no_wrap=True)
    t.add_column("Intervalo interpretado")
    t.add_column("Parent")
    t.add_column("Referencia técnica")
    for e in cat.entradas:
        if e.hasta_vencimiento:
            intervalo = "UNTIL DUE DATE"
        elif e.no_verificable:
            intervalo = "[yellow]manual[/]"
        else:
            intervalo = "; ".join(
                " o ".join(map(str, v.limites)) + (f" [{','.join(v.flotas)}]" if v.flotas else "")
                + (f" RIR {v.rir}" if v.rir else "") for v in e.variantes)
        t.add_row(e.id, intervalo, "/".join(sorted(e.parent_assy)), e.referencias_tecnicas[:60])
    consola.print(t)
    for a in cat.advertencias:
        consola.print(f"[yellow]Advertencia:[/] {a}")
    return 0


def cmd_probar_llm(args, config) -> int:
    llm = _cliente_llm(config, args.modelo)
    auditor = Auditor(config, llm=llm)
    from .asociacion import asociar
    from .referencias import normalizar_unidad
    ejemplos = ["DIP - DEFIBRILLATOR DUE DATE @ 38 DAY", "DIP - NOSE INTERNAL INSPECTION @ 3 CYCLES",
                "CREW 02 BOTLE LOW @ 3 DAY"] + args.textos
    for ejemplo in ejemplos:
        texto, _, intervalo = ejemplo.partition(" @ ")
        valor, _, unidad = intervalo.partition(" ")
        inicio = time.perf_counter()
        a = asociar(texto, auditor.catalogo, llm, float(valor) if valor else None,
                    normalizar_unidad(unidad))
        consola.print(f"[bold]{texto}[/] ({intervalo or 'sin intervalo'}) -> "
                      f"{a.entrada.id if a.entrada else a.metodo} [{a.metodo}] "
                      f"({time.perf_counter() - inicio:.1f} s) [dim]{a.detalle}[/]")
    return 0


def cmd_benchmark(args, config) -> int:
    import pandas as pd
    from rich.progress import Progress

    from .benchmark import cargar_casos, evaluar_modelo, seleccionar

    modelos = [m.strip() for m in (args.modelos or ",".join(config["llm"]["modelos_benchmark"]))
               .split(",") if m.strip()]
    variantes = [(m, False) for m in modelos] + ([(m, True) for m in modelos] if args.pensar else [])
    auditor = Auditor(config)
    casos = seleccionar(cargar_casos(), args.casos)
    resultados = []
    with Progress(console=consola) as progreso:
        for modelo, pensar in variantes:
            tarea = progreso.add_task(f"{modelo}{' (thinking)' if pensar else ''}", total=len(casos))
            r = evaluar_modelo(modelo, auditor.catalogo, casos, config["llm"]["url"], pensar,
                               progreso=lambda: progreso.advance(tarea), solo_cpu=args.cpu)
            resultados.append(r)
            if r.error:
                progreso.console.print(f"[yellow]{modelo}: {r.error}[/]")

    positivos = sum(1 for g, _ in casos if g == "positivo")
    negativos = len(casos) - positivos
    t = Table(title=f"Benchmark de modelos locales ({len(casos)} casos: {positivos} con "
                    f"referencia, {negativos} sin referencia) - "
                    f"{'solo CPU' if args.cpu else 'GPU si está disponible'}")
    for col, just in [("Modelo", "left"), ("Aciertos modelo", "right"),
                      ("Aciertos finales", "right"), ("Con ref.", "right"),
                      ("Sin ref.", "right"), ("Errores aceptados", "right"),
                      ("s/consulta", "right"), ("p95 s", "right"), ("Carga s", "right"),
                      ("RAM GB", "right")]:
        t.add_column(col, justify=just)
    validos = [r for r in resultados if not r.error and r.total]
    for r in sorted(validos, key=lambda r: (r.errores_aceptados, -r.aciertos_finales,
                                            r.latencia_media)):
        t.add_row(r.modelo + (" [thinking]" if r.pensar else ""),
                  f"{r.aciertos_crudos}/{r.total}", f"{r.aciertos_finales}/{r.total}",
                  f"{r.positivos_ok}/{positivos}", f"{r.negativos_ok}/{negativos}",
                  f"[{'red' if r.errores_aceptados else 'green'}]{r.errores_aceptados}[/]",
                  f"{r.latencia_media:.1f}", f"{r.latencia_p95:.1f}", f"{r.carga_s:.0f}",
                  f"{r.ram_gb:.1f}" if r.ram_gb else "?")
    consola.print(t)

    carpeta = config["carpeta_salida"]
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / (f"BENCHMARK_{'CPU_' if args.cpu else ''}"
                      f"{datetime.now():%Y%m%d_%H%M%S}.xlsx")
    resumen = pd.DataFrame([{
        "modelo": r.modelo, "thinking": r.pensar, "solo_cpu": r.solo_cpu, "casos": r.total,
        "aciertos_modelo": r.aciertos_crudos, "aciertos_finales": r.aciertos_finales,
        "con_referencia_ok": r.positivos_ok, "sin_referencia_ok": r.negativos_ok,
        "errores_aceptados": r.errores_aceptados, "s_por_consulta": round(r.latencia_media, 2),
        "p95_s": round(r.latencia_p95, 2), "carga_s": round(r.carga_s, 1),
        "ram_gb": round(r.ram_gb, 2) if r.ram_gb else None, "error": r.error,
    } for r in resultados])
    with pd.ExcelWriter(ruta) as w:
        resumen.to_excel(w, sheet_name="Resumen", index=False)
        pd.DataFrame([d for r in resultados for d in r.detalle]).to_excel(
            w, sheet_name="Detalle", index=False)
    consola.print(f"[bold green]Detalle guardado en:[/] {ruta}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="dips_audit", description="Auditor preliminar de DIPs")
    p.add_argument("--config", help="Ruta a config.yaml")
    sub = p.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("auditar", help="Audita un Excel exportado de ICAM")
    a.add_argument("archivo")
    a.add_argument("--hoja", help="Hoja a leer (por defecto, la primera con 'Fault Barcode')")
    a.add_argument("--salida", help="Ruta del Excel de resultado")
    a.add_argument("--fecha", help="Fecha de auditoría AAAA-MM-DD (por defecto, hoy)")
    a.add_argument("--llm", action="store_true", help="Usar el modelo local para casos sin referencia")
    a.add_argument("--modelo", help="Modelo de Ollama (por defecto, el de config.yaml)")
    a.add_argument("--sin-excel", action="store_true", help="Solo mostrar en consola")
    a.add_argument("--max-filas", type=int, default=40, help="Filas a mostrar en consola")

    e = sub.add_parser("evaluar", help="Compara contra las auditorías humanas del histórico")
    e.add_argument("--historico", default=str(HISTORICO))
    e.add_argument("--llm", action="store_true")
    e.add_argument("--modelo")

    sub.add_parser("referencias", help="Muestra cómo se interpretó la tabla de referencias")

    t = sub.add_parser("probar-llm", help="Verifica el modelo local y mide su velocidad")
    t.add_argument("textos", nargs="*",
                   help="Fault Names adicionales, opcionalmente con intervalo: 'NOMBRE @ 3 DAY'")
    t.add_argument("--modelo")

    b = sub.add_parser("benchmark", help="Compara modelos locales (precisión, velocidad, RAM)")
    b.add_argument("--modelos", help="Lista separada por comas (por defecto, la de config.yaml)")
    b.add_argument("--pensar", action="store_true",
                   help="Evaluar también cada modelo con modo 'thinking'")
    b.add_argument("--cpu", action="store_true",
                   help="Forzar solo CPU (como en las PCs del departamento, sin GPU)")
    b.add_argument("--casos", type=int, help="Usar solo N casos (balanceados) para medir rápido")

    args = p.parse_args(argv)
    try:
        config = cargar_configuracion(Path(args.config) if args.config else None)
        return {"auditar": cmd_auditar, "evaluar": cmd_evaluar, "referencias": cmd_referencias,
                "probar-llm": cmd_probar_llm, "benchmark": cmd_benchmark}[args.comando](args, config)
    except (ErrorCarga, ErrorCatalogo, ErrorLLM, FileNotFoundError, PermissionError) as ex:
        consola.print(f"[bold red]Error:[/] {ex}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
