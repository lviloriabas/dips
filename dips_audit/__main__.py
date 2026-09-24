"""Interfaz de consola.

    python -m dips_audit auditar  "entrada.xlsx" [--hoja HOJA] [--llm] [--icam ICAM.csv]
    python -m dips_audit abrir-icam
    python -m dips_audit auditar  "entrada.xlsx" --leer-icam
    python -m dips_audit extraer-icam "entrada.xlsx" | --barcode T40S...
    python -m dips_audit benchmark {sin-modelo,con-modelo}
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
from .extractor_icam import ErrorExtraccion
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


def _extraer_icam(config, archivo: Path, hoja: str | None, todos: bool = False,
                  barcodes: list[str] | None = None, actualizar: bool = False) -> Path:
    """Lee en ICAM los DIPs del Excel de entrada (o `barcodes`) que aún no se leyeron."""
    from .cargador import cargar_export
    from .extractor_icam import extraer

    icam = config["icam"]
    if not barcodes:
        datos = cargar_export(archivo, hoja).datos
        tipos = {t.upper() for t in icam.get("tipos", ["Others"])}
        barcodes = [d["barcode"] for d in datos.to_dict("records")
                    if todos or not d["tipo"] or d["tipo"].upper() in tipos]
    consola.print(f"Lectura de ICAM (solo lectura): {len(barcodes)} DIPs. Los ya leídos se "
                  f"toman de {icam['carpeta']}.")
    estado = extraer(barcodes, icam, icam["carpeta"], actualizar, consola.print)
    errores = {b: e for b, e in estado.items() if e.startswith("error")}
    leidos = sum(e == "leido" for e in estado.values())
    consola.print(f"[bold green]ICAM:[/] {leidos} leídos, "
                  f"{sum(e == 'en cache' for e in estado.values())} ya estaban, {len(errores)} con error.")
    for b, e in list(errores.items())[:10]:
        consola.print(f"[yellow]{b}:[/] {e}")
    return icam["carpeta"]


def cmd_extraer_icam(args, config) -> int:
    carpeta = _extraer_icam(config, Path(args.archivo) if args.archivo else None, args.hoja,
                            args.todos, args.barcode, args.actualizar)
    if args.barcode and len(args.barcode) == 1:
        # Diagnóstico: muestra lo que se interpretó del DIP.
        import json

        from .extractor_icam import ruta_cache
        from .icam import leer_ficha
        ruta = ruta_cache(carpeta, args.barcode[0])
        if ruta.exists():
            r = json.loads(ruta.read_text(encoding="utf-8"))
            f = leer_ficha(r["sections"], r["barcode"], r.get("page_title", ""))
            consola.print_json(json.dumps(f.como_dict(), ensure_ascii=False, default=str))
    return 0


def cmd_abrir_icam(args, config) -> int:
    from .extractor_icam import abrir_edge, edge_activo

    ya_abierto = edge_activo(int(config["icam"].get("puerto", 9222)))
    abrir_edge(config["icam"])
    consola.print("Edge de ICAM " + ("ya estaba abierto." if ya_abierto else "abierto.")
                  + " Inicie sesión en ICAM en esa ventana y déjela abierta.")
    return 0


def cmd_auditar(args, config) -> int:
    if args.leer_icam and not args.sin_icam and not args.icam:
        args.icam = str(_extraer_icam(config, Path(args.archivo), args.hoja))
    llm = _cliente_llm(config, args.modelo) if args.llm else None
    fecha = datetime.strptime(args.fecha, "%Y-%m-%d").date() if args.fecha else date.today()
    auditor = Auditor(config, llm=llm, fecha_auditoria=fecha)
    with consola.status("Auditando..."):
        resultado = auditor.auditar_archivo(Path(args.archivo), args.hoja,
                                            Path(args.icam) if args.icam else None)

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

    modo = args.modo.replace("-", "_")
    llm = None
    if modo == "con_modelo":
        try:
            llm = _cliente_llm(config, None)
        except ErrorLLM as e:
            consola.print(f"[bold red]Modelo local no disponible:[/] {e}\nEl benchmark con "
                          "modelo necesita Ollama y el modelo descargado. Para medir solo las "
                          f"reglas, ejecute {bm.MODOS['sin_modelo'][1]}.")
            return 1
    # Sin terminal (salida redirigida a un archivo) no hay animación: se imprime una
    # línea por cada consulta al modelo.
    avance = bm.Avance(None if consola.is_terminal else consola.print)
    with consola.status("Preparando: lectura de datos y auditoría solo con reglas..."):
        plan = bm.preparar(config, llm)
    descripcion = bm.descripcion(plan)
    consola.print(Markdown(f"# {bm.titulo(descripcion)}\n\n## Cómo se audita\n\n"
                           + bm.como_se_audita(descripcion, bm.texto_plan(plan))))
    consola.print()
    try:
        with bm.sin_suspension():
            if llm and consola.is_terminal:
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

    base = bm.cargar_linea_base(modo)
    ruta_json, ruta_md = bm.guardar(resultado, base)
    consola.print()
    consola.print(Markdown(bm.a_markdown(resultado, base, completo=False)))
    consola.print(f"\n[bold green]Resultado guardado:[/] {ruta_json}\n"
                  f"[bold green]Para leer (incluye los desacuerdos con el auditor):[/] {ruta_md}")
    motivo = bm.comparable(resultado, base)
    if motivo:
        consola.print(f"[yellow]{motivo}[/] Para usar este resultado como línea base, copie "
                      f"{ruta_json.name} sobre {bm.linea_base(modo)}.")
        return 0
    peores = bm.empeoraron(resultado, base)
    if peores:
        consola.print("[bold red]Empeoró respecto de la línea base:[/] " + "; ".join(peores))
        consola.print(f"[dim]Si el cambio es intencional, copie {ruta_json.name} sobre "
                      f"{bm.linea_base(modo)}.[/]")
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
    a.add_argument("--leer-icam", action="store_true",
                   help="Leer antes en ICAM (solo lectura) los DIPs del archivo y usar esos datos")
    a.add_argument("--sin-icam", action="store_true", help="Auditar solo con el Excel de entrada")
    a.add_argument("--icam", help="CSV o Excel con datos extraídos de ICAM por barcode "
                                  "(columnas barcode y technical_references; description opcional)")
    a.add_argument("--modelo", help="Modelo de Ollama (por defecto, el de config.yaml)")
    a.add_argument("--sin-excel", action="store_true", help="Solo mostrar en consola")
    a.add_argument("--max-filas", type=int, default=40, help="Filas a mostrar en consola")

    b = sub.add_parser("benchmark", help="Mide el programa con los DIPs ya auditados de "
                                        "benchmark/, sin o con modelo local (se ajusta en "
                                        "config.yaml)")
    b.add_argument("modo", choices=["sin-modelo", "con-modelo"],
                   help="sin-modelo: solo reglas, unos segundos. con-modelo: reglas + modelo "
                        "local (Ollama); en CPU tarda más de 30 min")

    n = sub.add_parser("anonimizar", help="Crea el Excel del benchmark desde el histórico, "
                                          "sin nombres del personal")
    n.add_argument("--historico", default=str(HISTORICO))
    n.add_argument("--salida", default=str(DATOS_BENCHMARK))
    n.add_argument("--cantidad", type=int, default=CANTIDAD_BENCHMARK,
                   help=f"DIPs de la muestra (por defecto {CANTIDAD_BENCHMARK}; 0 = todos)")
    n.add_argument("--semilla", type=int, default=SEMILLA_BENCHMARK,
                   help="Cambia la muestra; la misma semilla da los mismos DIPs")

    sub.add_parser("abrir-icam", help="Abre el Edge de ICAM del programa para iniciar sesión")
    x = sub.add_parser("extraer-icam", help="Lee en ICAM (solo lectura) los DIPs de un Excel de "
                                             "entrada y los guarda en data/icam/")
    x.add_argument("archivo", nargs="?", help="Excel de entrada (o use --barcode)")
    x.add_argument("--hoja")
    x.add_argument("--barcode", action="append", help="Leer solo este barcode (se puede repetir); "
                                                      "con uno solo, muestra lo interpretado")
    x.add_argument("--todos", action="store_true", help="Todos los tipos de DIP, no solo los de config")
    x.add_argument("--actualizar", action="store_true", help="Volver a leer los que ya estaban")

    sub.add_parser("referencias", help="Muestra cómo se interpretó la tabla de referencias")

    t = sub.add_parser("probar-llm", help="Verifica el modelo local y mide su velocidad")
    t.add_argument("textos", nargs="*",
                   help="Fault Names adicionales, opcionalmente con intervalo: 'NOMBRE @ 3 DAY'")
    t.add_argument("--modelo")

    args = p.parse_args(argv)
    try:
        config = cargar_configuracion(Path(args.config) if args.config else None)
        return {"auditar": cmd_auditar, "benchmark": cmd_benchmark, "anonimizar": cmd_anonimizar,
                "extraer-icam": cmd_extraer_icam, "abrir-icam": cmd_abrir_icam,
                "referencias": cmd_referencias,
                "probar-llm": cmd_probar_llm}[args.comando](args, config)
    except (ErrorCarga, ErrorCatalogo, ErrorLLM, ErrorAnonimizacion, ErrorExtraccion,
            FileNotFoundError,
            PermissionError) as ex:
        consola.print(f"[bold red]Error:[/] {ex}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
