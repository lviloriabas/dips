"""Interfaz de consola.

    python -m dips_audit auditar  "entrada.xlsx" [--hoja HOJA] [--llm]
    python -m dips_audit benchmark
    python -m dips_audit anonimizar [--historico ARCHIVO]
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
from .anonimizar import CANTIDAD as CANTIDAD_BENCHMARK
from .anonimizar import SEMILLA as SEMILLA_BENCHMARK
from .anonimizar import ErrorAnonimizacion
from .auditor import RAIZ, Auditor, cargar_configuracion
from .benchmark import DATOS as DATOS_BENCHMARK
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
    cliente = ClienteOllama.desde_config(config["llm"], modelo)
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


class _PantallaAvance:
    """Lo que se ve mientras corre el benchmark. Rich la redibuja dos veces por segundo."""

    def __init__(self, avance):
        self.avance = avance

    def __rich__(self):
        from rich.console import Group
        from rich.progress_bar import ProgressBar
        from rich.text import Text

        from .benchmark import aprox, reloj

        a = self.avance
        barra = Table.grid(padding=(0, 1))
        barra.add_row(ProgressBar(total=max(a.previstas, 1), completed=a.hechas, width=40),
                      f"{a.hechas} de {a.previstas} consultas al modelo")
        tiempos = (f"Transcurrido [bold]{reloj(a.transcurrido)}[/] · falta "
                   f"[bold]{aprox(a.faltante)}[/] · total estimado [bold]{aprox(a.total)}[/]")
        if a.por_consulta:
            tiempos += f" · {a.por_consulta:.1f} s por consulta"
        lineas = [Text.from_markup(f"[bold cyan]{a.etapa}[/]"), barra, Text.from_markup(tiempos)]
        if a.consultando:
            lineas.append(Text(f"Consultando al modelo: {a.consultando[:90]}", style="dim"))
        return Group(*lineas)


def cmd_benchmark(args, config) -> int:
    from rich.live import Live
    from rich.markdown import Markdown

    from . import benchmark as bm

    llm, sin_modelo = None, ""
    try:
        llm = _cliente_llm(config, None)
    except ErrorLLM as e:
        sin_modelo = str(e)
    # Sin terminal (salida redirigida a un archivo) no hay animación: se imprime una
    # línea por cada consulta al modelo.
    avance = bm.Avance(None if consola.is_terminal else consola.print)
    with consola.status("Preparando: lectura de datos y auditoría solo con reglas..."):
        plan = bm.preparar(config, llm, sin_modelo)
    consola.print(Markdown("# Benchmark del auditor de DIPs\n\n## Cómo se audita\n\n"
                           + bm.como_se_audita(bm.descripcion(plan), bm.texto_plan(plan))))
    consola.print()
    try:
        with bm.sin_suspension():
            if consola.is_terminal:
                with Live(_PantallaAvance(avance), console=consola, refresh_per_second=2):
                    resultado = bm.ejecutar(plan, avance)
            else:
                resultado = bm.ejecutar(plan, avance)
    except KeyboardInterrupt:
        if llm:
            llm.descargar_de_memoria()
        consola.print("[yellow]Benchmark cancelado. No se guardó ningún resultado.[/]")
        return 130
    except ErrorLLM as e:
        consola.print(f"[bold red]El modelo local dejó de responder[/] después de {avance.hechas} "
                      f"de {avance.previstas} consultas: {e}\nRevise que Ollama siga abierto y "
                      "que el equipo no se haya suspendido. No se guardó ningún resultado.")
        return 1

    base = bm.cargar_linea_base()
    ruta_json, ruta_md = bm.guardar(resultado, base)
    consola.print()
    consola.print(Markdown(bm.a_markdown(resultado, base, completo=False)))
    consola.print(f"\n[bold green]Resultado guardado:[/] {ruta_json}\n"
                  f"[bold green]Para leer (incluye los desacuerdos con el auditor):[/] {ruta_md}")
    if not llm:
        consola.print(f"[bold yellow]Modelo local no disponible:[/] {sin_modelo} "
                      "Se midieron solo las reglas.")
    motivo = bm.comparable(resultado, base)
    if motivo:
        consola.print(f"[yellow]{motivo}[/] Para usar este resultado como línea base, copie "
                      f"{ruta_json.name} sobre {bm.LINEA_BASE}.")
        return 0
    peores = bm.empeoraron(resultado, base)
    if peores:
        consola.print("[bold red]Empeoró respecto de la línea base:[/] " + "; ".join(peores))
        consola.print(f"[dim]Si el cambio es intencional, copie {ruta_json.name} sobre "
                      f"{bm.LINEA_BASE}.[/]")
        return 2
    consola.print("[bold green]Ningún indicador empeoró respecto de la línea base.[/]")
    return 0


def cmd_anonimizar(args, config) -> int:
    from .anonimizar import anonimizar, guardar

    with consola.status("Anonimizando el histórico..."):
        anon = anonimizar(Path(args.historico), args.cantidad or None, args.semilla)
        ruta = guardar(anon, Path(args.salida))
    veredictos = anon.tabla["STATUS - Apertura"].value_counts().to_dict()
    consola.print(f"[bold green]Guardado:[/] {ruta}\n"
                  f"DIPs Others: {len(anon.tabla)} ("
                  + ", ".join(f"{v}: {n}" for v, n in veredictos.items()) + "). "
                  f"Columnas del personal eliminadas. Nombres reemplazados por [PERSONA] "
                  f"en {anon.textos_modificados} textos.\n"
                  "[dim]Revise los comentarios antes de subir el archivo.[/]")
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
                    normalizar_unidad(unidad), auditor.parametros)
        consola.print(f"[bold]{texto}[/] ({intervalo or 'sin intervalo'}) -> "
                      f"{a.entrada.id if a.entrada else a.metodo} [{a.metodo}] "
                      f"({time.perf_counter() - inicio:.1f} s) [dim]{a.detalle}[/]")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="dips_audit", description="Auditor preliminar de DIPs")
    p.add_argument("--config", help="Ruta a config.yaml")
    sub = p.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("auditar", help="Audita un Excel de entrada")
    a.add_argument("archivo")
    a.add_argument("--hoja", help="Hoja a leer (por defecto, la primera con 'Fault Barcode')")
    a.add_argument("--salida", help="Ruta del Excel de resultado")
    a.add_argument("--fecha", help="Fecha de auditoría AAAA-MM-DD (por defecto, hoy)")
    a.add_argument("--llm", action="store_true", help="Usar el modelo local para casos sin referencia")
    a.add_argument("--modelo", help="Modelo de Ollama (por defecto, el de config.yaml)")
    a.add_argument("--sin-excel", action="store_true", help="Solo mostrar en consola")
    a.add_argument("--max-filas", type=int, default=40, help="Filas a mostrar en consola")

    sub.add_parser("benchmark", help="Mide el programa y el modelo local con los DIPs ya "
                                    "auditados de benchmark/ (sin opciones; se ajusta en "
                                    "config.yaml)")

    n = sub.add_parser("anonimizar", help="Crea el Excel del benchmark desde el histórico, "
                                          "sin nombres del personal")
    n.add_argument("--historico", default=str(HISTORICO))
    n.add_argument("--salida", default=str(DATOS_BENCHMARK))
    n.add_argument("--cantidad", type=int, default=CANTIDAD_BENCHMARK,
                   help=f"DIPs de la muestra (por defecto {CANTIDAD_BENCHMARK}; 0 = todos)")
    n.add_argument("--semilla", type=int, default=SEMILLA_BENCHMARK,
                   help="Cambia la muestra; la misma semilla da los mismos DIPs")

    sub.add_parser("referencias", help="Muestra cómo se interpretó la tabla de referencias")

    t = sub.add_parser("probar-llm", help="Verifica el modelo local y mide su velocidad")
    t.add_argument("textos", nargs="*",
                   help="Fault Names adicionales, opcionalmente con intervalo: 'NOMBRE @ 3 DAY'")
    t.add_argument("--modelo")

    args = p.parse_args(argv)
    try:
        config = cargar_configuracion(Path(args.config) if args.config else None)
        return {"auditar": cmd_auditar, "benchmark": cmd_benchmark, "anonimizar": cmd_anonimizar,
                "referencias": cmd_referencias,
                "probar-llm": cmd_probar_llm}[args.comando](args, config)
    except (ErrorCarga, ErrorCatalogo, ErrorLLM, ErrorAnonimizacion, FileNotFoundError,
            PermissionError) as ex:
        consola.print(f"[bold red]Error:[/] {ex}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
