"""Interfaz de consola.

    python -m dips_audit auditar  "entrada.xlsx" [--hoja HOJA] [--datos-icam ICAM.csv]
    python -m dips_audit abrir-icam
    python -m dips_audit auditar  "entrada.xlsx" --icam
    python -m dips_audit barcode  T40S... [T40S...]      (solo ICAM, resultado en consola)
    python -m dips_audit extraer-icam "entrada.xlsx" | --barcode T40S...
    python -m dips_audit benchmark
    python -m dips_audit anonimizar [--historico ARCHIVO]
    python -m dips_audit auditar  "entrada.xlsx" --categorias "Incorrect DIP Interval" RIR
    python -m dips_audit auditar  "entrada.xlsx" --tipos-dip Others
    python -m dips_audit referencias
    python -m dips_audit categorias
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml
from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .anonimizar import CANTIDAD as CANTIDAD_BENCHMARK
from .anonimizar import SEMILLA as SEMILLA_BENCHMARK
from .anonimizar import ErrorAnonimizacion
from .auditor import CORREGIDO_EN_CIERRE, RAIZ, Auditor, cargar_configuracion
from .benchmark import DATOS as DATOS_BENCHMARK
from .cargador import ErrorCarga
from .extractor_icam import ErrorExtraccion
from .referencias import ErrorCatalogo

consola = Console()
ESTILOS = {
    "POSIBLE DISCREPANCIA": "bold yellow",
    "REVISAR": "bold magenta",
    "SIN FUENTE": "bold cyan",
    "OK": "bold green",
    CORREGIDO_EN_CIERRE: "bold bright_green",
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


def _tabla_hallazgos(resultado) -> Table | None:
    """Tipos de discrepancia: cuántos hallazgos y en cuántos DIPs (% de los auditados)."""
    h = resultado.hallazgos_auditoria_actual()
    h = h[~h["Severidad"].isin(["OBSERVACION", "SIN FUENTE", "CONSULTAR MANUAL"])]
    if h.empty:
        return None
    auditados = int((resultado.filas["RESULTADO"] != "FUERA DE ALCANCE").sum())
    t = Table(title="Posibles discrepancias por tipo")
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


QUE_HACER = {
    "OK": "Completar las verificaciones manuales",
    CORREGIDO_EN_CIERRE: "Completar las verificaciones manuales",
    "POSIBLE DISCREPANCIA": "Confirmar o descartar las discrepancias",
    "REVISAR": "Definir el T/A o RIR según el manual",
    "SIN FUENTE": "Verificar la fuente citada",
    "FUERA DE ALCANCE": "Tipo de DIP excluido",  # se completa con los tipos
}


def _resumen(resultado, tiempos: dict[str, float]) -> Panel:
    """Resumen final de la corrida: cuántos DIPs, qué resultado tuvieron y qué hacer con cada uno."""
    filas = resultado.filas
    conteo = filas["RESULTADO"].value_counts().to_dict()
    en_alcance = filas[filas["RESULTADO"] != "FUERA DE ALCANCE"]
    auditados = len(en_alcance)
    cierre = int((en_alcance["AUDITORÍA"] == "CIERRE").sum())
    h = resultado.hallazgos_auditoria_actual()
    hallazgos = int((~h["Severidad"].isin(["OBSERVACION", "SIN FUENTE", "CONSULTAR MANUAL"])).sum())

    tipos = dict(zip(resultado.lote.datos["fila"], resultado.lote.datos["tipo"]))
    fuera = filas.loc[filas["RESULTADO"] == "FUERA DE ALCANCE", "Fila Excel"].map(tipos)
    detalle_fuera = ", ".join(f"{t} {n}" for t, n in fuera.value_counts().items())

    t = Table(box=box.SIMPLE_HEAD, padding=(0, 1), pad_edge=False)
    t.add_column("Resultado")
    t.add_column("DIPs", justify="right")
    t.add_column("%", justify="right")
    t.add_column("Acción")
    for estado in ("OK", CORREGIDO_EN_CIERRE, "POSIBLE DISCREPANCIA", "REVISAR", "SIN FUENTE",
                   "FUERA DE ALCANCE"):
        n = conteo.get(estado, 0)
        if not n and estado == "FUERA DE ALCANCE":
            continue
        base = len(filas) if estado == "FUERA DE ALCANCE" else auditados
        que_hacer = QUE_HACER[estado]
        if estado == "POSIBLE DISCREPANCIA" and hallazgos:
            que_hacer += f" ({hallazgos} hallazgos)"
        elif estado == "FUERA DE ALCANCE":
            que_hacer = f"Tipo excluido ({detalle_fuera})"
        t.add_row(f"[{ESTILOS[estado]}]{estado}[/]", str(n), f"{n / base:.0%}" if base else "-",
                  que_hacer if n else "")

    t_tiempos = Table(box=box.SIMPLE_HEAD, padding=(0, 1), pad_edge=False, show_footer=True,
                      style="dim", header_style="dim bold", footer_style="dim bold")
    t_tiempos.add_column("Etapa", footer="Total")
    t_tiempos.add_column("Tiempo", justify="right", footer=_duracion(tiempos["Total"]))
    for etapa, segundos in tiempos.items():
        if etapa != "Total":
            t_tiempos.add_row(etapa, _duracion(segundos))
    lineas = [
        f"[bold]DIPs auditados: {auditados}[/] (apertura: {auditados - cierre}, cierre: {cierre}).",
        t,
        t_tiempos,
    ]
    return Panel.fit(Group(*lineas), title="Resumen", border_style="green")


def _vigencia(config, args) -> float | None:
    """Minutos en que un DIP ya leído en ICAM se usa sin volver a leerlo (None con --no-cache)."""
    return None if getattr(args, "no_cache", False) else float(
        config["icam"].get("vigencia_minutos", 60))


def _extraer_icam(config, archivo: Path, hoja: str | None,
                  barcodes: list[str] | None = None, vigencia: float | None = None) -> Path:
    """Lee en ICAM todos los DIPs del Excel de entrada (o `barcodes`), de cualquier tipo. Un
    DIP leído hace menos de `vigencia` minutos no se vuelve a leer: se usa lo guardado."""
    from .cargador import cargar_export
    from .extractor_icam import extraer

    icam = config["icam"]
    if not barcodes:
        barcodes = cargar_export(archivo, hoja).datos["barcode"].tolist()
    consola.print(f"Lectura de ICAM (solo lectura): {len(barcodes)} DIPs, "
                  f"se guardan en {icam['archivo']}."
                  + (f" Los leídos hace menos de {vigencia:g} min se toman de ahí (--no-cache "
                     "para leerlos todos)." if vigencia else ""))
    estado = extraer(barcodes, icam, icam["archivo"], consola.print, vigencia_minutos=vigencia)
    errores = {b: e for b, e in estado.items() if e.startswith("error")}
    leidos = sum(e == "leido" for e in estado.values())
    guardados = sum(e == "guardado" for e in estado.values())
    consola.print(f"[bold green]ICAM:[/] {leidos} leídos, {guardados} de lo guardado, "
                  f"{len(errores)} con error.")
    for b, e in list(errores.items())[:10]:
        consola.print(f"[yellow]{b}:[/] {e}")
    return icam["archivo"]


def cmd_extraer_icam(args, config) -> int:
    archivo = _extraer_icam(config, Path(args.archivo) if args.archivo else None, args.hoja,
                            args.barcode, _vigencia(config, args))
    if args.barcode and len(args.barcode) == 1:
        # Diagnóstico: muestra lo que se interpretó del DIP.
        import json

        from .extractor_icam import leer_registro
        from .icam import leer_ficha
        r = leer_registro(archivo, args.barcode[0])
        if r:
            f = leer_ficha(r["sections"], r["barcode"], r.get("page_title", ""))
            consola.print_json(json.dumps(f.como_dict(), ensure_ascii=False, default=str))
    return 0


def _fecha(valor) -> str:
    return f"{valor:%d-%b-%Y %H:%M}" if valor else "-"


def _ficha_dip(resultado) -> Panel:
    """Un DIP auditado desde ICAM: sus datos, el resultado y los hallazgos."""
    f = resultado.filas.iloc[0]
    dip = resultado.lote.datos.iloc[0]
    estilo = ESTILOS.get(f["RESULTADO"], "bold")
    intervalo = (f"{dip['intervalo']:g} {dip['tipo_intervalo_original']}"
                 if dip["intervalo"] is not None else "-")
    lineas = [
        f"[bold]{f['Fault Name']}[/]",
        f"[bold]Avión:[/] {f['Aircraft'] or '-'}" + (f" ({f['Flota']})" if f["Flota"] else "")
        + f"   [bold]Parent:[/] {dip['parent_assy'] or '-'}",
        f"[bold]Estado:[/] {f['Fault Status']}   [bold]Auditoría:[/] {f['AUDITORÍA']} "
        f"(al {_fecha(f['FECHA AUDITORÍA'])})",
        f"[bold]Intervalo:[/] {intervalo}   [bold]Apertura:[/] {_fecha(dip['found_date'])}   "
        f"[bold]Due:[/] {_fecha(dip['due_date'])}"
        + (f"   [bold]Cierre:[/] {_fecha(dip['complete_date'])}" if dip["complete_date"] else ""),
        f"[bold]Referencia asociada:[/] {f['REFERENCIA ASOCIADA'] or '-'}"
        + (f" ({f['ASOCIACIÓN']})" if f["REFERENCIA ASOCIADA"] else ""),
    ]
    for titulo, columna in (("T/A según referencia", "TA SEGÚN REFERENCIA"),
                            ("Referencia técnica esperada", "REFERENCIA TÉCNICA ESPERADA"),
                            ("Referencia técnica del DIP", "REFERENCIA TÉCNICA DEL DIP"),
                            ("RIR", "RIR EN ICAM"), ("Attachments", "ADJUNTOS EN ICAM"),
                            ("Auditoría manual en ICAM", "AUDITORÍA MANUAL EN ICAM")):
        if f[columna]:
            lineas.append(f"[bold]{titulo}:[/] {f[columna]}")
    lineas += ["", f"[bold]Resultado:[/] [{estilo}]{f['RESULTADO']}[/]"
               + (f"   (apertura: {f['ESTADO APERTURA']}"
                  + (f", cierre: {f['ESTADO CIERRE']}" if f["ESTADO CIERRE"] else "") + ")"
                  if f["ESTADO APERTURA"] else "")]
    for titulo, columna in (("Hallazgos", "HALLAZGOS"), ("Verificación manual", "VERIFICACIÓN MANUAL"),
                            ("Comentario sugerido", "COMENTARIO SUGERIDO")):
        if f[columna]:
            lineas += ["", f"[bold]{titulo}:[/]", f[columna]]
    for nota in resultado.advertencias:
        lineas += ["", f"[yellow]Nota:[/] {nota}"]
    return Panel("\n".join(lineas), title=f"DIP {f['Fault Barcode']}", title_align="left",
                 border_style=estilo.replace("bold ", ""))


def cmd_barcode(args, config) -> int:
    """Audita DIPs solo con ICAM, sin Excel de entrada: lee cada barcode en ICAM y muestra el
    resultado en consola (no se genera ningún archivo de resultado)."""
    from .cargador import lote_desde_icam
    from .extractor_icam import cargar_registros, extraer

    barcodes = list(dict.fromkeys(b.strip().upper() for b in args.barcodes))
    invalidos = [b for b in args.barcodes if not re.fullmatch(r"[A-Z0-9]{8,15}", b.strip().upper())]
    if invalidos:
        consola.print(f"[bold red]Error:[/] {', '.join(invalidos)} no es un barcode ni un "
                      "Excel de entrada que exista.")
        return 1
    if args.datos_icam:
        archivo = Path(args.datos_icam)
    else:
        archivo = config["icam"]["archivo"]
        with consola.status(f"Leyendo en ICAM (solo lectura) {', '.join(barcodes)}..."):
            estado = extraer(barcodes, config["icam"], archivo,
                             vigencia_minutos=_vigencia(config, args))
        errores = {b: e for b, e in estado.items() if e.startswith("error")}
        for b, e in errores.items():
            consola.print(f"[bold red]{b}:[/] no se pudo leer en ICAM ({e}).")
        barcodes = [b for b in barcodes if b not in errores]
    registros = cargar_registros(archivo)
    auditor = Auditor(config, fecha_auditoria=_fecha_hora(args.fecha))
    _filtrar_categorias(args, auditor)
    codigo = 0 if barcodes else 1
    for b in barcodes:
        if b not in registros:
            consola.print(f"[bold red]{b}:[/] no está en {archivo}.")
            codigo = 1
            continue
        consola.print(_ficha_dip(auditor.auditar_lote(lote_desde_icam(registros[b], archivo))))
    return codigo


def cmd_abrir_icam(args, config) -> int:
    from .extractor_icam import abrir_edge, edge_activo

    ya_abierto = edge_activo(int(config["icam"].get("puerto", 9222)))
    abrir_edge(config["icam"])
    consola.print("Edge de ICAM " + ("ya estaba abierto." if ya_abierto else "abierto.")
                  + " Inicie sesión en ICAM en esa ventana.")
    if config.get("referencias_sharepoint"):
        from .fuente_referencias import preparar_referencias

        preparar_referencias(config["referencias_sharepoint"], config["icam"],
                             lambda mensaje: consola.print(mensaje, markup=False),
                             respaldo=config["referencias"],
                             hoja=config.get("hoja_referencias", "References"))
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
    o se pidió --prueba. Los datos de ICAM y los resultados van a pruebas/icam.json y
    pruebas/salida, y los resultados se marcan como PRUEBA, para no mezclarlos con
    auditorías reales."""
    carpeta = Path(config["carpeta_pruebas"]).resolve()
    archivo = getattr(args, "archivo", None)
    dentro = bool(archivo) and Path(archivo).resolve().is_relative_to(carpeta)
    if not (getattr(args, "prueba", False) or dentro):
        return False
    config["modo_prueba"] = True
    config["icam"]["archivo"] = carpeta / "icam.json"
    config["carpeta_salida"] = carpeta / "salida"
    consola.print(Panel.fit(
        "[bold]MODO PRUEBA[/]: datos de prueba, no es una auditoría real.\n"
        f"ICAM: {config['icam']['archivo']}\nResultados: {config['carpeta_salida']} "
        "(con el prefijo PRUEBA_)", border_style="yellow"))
    return True


