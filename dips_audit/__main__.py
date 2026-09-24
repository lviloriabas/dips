"""Interfaz de consola.

    python -m dips_audit auditar  "entrada.xlsx" [--hoja HOJA] [--icam ICAM.csv]
    python -m dips_audit abrir-icam
    python -m dips_audit auditar  "entrada.xlsx" --leer-icam
    python -m dips_audit extraer-icam "entrada.xlsx" | --barcode T40S...
    python -m dips_audit benchmark
    python -m dips_audit anonimizar [--historico ARCHIVO]
    python -m dips_audit auditar  "entrada.xlsx" --categorias "Incorrect DIP Interval" RIR
    python -m dips_audit referencias
    python -m dips_audit categorias
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
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
from .referencias import ErrorCatalogo

consola = Console()
ESTILOS = {
    "POSIBLE DISCREPANCIA": "bold yellow",
    "OK": "bold green",
    "FUERA DE ALCANCE": "dim",
}
HISTORICO = RAIZ / "02 - HISTORY - DIPs AUDIT (From 09Jul 15_45).xlsx"


def _pct(n: int, total: int) -> str:
    return f"{n / total:.1%}" if total else "-"


def _duracion(segundos: float) -> str:
    if segundos < 60:
        return f"{segundos:.1f} s"
    m, s = divmod(round(segundos), 60)
    return f"{m} min {s:02d} s" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _tabla_estados(filas: pd.DataFrame) -> Table:
    """DIPs por resultado. El % de OK y POSIBLE DISCREPANCIA es sobre los DIPs auditados;
    el de FUERA DE ALCANCE, sobre el total del archivo."""
    total = len(filas)
    conteo = filas["RESULTADO"].value_counts().to_dict()
    auditados = total - conteo.get("FUERA DE ALCANCE", 0)
    t = Table(title=f"Resultado por DIP ({auditados} auditados de {total})",
              caption="% sobre los auditados; fuera de alcance, sobre el total.")
    t.add_column("Resultado")
    t.add_column("DIPs", justify="right")
    t.add_column("%", justify="right")
    for estado, estilo in ESTILOS.items():
        n = conteo.get(estado, 0)
        if n or estado != "FUERA DE ALCANCE":
            base = total if estado == "FUERA DE ALCANCE" else auditados
            t.add_row(f"[{estilo}]{estado}[/]", str(n), _pct(n, base))
    return t


def _tabla_hallazgos(resultado) -> Table | None:
    """Tipos de discrepancia: cuántos hallazgos y en cuántos DIPs (% de los auditados)."""
    h = resultado.hallazgos
    h = h[h["Severidad"] != "OBSERVACION"]
    if h.empty:
        return None
    auditados = int((resultado.filas["RESULTADO"] != "FUERA DE ALCANCE").sum())
    t = Table(title="Posibles discrepancias por tipo",
              caption="Un DIP puede tener varios tipos. % sobre los DIPs auditados.")
    t.add_column("Tipo de discrepancia")
    t.add_column("Apertura", justify="right")
    t.add_column("Cierre", justify="right")
    t.add_column("Hallazgos", justify="right")
    t.add_column("DIPs", justify="right")
    t.add_column("%", justify="right")
    for tipo, g in sorted(h.groupby("Tipo de discrepancia"),
                          key=lambda x: -x[1]["Fila Excel"].nunique()):
        dips = g["Fila Excel"].nunique()
        t.add_row(tipo, str(int((g["Auditoría"] == "APERTURA").sum())),
                  str(int((g["Auditoría"] == "CIERRE").sum())), str(len(g)), str(dips),
                  _pct(dips, auditados))
    dips = h["Fila Excel"].nunique()
    t.add_row("[bold]Total[/]", str(int((h["Auditoría"] == "APERTURA").sum())),
              str(int((h["Auditoría"] == "CIERRE").sum())), f"[bold]{len(h)}[/]",
              f"[bold]{dips}[/]", f"[bold]{_pct(dips, auditados)}[/]", end_section=True)
    return t


def _resumen(resultado, tiempos: dict[str, float]) -> Panel:
    """Resumen final de la corrida: DIPs, resultado, hallazgos y tiempos."""
    filas = resultado.filas
    total = len(filas)
    en_alcance = filas[filas["RESULTADO"] != "FUERA DE ALCANCE"]
    auditados = len(en_alcance)
    posibles = int((en_alcance["RESULTADO"] == "POSIBLE DISCREPANCIA").sum())
    ok = int((en_alcance["RESULTADO"] == "OK").sum())
    h = resultado.hallazgos
    observaciones = int((h["Severidad"] == "OBSERVACION").sum())
    discrepancias = len(h) - observaciones
    manuales = int((en_alcance["VERIFICACIÓN MANUAL"] != "").sum())
    cierre = int((en_alcance["AUDITORÍA"] == "CIERRE").sum())
    lineas = [
        f"[bold]DIPs en el archivo:[/] {total}   [bold]Auditados:[/] {auditados} "
        f"(apertura {auditados - cierre}, cierre {cierre})   "
        f"[bold]Fuera de alcance:[/] {total - auditados}",
        f"[{ESTILOS['POSIBLE DISCREPANCIA']}]POSIBLE DISCREPANCIA:[/] {posibles} "
        f"({_pct(posibles, auditados)})   [{ESTILOS['OK']}]OK:[/] {ok} ({_pct(ok, auditados)})",
        f"[bold]Hallazgos:[/] {discrepancias} posibles discrepancias"
        + (f" ({discrepancias / posibles:.1f} por DIP marcado)" if posibles else "")
        + f", {observaciones} observaciones",
        f"[bold]DIPs con verificación manual pendiente:[/] {manuales} ({_pct(manuales, auditados)})",
        "",
        "[bold]Tiempos:[/] " + "   ".join(f"{k} {_duracion(v)}" for k, v in tiempos.items()
                                         if k != "Total"),
        f"[bold]Tiempo total:[/] {_duracion(tiempos['Total'])}"
        + (f"   ({tiempos['Auditoría'] / auditados:.2f} s por DIP auditado)" if auditados else ""),
    ]
    return Panel.fit("\n".join(lineas), title="Resumen de la corrida", border_style="green")


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


def _fecha_hora(texto: str | None) -> datetime | None:
    if not texto:
        return None
    for formato in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise SystemExit(f"Fecha inválida: {texto} (use AAAA-MM-DD o 'AAAA-MM-DD HH:MM').")


def _modo_prueba(args, config: dict) -> bool:
    """Modo prueba: el Excel está dentro de la carpeta de pruebas (config carpeta_pruebas)
    o se pidió --prueba. Los datos de ICAM y los resultados van a pruebas/icam y
    pruebas/salidas, y los resultados se marcan como PRUEBA, para no mezclarlos con
    auditorías reales."""
    carpeta = Path(config["carpeta_pruebas"]).resolve()
    archivo = getattr(args, "archivo", None)
    dentro = bool(archivo) and Path(archivo).resolve().is_relative_to(carpeta)
    if not (getattr(args, "prueba", False) or dentro):
        return False
    config["modo_prueba"] = True
    config["icam"]["carpeta"] = carpeta / "icam"
    config["carpeta_salida"] = carpeta / "salidas"
    consola.print(Panel.fit(
        "[bold]MODO PRUEBA[/]: datos de prueba, no es una auditoría real.\n"
        f"ICAM: {config['icam']['carpeta']}\nResultados: {config['carpeta_salida']} "
        "(con el prefijo PRUEBA_)", border_style="yellow"))
    return True


def _filtrar_categorias(args, auditor: Auditor) -> None:
    """--categorias / --excluir-categorias: revisar solo algunos tipos de discrepancia."""
    if not (args.categorias or args.excluir_categorias):
        return
    try:
        revisados = auditor.discrepancias.filtrar(args.categorias, args.excluir_categorias)
    except ValueError as e:
        raise SystemExit(f"{e}\nVea los tipos con: python -m dips_audit categorias")
    consola.print(Panel.fit("\n".join(revisados) or "ninguno",
                            title="Tipos de discrepancia que se revisan", border_style="cyan"))


def cmd_comparar(args, config) -> int:
    from .comparacion import comparar, exportar

    inicio = time.perf_counter()
    if args.leer_icam and not args.icam:
        args.icam = str(_extraer_icam(config, Path(args.archivo), args.hoja))
    auditor = Auditor(config)
    _filtrar_categorias(args, auditor)
    with consola.status("Auditando a la fecha y hora de cada auditoría manual..."):
        c = comparar(auditor, Path(args.archivo), args.hoja, Path(args.icam) if args.icam else None)

    for titulo, nota, df in c.tablas:
        if df.empty:
            continue
        largas = {"Apertura: motivos", "Cierre: motivos", "Motivo", "Ejemplos", "DIP (Fault Name)"}
        t = Table(title=f"[bold]{titulo}[/]", caption=nota or None, show_lines=len(df.columns) > 5)
        for columna in df.columns:
            numerica = pd.api.types.is_numeric_dtype(df[columna])
            t.add_column(columna, justify="right" if numerica else "left",
                         ratio=3 if columna in largas else None, overflow="fold")
        for fila in df.head(25).itertuples(index=False):
            t.add_row(*("" if v is None else str(v) for v in fila))
        consola.print(t)
    ruta = exportar(c, Path(config["carpeta_salida"]))
    consola.print(f"\n[bold green]Comparación guardada en:[/] {ruta}")
    consola.print(f"[bold]Tiempo total:[/] {_duracion(time.perf_counter() - inicio)}")
    return 0


def cmd_auditar(args, config) -> int:
    inicio = time.perf_counter()
    tiempos: dict[str, float] = {}
    if args.leer_icam and not args.sin_icam and not args.icam:
        args.icam = str(_extraer_icam(config, Path(args.archivo), args.hoja))
        tiempos["Lectura de ICAM"] = time.perf_counter() - inicio
    marca = time.perf_counter()
    auditor = Auditor(config, fecha_auditoria=_fecha_hora(args.fecha))
    _filtrar_categorias(args, auditor)
    tiempos["Carga de referencias"] = time.perf_counter() - marca
    marca = time.perf_counter()
    with consola.status("Auditando..."):
        resultado = auditor.auditar_archivo(Path(args.archivo), args.hoja,
                                            Path(args.icam) if args.icam else None)
    tiempos["Auditoría"] = time.perf_counter() - marca
    fecha = auditor.fecha_auditoria

    lote = resultado.lote
    consola.print(Panel.fit(
        f"[bold]Archivo:[/] {lote.ruta.name}\n[bold]Hoja:[/] {lote.hoja} "
        f"(encabezado en fila {lote.fila_encabezado})\n[bold]DIPs:[/] {len(resultado.filas)}   "
        f"[bold]Fecha de auditoría:[/] {fecha:%d-%b-%Y %H:%M}",
        title=f"Auditor de DIPs v{__version__}"))
    filas = resultado.filas
    marcadas = filas[filas["RESULTADO"] == "POSIBLE DISCREPANCIA"]
    if not marcadas.empty:
        t = Table(title="DIPs con posibles discrepancias", show_lines=True, expand=True)
        t.add_column("Fila", justify="right", no_wrap=True)
        t.add_column("Fault Barcode", no_wrap=True)
        t.add_column("Aircraft", no_wrap=True)
        t.add_column("Fault Name", ratio=2)
        t.add_column("Estado", no_wrap=True)
        t.add_column("Hallazgos", ratio=4)
        for _, f in marcadas.head(args.max_filas).iterrows():
            hallazgos = "\n".join(l for l in f["HALLAZGOS"].splitlines()
                                  if not l.startswith("[OBSERVACIÓN]"))
            t.add_row(str(f["Fila Excel"]), f["Fault Barcode"], f["Aircraft"],
                      f["Fault Name"][:90], f"[{ESTILOS[f['RESULTADO']]}]{f['RESULTADO']}[/]",
                      hallazgos)
        consola.print(t)
        if len(marcadas) > args.max_filas:
            consola.print(f"[dim]... y {len(marcadas) - args.max_filas} más en el Excel.[/]")

    for nota in resultado.advertencias:
        consola.print(f"[yellow]Nota:[/] {nota}")

    if not args.sin_excel:
        from .reporte import exportar_excel, ruta_salida
        marca = time.perf_counter()
        ruta = Path(args.salida) if args.salida else ruta_salida(resultado, config["carpeta_salida"])
        exportar_excel(resultado, ruta)
        tiempos["Excel"] = time.perf_counter() - marca
        consola.print(f"\n[bold green]Reporte guardado en:[/] {ruta}")
    tiempos["Total"] = time.perf_counter() - inicio

    consola.print()
    consola.print(_tabla_estados(filas))
    tabla = _tabla_hallazgos(resultado)
    if tabla:
        consola.print(tabla)
    consola.print(_resumen(resultado, tiempos))
    return 0


def cmd_benchmark(args, config) -> int:
    from rich.markdown import Markdown

    from . import benchmark as bm

    with consola.status("Auditando los DIPs del benchmark..."):
        resultado = bm.ejecutar(config)
    consola.print(Markdown(f"# {bm.TITULO}\n\n## Cómo se audita\n\n"
                           + bm.como_se_audita(resultado)))
    consola.print()

    base = bm.cargar_linea_base()
    ruta_json, ruta_md = bm.guardar(resultado, base)
    consola.print(Markdown(bm.a_markdown(resultado, base, completo=False)))
    consola.print(f"\n[bold green]Resultado guardado:[/] {ruta_json}\n"
                  f"[bold green]Para leer (incluye los desacuerdos con el auditor):[/] {ruta_md}")
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


def cmd_categorias(args, config) -> int:
    from .discrepancias import cargar_discrepancias

    d = cargar_discrepancias(config["discrepancias"])
    t = Table(title="Tipos de discrepancia (config/discrepancias.yaml)", show_lines=True)
    t.add_column("Tipo", no_wrap=True)
    t.add_column("Activo", no_wrap=True)
    t.add_column("Reglas")
    for tipo, activo in d.tipos.items():
        reglas = "\n".join(f"{r.codigo} ({r.severidad}" + (")" if r.activa else ", inactiva)")
                           for r in d.reglas.values() if r.tipo == tipo)
        t.add_row(tipo, "sí" if activo else "[dim]no[/]", reglas)
    consola.print(t)
    consola.print('Para revisar solo algunos: auditar.bat "entrada.xlsx" --categorias '
                  '"Incorrect DIP Interval" "technical reference"  (basta una parte del nombre)\n'
                  'Para omitir algunos: --excluir-categorias RIR "Missing S/N"')
    return 0


def _argumentos_categorias(p: argparse.ArgumentParser) -> None:
    p.add_argument("--categorias", nargs="+", metavar="TIPO",
                   help="Revisar solo estos tipos de discrepancia (basta una parte del nombre, "
                        "p. ej. \"technical reference\"). Ver: python -m dips_audit categorias")
    p.add_argument("--excluir-categorias", nargs="+", metavar="TIPO",
                   help="No revisar estos tipos de discrepancia")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="dips_audit", description="Auditor preliminar de DIPs")
    p.add_argument("--config", help="Ruta a config.yaml")
    sub = p.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("auditar", help="Audita un Excel de entrada")
    a.add_argument("archivo")
    a.add_argument("--hoja", help="Hoja a leer (por defecto, la primera con 'Fault Barcode')")
    a.add_argument("--prueba", action="store_true", help="Datos de prueba: usa pruebas/icam y pruebas/salidas y marca los resultados como PRUEBA (automático si el Excel está en pruebas/)")
    a.add_argument("--salida", help="Ruta del Excel de resultado")
    a.add_argument("--fecha", help="Fecha y hora de auditoría 'AAAA-MM-DD HH:MM' "
                   "(por defecto, ahora)")
    a.add_argument("--leer-icam", action="store_true",
                   help="Leer antes en ICAM (solo lectura) los DIPs del archivo y usar esos datos")
    a.add_argument("--sin-icam", action="store_true", help="Auditar solo con el Excel de entrada")
    a.add_argument("--icam", help="CSV o Excel con datos extraídos de ICAM por barcode "
                                  "(columnas barcode y technical_references; description opcional)")
    a.add_argument("--sin-excel", action="store_true", help="Solo mostrar en consola")
    a.add_argument("--max-filas", type=int, default=40, help="Filas a mostrar en consola")
    _argumentos_categorias(a)

    c = sub.add_parser("comparar", help="Compara el programa con la auditoría manual del Excel "
                                        "(apertura y cierre, a la fecha y hora de cada una)")
    c.add_argument("archivo")
    c.add_argument("--hoja")
    c.add_argument("--prueba", action="store_true", help="Datos de prueba: usa pruebas/icam y pruebas/salidas y marca los resultados como PRUEBA (automático si el Excel está en pruebas/)")
    c.add_argument("--leer-icam", action="store_true",
                   help="Leer antes en ICAM (solo lectura) los DIPs del archivo y usar esos datos")
    c.add_argument("--icam", help="Datos de ICAM ya extraídos (p. ej. data/icam)")
    _argumentos_categorias(c)

    sub.add_parser("benchmark", help="Mide el programa con los DIPs ya auditados de benchmark/")

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
    x.add_argument("--prueba", action="store_true", help="Datos de prueba: usa pruebas/icam y pruebas/salidas y marca los resultados como PRUEBA (automático si el Excel está en pruebas/)")
    x.add_argument("--barcode", action="append", help="Leer solo este barcode (se puede repetir); "
                                                      "con uno solo, muestra lo interpretado")
    x.add_argument("--todos", action="store_true", help="Todos los tipos de DIP, no solo los de config")
    x.add_argument("--actualizar", action="store_true", help="Volver a leer los que ya estaban")

    sub.add_parser("referencias", help="Muestra cómo se interpretó la tabla de referencias")
    sub.add_parser("categorias", help="Muestra los tipos de discrepancia y sus reglas "
                                      "(los nombres que acepta --categorias)")

    args = p.parse_args(argv)
    try:
        config = cargar_configuracion(Path(args.config) if args.config else None)
        _modo_prueba(args, config)
        return {"auditar": cmd_auditar, "comparar": cmd_comparar, "benchmark": cmd_benchmark, "anonimizar": cmd_anonimizar,
                "extraer-icam": cmd_extraer_icam, "abrir-icam": cmd_abrir_icam,
                "referencias": cmd_referencias, "categorias": cmd_categorias}[args.comando](args, config)
    except (ErrorCarga, ErrorCatalogo, ErrorAnonimizacion, ErrorExtraccion,
            FileNotFoundError,
            PermissionError) as ex:
        consola.print(f"[bold red]Error:[/] {ex}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