def _filtrar_tipos_dip(args, config) -> None:
    """--tipos-dip: auditar solo esos tipos de DIP (por defecto, los de config.yaml; vacío = todos)."""
    if args.tipos_dip:
        config["tipos_auditados"] = args.tipos_dip
    tipos = config.get("tipos_auditados")
    consola.print(f"[bold]Tipos de DIP auditados:[/] {', '.join(tipos) if tipos else 'todos'}")


def _avisar_tipos_ausentes(config, lote) -> None:
    """Avisa si un tipo pedido no aparece en el Excel (p. ej. por un error de escritura)."""
    en_archivo = {str(t) for t in lote.datos["tipo"].dropna() if t}
    presentes = {t.upper() for t in en_archivo}
    ausentes = [t for t in config.get("tipos_auditados") or [] if str(t).upper() not in presentes]
    if ausentes:
        consola.print(f"[bold yellow]Aviso:[/] el Excel no tiene DIPs de tipo {', '.join(ausentes)}. "
                      f"Tipos en el archivo: {', '.join(sorted(en_archivo)) or 'ninguno'}.")


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
    if args.icam and not args.datos_icam:
        args.datos_icam = str(_extraer_icam(config, Path(args.archivo), args.hoja,
                                               vigencia=_vigencia(config, args)))
    _filtrar_tipos_dip(args, config)
    auditor = Auditor(config)
    _filtrar_categorias(args, auditor)
    with consola.status("Auditando a la fecha y hora de cada auditoría manual..."):
        c = comparar(auditor, Path(args.archivo), args.hoja, Path(args.datos_icam) if args.datos_icam else None)

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


def _pendientes(args) -> None:
    """--pendientes: auditar solo los DIPs a los que les falta la auditoría manual."""
    from .filtrar import filtrar

    try:
        salida, resumen = filtrar(Path(args.archivo))
    except (ValueError, OSError) as e:
        raise SystemExit(f"--pendientes: {e}")
    detalle = "\n".join(f"{hoja}: {quedan} de {total} filas" for hoja, (quedan, total) in resumen.items())
    consola.print(Panel.fit(f"{detalle}\n[bold]Archivo filtrado:[/] {salida}",
                            title="Solo DIPs pendientes de auditar", border_style="cyan"))
    args.archivo = str(salida)


def cmd_auditar(args, config) -> int:
    inicio = time.perf_counter()
    tiempos: dict[str, float] = {}
    if args.pendientes:
        _pendientes(args)
    if args.icam and not args.datos_icam:
        args.datos_icam = str(_extraer_icam(config, Path(args.archivo), args.hoja,
                                               vigencia=_vigencia(config, args)))
        tiempos["Lectura de ICAM"] = time.perf_counter() - inicio
    marca = time.perf_counter()
    _filtrar_tipos_dip(args, config)
    auditor = Auditor(config, fecha_auditoria=_fecha_hora(args.fecha))
    _filtrar_categorias(args, auditor)
    tiempos["Carga de referencias"] = time.perf_counter() - marca
    marca = time.perf_counter()
    with consola.status("Auditando..."):
        resultado = auditor.auditar_archivo(Path(args.archivo), args.hoja,
                                            Path(args.datos_icam) if args.datos_icam else None)
    tiempos["Auditoría"] = time.perf_counter() - marca
    fecha = auditor.fecha_auditoria

    lote = resultado.lote
    _avisar_tipos_ausentes(config, lote)
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
        elif e.ta_segun_manual:
            intervalo = f"[magenta]REVISAR en el manual[/] ({e.ta_segun_manual})"
        elif e.no_verificable:
            intervalo = "[yellow]manual[/]"
        else:
            intervalo = "; ".join(
                " o ".join(map(str, v.limites)) + (f" [{','.join(v.flotas)}]" if v.flotas else "")
                + (f" RIR {v.rir}" if v.rir else "") for v in e.variantes)
        if e.rir_segun_manual:
            intervalo += f" [magenta]RIR: REVISAR en el manual[/] ({e.rir_segun_manual})"
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


def cmd_validar_reglas(args, config) -> int:
    """Comprueba la sintaxis, los valores y la correspondencia con el código."""
    from .discrepancias import cargar_discrepancias, validar_cobertura

    try:
        reglas = cargar_discrepancias(config["discrepancias"])
        validar_cobertura(reglas)
    except (ValueError, yaml.YAMLError) as ex:
        consola.print(f"[bold red]Reglas inválidas:[/] {ex}")
        return 1
    consola.print(f"[bold green]Reglas válidas:[/] {len(reglas.reglas)} reglas en "
                  f"{len(reglas.tipos)} tipos. Archivo: {config['discrepancias']}")
    return 0


def _argumentos_categorias(p: argparse.ArgumentParser) -> None:
    p.add_argument("-c", "--categorias", nargs="+", metavar="TIPO",
                   help="Revisar solo estos tipos de discrepancia (basta una parte del nombre, "
                        "p. ej. \"technical reference\"). Ver: python -m dips_audit categorias")
    p.add_argument("-e", "--excluir-categorias", nargs="+", metavar="TIPO",
                   help="No revisar estos tipos de discrepancia")
    p.add_argument("-t", "--tipos-dip", nargs="+", metavar="TIPO",
                   help="Auditar solo estos tipos de DIP (columna Type DIP / Area, p. ej. Others). "
                        "Por defecto, todos; los demás quedan FUERA DE ALCANCE")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="dips_audit", description="Auditor preliminar de DIPs")
    p.add_argument("--config", help="Ruta a config.yaml")
    sub = p.add_subparsers(dest="comando", required=True)

    a = sub.add_parser("auditar", help="Audita un Excel de entrada")
    a.add_argument("archivo")
    a.add_argument("-j", "--hoja", help="Hoja a leer (por defecto, la primera con 'Fault Barcode')")
    a.add_argument("--referencias", metavar="XLSX/PDF/URL",
                   help="Tabla de referencias local (XLSX o PDF) o enlace HTTPS de SharePoint")
    a.add_argument("-p", "--prueba", action="store_true", help="Datos de prueba: usa pruebas/icam.json y pruebas/salida y marca los resultados como PRUEBA (automático si el Excel está en pruebas/)")
    a.add_argument("-o", "--salida", help="Ruta del Excel de resultado")
    a.add_argument("-f", "--fecha", help="Fecha y hora de auditoría 'AAAA-MM-DD HH:MM' "
                   "(por defecto, ahora)")
    a.add_argument("-i", "--icam", action="store_true",
                   help="Leer antes en ICAM (solo lectura) todos los DIPs del archivo y usar esos "
                        "datos (sin esta opción, se audita solo con el Excel de entrada)")
    a.add_argument("--no-cache", action="store_true",
                   help="Leer en ICAM todos los DIPs, aunque se hayan leído hace menos de 1 hora")
    a.add_argument("--datos-icam", metavar="RUTA", help="CSV o Excel con datos extraídos de ICAM por barcode "
                                  "(columnas barcode y technical_references; description opcional)")
    a.add_argument("--pendientes", action="store_true",
                   help="Filtrar antes el Excel (copia con ' FILTERED' junto al original) y auditar "
                        "solo los DIPs ACTV sin 'DIP Open Audit User' y COMPLETE sin 'DIP Closed "
                        "Audit User' (sin esta opción, se auditan todos)")
    a.add_argument("-n", "--sin-excel", action="store_true", help="Solo mostrar en consola")
    a.add_argument("--max-filas", type=int, default=40, help="Filas a mostrar en consola")
    _argumentos_categorias(a)

    c = sub.add_parser("comparar", help="Compara el programa con la auditoría manual del Excel "
                                        "(apertura y cierre, a la fecha y hora de cada una)")
    c.add_argument("archivo")
    c.add_argument("-j", "--hoja", help="Hoja a leer")
    c.add_argument("--referencias", metavar="XLSX/PDF/URL",
                   help="Tabla de referencias local o enlace de SharePoint")
    c.add_argument("-p", "--prueba", action="store_true", help="Datos de prueba: usa pruebas/icam.json y pruebas/salida y marca los resultados como PRUEBA (automático si el Excel está en pruebas/)")
    c.add_argument("-i", "--icam", action="store_true",
                   help="Leer antes en ICAM (solo lectura) todos los DIPs del archivo y usar esos "
                        "datos (sin esta opción, se compara solo con el Excel de entrada)")
    c.add_argument("--no-cache", action="store_true",
                   help="Leer en ICAM todos los DIPs, aunque se hayan leído hace menos de 1 hora")
    c.add_argument("--datos-icam", metavar="RUTA", help="Datos de ICAM ya extraídos (p. ej. data/icam.json)")
    _argumentos_categorias(c)

    bm = sub.add_parser("benchmark", help="Mide el programa con los DIPs ya auditados de benchmark/")
    bm.add_argument("--referencias", metavar="XLSX/PDF/URL")

    n = sub.add_parser("anonimizar", help="Crea el Excel del benchmark desde el histórico, "
                                          "sin nombres del personal")
    n.add_argument("--historico", default=str(HISTORICO))
    n.add_argument("--salida", default=str(DATOS_BENCHMARK))
    n.add_argument("--cantidad", type=int, default=CANTIDAD_BENCHMARK,
                   help=f"DIPs de la muestra (por defecto {CANTIDAD_BENCHMARK}; 0 = todos)")
    n.add_argument("--semilla", type=int, default=SEMILLA_BENCHMARK,
                   help="Cambia la muestra; la misma semilla da los mismos DIPs")

    sub.add_parser("abrir-icam", help="Abre Edge, actualiza las referencias y cierra el navegador")
    x = sub.add_parser("extraer-icam", help="Lee en ICAM (solo lectura) los DIPs de un Excel de "
                                             "entrada y los guarda en data/icam.json")
    x.add_argument("archivo", nargs="?", help="Excel de entrada (o use --barcode)")
    x.add_argument("-j", "--hoja", help="Hoja a leer")
    x.add_argument("-p", "--prueba", action="store_true", help="Datos de prueba: usa pruebas/icam.json y pruebas/salida y marca los resultados como PRUEBA (automático si el Excel está en pruebas/)")
    x.add_argument("-b", "--barcode", action="append", help="Leer solo este barcode (se puede repetir); "
                                                      "con uno solo, muestra lo interpretado")
    x.add_argument("--no-cache", action="store_true",
                   help="Leer en ICAM todos los DIPs, aunque se hayan leído hace menos de 1 hora")

    b = sub.add_parser("barcode", help="Audita DIPs por barcode solo con ICAM, sin Excel de "
                                       "entrada; el resultado se muestra en consola")
    b.add_argument("barcodes", nargs="+", metavar="BARCODE")
    b.add_argument("-f", "--fecha", help="Fecha y hora de auditoría 'AAAA-MM-DD HH:MM' "
                   "(por defecto, ahora)")
    b.add_argument("-p", "--prueba", action="store_true", help="Datos de prueba: usa pruebas/icam.json")
    b.add_argument("--datos-icam", metavar="RUTA",
                   help="Usar datos de ICAM ya leídos (p. ej. data/icam.json), sin leer ICAM")
    b.add_argument("--referencias", metavar="XLSX/PDF/URL",
                   help="Tabla de referencias local o enlace de SharePoint")
    b.add_argument("-i", "--icam", action="store_true", help=argparse.SUPPRESS)  # siempre lee ICAM
    b.add_argument("--no-cache", action="store_true",
                   help="Leer en ICAM todos los DIPs, aunque se hayan leído hace menos de 1 hora")
    b.add_argument("-c", "--categorias", nargs="+", metavar="TIPO",
                   help="Revisar solo estos tipos de discrepancia (basta una parte del nombre)")
    b.add_argument("-e", "--excluir-categorias", nargs="+", metavar="TIPO",
                   help="No revisar estos tipos de discrepancia")

    ref = sub.add_parser("referencias", help="Muestra cómo se interpretó la tabla de referencias")
    ref.add_argument("--referencias", metavar="XLSX/PDF/URL",
                     help="Tabla de referencias local o enlace de SharePoint")
    sub.add_parser("categorias", help="Muestra los tipos de discrepancia y sus reglas "
                                      "(los nombres que acepta --categorias)")
    sub.add_parser("validar-reglas", help="Comprueba el archivo de reglas antes de auditar")

    args = p.parse_args(argv)
    config = None
    try:
        config = cargar_configuracion(Path(args.config) if args.config else None)
        prueba = _modo_prueba(args, config)
        if args.comando in {"auditar", "comparar", "barcode", "referencias", "benchmark"}:
            from .fuente_referencias import preparar_referencias

            fuente_explicita = getattr(args, "referencias", None)
            fuente = (fuente_explicita or
                      (config.get("referencias_sharepoint")
                       if not prueba and args.comando != "benchmark" else None) or
                      config["referencias"])
            config["referencias"] = preparar_referencias(
                fuente, config["icam"], lambda mensaje: consola.print(mensaje, markup=False),
                respaldo=config["referencias"] if fuente == config.get("referencias_sharepoint") else None,
                hoja=config.get("hoja_referencias", "References"))
        return {"auditar": cmd_auditar, "comparar": cmd_comparar, "benchmark": cmd_benchmark, "anonimizar": cmd_anonimizar,
                "barcode": cmd_barcode, "extraer-icam": cmd_extraer_icam, "abrir-icam": cmd_abrir_icam,
                "referencias": cmd_referencias, "categorias": cmd_categorias,
                "validar-reglas": cmd_validar_reglas}[args.comando](args, config)
    except (ErrorCarga, ErrorCatalogo, ErrorAnonimizacion, ErrorExtraccion,
            ValueError, yaml.YAMLError,
            FileNotFoundError,
            PermissionError) as ex:
        consola.print(f"[bold red]Error:[/] {ex}")
        return 1
    finally:
        if config is not None:
            _cerrar_edge_pendiente(config)


def _cerrar_edge_pendiente(config) -> None:
    """Si una corrida anterior dejó abierto el Edge de ICAM del programa (o esta no pudo
    cerrarlo), se cierra al terminar. El Edge de uso diario no se toca."""
    from .extractor_icam import cerrar_edge

    perfil = config.get("icam", {}).get("perfil")
    if perfil:
        cerrados = cerrar_edge(perfil)
        if cerrados:
            consola.print(f"[dim]Se cerró el Edge de ICAM que había quedado abierto "
                          f"({cerrados} procesos).[/]")


if __name__ == "__main__":
    sys.exit(main())
