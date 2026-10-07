"""Benchmark del auditor de DIPs.

Con los datos de la carpeta benchmark/ mide:
  1. Auditoría: audita los DIPs de dips_auditados.xlsx y compara el resultado con
     el veredicto del auditor.
  2. Casos: en casos_asociacion.yaml (Fault Names difíciles de asociar, con la
     referencia correcta) mide cuántos quedan bien asociados.
  3. Tiempos de cada etapa.

El resultado se guarda en benchmark/resultados/ (JSON para guardar y comparar,
Markdown para leer) y se compara con benchmark/linea_base.json, que es la copia
de un resultado anterior. Los ajustes que se evalúan están en config/config.yaml.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from . import __version__
from .asociacion import Asociacion, _equivalentes, asociar
from .auditor import RAIZ, Auditor
from .evaluacion import ESTADOS_HUMANOS, INDICADORES, Evaluacion, evaluar, indicadores
from .referencias import normalizar_unidad
from .reglas import SIN_FUENTE

CARPETA = RAIZ / "benchmark"
DATOS = CARPETA / "dips_auditados.xlsx"
CASOS = CARPETA / "casos_asociacion.yaml"
RESULTADOS = CARPETA / "resultados"
LINEA_BASE = CARPETA / "linea_base.json"
FORMATO = 3  # versión del formato del JSON de resultados
TITULO = "Benchmark del auditor de DIPs"

# Indicadores de los casos etiquetados: clave, descripción y si conviene que suba
# (True) o que baje (False).
INDICADORES_CASOS = [
    ("aciertos_finales", "Casos bien resueltos", True),
    ("con_referencia", "Con referencia: asociados a la correcta", True),
    ("sin_referencia", "Sin referencia: no se asocian a ninguna", True),
    ("errores_aceptados", "Referencia equivocada aceptada (el error peligroso)", False),
]
# Cómo se asoció cada DIP a su referencia: nombre y qué pasa con el DIP.
METODOS = {
    "reglas": ("Reglas", "Se aplican todas las verificaciones con esa referencia."),
    "ref_tecnica": ("Referencia técnica",
                    "Se aplican todas las verificaciones con la referencia de su tarea."),
    "descripcion": ("Descripción",
                    "Se aplican todas las verificaciones con la referencia que describe."),
    "sin_referencia": (SIN_FUENTE, f"Queda {SIN_FUENTE}: no está en la tabla de referencias."),
}
_ACUERDO = {"Ambos marcan": "Ambos marcan", "Ambos OK": "Ambos OK",
            "Solo humano": "Solo el auditor marca", "Solo IA": "Solo el programa marca"}


# --------------------------------------------------------------------------
# Casos etiquetados
# --------------------------------------------------------------------------

@dataclass
class Caso:
    grupo: str      # positivo (tiene referencia en la tabla) o negativo (no tiene)
    nombre: str
    intervalo: float
    unidad: str | None
    esperado: str   # ID del catálogo o NINGUNA


def cargar_casos(ruta: Path = CASOS) -> list[Caso]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    casos = []
    for grupo, clave in (("positivo", "positivos"), ("negativo", "negativos")):
        for c in datos[clave]:
            valor, _, unidad = c["intervalo"].partition(" ")
            casos.append(Caso(grupo, c["nombre"], float(valor), normalizar_unidad(unidad),
                              c.get("esperado", "NINGUNA")))
    return casos


def _evaluar_caso(caso: Caso, auditor: Auditor) -> dict:
    catalogo = auditor.catalogo
    a = asociar(caso.nombre, catalogo)
    esperado = catalogo.por_id(caso.esperado)

    def correcto(id_: str | None) -> bool:
        # Elegir una entrada equivalente (mismas verificaciones) no es un error.
        entrada = catalogo.por_id(id_ or "")
        return id_ == caso.esperado or (entrada is not None and esperado is not None
                                        and _equivalentes([entrada, esperado]))

    final = a.entrada.id if a.entrada else "NINGUNA"
    return {
        "grupo": caso.grupo, "fault_name": caso.nombre,
        "intervalo": f"{caso.intervalo:g} {caso.unidad}", "esperado": caso.esperado,
        "final": final, "acierto_final": correcto(final),
        "error_aceptado": a.entrada is not None and not correcto(final),
        "detalle": a.detalle,
    }


def _indicador(aciertos: int, total: int) -> dict:
    return {"aciertos": aciertos, "total": total,
            "pct": round(aciertos / total * 100, 1) if total else 0.0}


def _indicadores_casos(detalle: list[dict]) -> dict[str, dict]:
    pos = [d for d in detalle if d["grupo"] == "positivo"]
    neg = [d for d in detalle if d["grupo"] == "negativo"]
    return {
        "aciertos_finales": _indicador(sum(d["acierto_final"] for d in detalle), len(detalle)),
        "con_referencia": _indicador(sum(d["acierto_final"] for d in pos), len(pos)),
        "sin_referencia": _indicador(sum(d["acierto_final"] for d in neg), len(neg)),
        "errores_aceptados": _indicador(sum(d["error_aceptado"] for d in detalle), len(detalle)),
    }


def duracion(segundos: float | None) -> str:
    if segundos is None:
        return "-"
    if segundos < 60:
        return f"{segundos:.1f} s"
    m, s = divmod(int(round(segundos)), 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"


# --------------------------------------------------------------------------
# Ejecución
# --------------------------------------------------------------------------

def ejecutar(config: dict) -> dict:
    """Audita los DIPs del benchmark, evalúa los casos y devuelve el resultado
    (se guarda como JSON)."""
    inicio = time.perf_counter()
    auditor = Auditor(config)
    tiempos: dict[str, float] = {"preparacion_s": round(time.perf_counter() - inicio, 2)}

    ev = evaluar(auditor, DATOS)
    tiempos["auditoria_s"] = round(ev.metricas["segundos"], 2)

    marca = time.perf_counter()
    casos = cargar_casos()
    detalle = [_evaluar_caso(c, auditor) for c in casos]
    tiempos["casos_s"] = round(time.perf_counter() - marca, 2)
    tiempos["total_s"] = round(time.perf_counter() - inicio, 2)

    catalogo = auditor.catalogo
    humanos = ev.comparacion["ESTADO HUMANO"].value_counts()
    dips = _dips(ev)
    return {
        "formato": FORMATO,
        "fecha": f"{datetime.now():%Y-%m-%d %H:%M}",
        "version_programa": __version__,
        "datos": {
            "archivo": _relativa(DATOS), "dips": len(ev.comparacion),
            "veredictos_auditor": {e: int(humanos.get(e, 0)) for e in ESTADOS_HUMANOS},
            "archivo_casos": _relativa(CASOS), "casos": len(casos),
            "dips_sin_referencia_por_reglas": sum(d["metodo"] == "sin_referencia" for d in dips),
        },
        "configuracion": {
            "tolerancias": config.get("tolerancias", {}),
            "discrepancias": auditor.discrepancias.como_dict(),
            "catalogo": {"archivo": _relativa(config["catalogo"]),
                         "entradas": len(catalogo.entradas)},
            "referencias": {"archivo": _relativa(config["referencias"]),
                            "filas": len(catalogo.referencias)},
        },
        "equipo": equipo(),
        "auditoria": {
            "indicadores": indicadores(ev.metricas),
            "matriz": {h: {p: int(v) for p, v in fila.items()} for h, fila in ev.matriz.iterrows()},
            "por_tema": {t: {"auditor": a, "programa_marca": b, "programa_algun_hallazgo": c}
                         for t, (a, b, c) in ev.metricas["por_tema"].items()},
            "hallazgos_en_ok_del_auditor": ev.metricas["codigos_en_humano_ok"],
            "dips": dips,
        },
        "casos": {"indicadores": _indicadores_casos(detalle), "casos": detalle},
        "tiempos": tiempos,
    }


def _relativa(ruta: Path) -> str:
    try:
        return Path(ruta).resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return str(ruta)


def _texto(valor: object) -> str:
    return "" if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor)


def _metodo(a: Asociacion | None) -> str:
    if a is None or a.metodo == "REGLAS":
        return "reglas"
    return {"REF_TECNICA": "ref_tecnica", "DESCRIPCION": "descripcion"}.get(a.metodo,
                                                                            "sin_referencia")


def _dips(ev: Evaluacion) -> list[dict]:
    salida = []
    for i, f in ev.comparacion.iterrows():
        valor = f["DIP Interval"]
        salida.append({
            "barcode": f["Fault Barcode"], "fault_name": f["Fault Name"],
            "intervalo": f"{valor:g} {_texto(f['Interval Type'])}" if pd.notna(valor) else "",
            "auditor": f["ESTADO HUMANO"], "comentario_auditor": _texto(f["COMENTARIO HUMANO"]),
            "tema_auditor": f["TEMA HUMANO"], "programa": f["ESTADO IA"],
            "acuerdo": _ACUERDO[f["ACUERDO"]],
            "metodo": _metodo(ev.resultado.asociaciones[i]),
            "referencia": f["REFERENCIA ASOCIADA"],
            "hallazgos": [h for h in _texto(f["HALLAZGOS"]).splitlines() if h],
        })
    return salida


def equipo() -> dict:
    """Procesador y RAM del equipo, para comparar tiempos entre PCs."""
    procesador, ram = platform.processor(), None
    if sys.platform == "win32":
        import ctypes
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                procesador = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass

        class _Memoria(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                (n, ctypes.c_ulonglong) for n in ("total", "libre", "pagina", "pagina_libre",
                                                  "virtual", "virtual_libre", "extendida")]
        mem = _Memoria()
        mem.dwLength = ctypes.sizeof(mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            ram = mem.total / 1024 ** 3
    else:
        try:
            ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
        except (ValueError, OSError, AttributeError):
            pass
    return {"procesador": procesador or "?", "hilos": os.cpu_count(),
            "ram_gb": round(ram, 1) if ram else None, "sistema": platform.platform(terse=True)}


# --------------------------------------------------------------------------
# Resultados: archivos, línea base y comparación
# --------------------------------------------------------------------------

def _leer(ruta: Path) -> dict | None:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) and datos.get("formato") == FORMATO else None


def cargar_linea_base() -> dict | None:
    return _leer(LINEA_BASE)


def guardar(resultado: dict, base: dict | None, carpeta: Path | None = None) -> tuple[Path, Path]:
    """Guarda el resultado en JSON (para guardar) y en Markdown (para leer)."""
    carpeta = carpeta or RESULTADOS
    carpeta.mkdir(parents=True, exist_ok=True)
    nombre = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    ruta_json, ruta_md = carpeta / f"{nombre}.json", carpeta / f"{nombre}.md"
    ruta_json.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    ruta_md.write_text(a_markdown(resultado, base, ruta_json.name), encoding="utf-8")
    return ruta_json, ruta_md


def comparable(resultado: dict, base: dict | None) -> str:
    """Motivo por el que la línea base no se puede comparar ("" si se puede)."""
    if base is None:
        return "No hay línea base."
    antes, ahora = base["datos"], resultado["datos"]
    if (antes["dips"], antes["casos"]) != (ahora["dips"], ahora["casos"]):
        return (f"La línea base se midió con otros datos ({antes['dips']} DIPs y "
                f"{antes['casos']} casos; ahora {ahora['dips']} y {ahora['casos']}).")
    return ""


def _grupos(resultado: dict, base: dict | None):
    """(grupo, clave, descripción, sube, actual, previo) de cada indicador que se compara."""
    usar_base = (base if not comparable(resultado, base) else None) or {}
    previos = usar_base.get("auditoria", {}).get("indicadores", {})
    for clave, descripcion, _, sube in INDICADORES:
        yield ("auditoria", clave, descripcion, sube,
               resultado["auditoria"]["indicadores"][clave], previos.get(clave))
    actuales = resultado["casos"]["indicadores"]
    previos = usar_base.get("casos", {}).get("indicadores", {})
    for clave, descripcion, sube in INDICADORES_CASOS:
        yield "casos", clave, descripcion, sube, actuales[clave], previos.get(clave)


def _peor(actual: dict, previo: dict | None, sube: bool) -> bool:
    if not previo:
        return False
    cambio = actual["pct"] - previo["pct"]
    return cambio < 0 if sube else cambio > 0


def empeoraron(resultado: dict, base: dict | None) -> list[str]:
    """Indicadores que quedaron peor que en la línea base."""
    return [d for _, _, d, sube, actual, previo in _grupos(resultado, base)
            if _peor(actual, previo, sube)]


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def _celda(valor: object) -> str:
    return str(valor).replace("|", "\\|").replace("\n", " ").strip()


def _tabla(encabezado: list[str], filas: list[list], derecha: set[int] = frozenset()) -> str:
    lineas = ["| " + " | ".join(encabezado) + " |",
              "| " + " | ".join("---:" if i in derecha else "---"
                                for i in range(len(encabezado))) + " |"]
    lineas += ["| " + " | ".join(_celda(c) for c in fila) + " |" for fila in filas]
    return "\n".join(lineas)


def _de(ind: dict) -> str:
    return f"{ind['aciertos']} de {ind['total']} ({ind['pct']:.0f}%)"


def _cambio(actual: dict, previo: dict | None, sube: bool) -> str:
    if not previo:
        return "-"
    d = actual["pct"] - previo["pct"]
    if abs(d) < 0.05:
        return "="
    return f"{d:+.1f} pp" + (" (peor)" if _peor(actual, previo, sube) else " (mejor)")


def _fecha_legible(fecha: str) -> str:
    return datetime.strptime(fecha, "%Y-%m-%d %H:%M").strftime("%d-%m-%Y %H:%M")


def como_se_audita(r: dict) -> str:
    """Explicación del método. Se muestra en la consola y queda en el Markdown."""
    datos, c = r["datos"], r["configuracion"]
    v = datos["veredictos_auditor"]
    return "\n".join([
        f"1. **Datos.** {datos['dips']} DIPs Others ya auditados por personas (jul-ago 2026): "
        f"{v['OK']} OK y {v['DISCREPANCIA']} con discrepancia, en `{datos['archivo']}` "
        "(copia anónima). Son los datos del Excel de entrada del día de la auditoría: en ICAM "
        "esos DIPs ya están corregidos, así que no se completan desde ICAM. Solo entran DIPs "
        "con intervalo y tipo de intervalo, y cada uno se audita con la fecha en que lo "
        "auditó la persona.",
        f"2. **Reglas.** Asocian cada DIP a una referencia de `{c['referencias']['archivo']}` "
        f"por palabras clave (`{c['catalogo']['archivo']}`) y verifican intervalo, tipo de "
        "intervalo, parent assy, due date, vencidos, duplicados, S/N y deferral reference. "
        f"Los DIPs que las reglas no asocian ({datos['dips_sin_referencia_por_reglas']} de "
        f"{datos['dips']}) quedan {SIN_FUENTE}: no se comparan con una referencia de la tabla.",
        "3. **Comparación.** El auditor da OK o discrepancia. El programa marca un DIP si lo "
        f"deja en POSIBLE DISCREPANCIA ({SIN_FUENTE} no cuenta como marca).",
        f"4. **Casos.** {datos['casos']} Fault Names difíciles de asociar (errores de "
        "escritura, abreviaturas, español, sinónimos), con la referencia correcta, en "
        f"`{datos['archivo_casos']}`. Miden cuántos asocian bien las reglas y que no acepten "
        "una referencia equivocada.",
    ])


def a_markdown(r: dict, base: dict | None, nombre_json: str = "", completo: bool = True) -> str:
    """Reporte legible. `completo=False` es la versión de la consola: sin el método (ya se
    mostró antes), sin las reglas y sin el detalle por DIP."""
    partes = [
        f"# {TITULO}" if completo else "# Resultado del benchmark",
        f"{_fecha_legible(r['fecha'])}, programa v{r['version_programa']}, "
        f"duración {duracion(r['tiempos']['total_s'])}",
    ]
    partes += _resumen(r, base)
    if completo:
        partes += ["## Cómo se audita", como_se_audita(r)]
    partes += _seccion_auditor(r, base)
    partes += _seccion_metodos(r)
    partes += _seccion_casos(r, base)
    partes += _seccion_tiempos(r, base)
    partes += _seccion_configuracion(r, completo)
    if completo:
        partes += _desacuerdos(r["auditoria"]["dips"])
        partes += ["## Línea base",
                   f"Este resultado está en `{nombre_json or 'el JSON de la misma carpeta'}`. "
                   "Si un cambio es intencional y el resultado es el nuevo punto de "
                   "comparación, copie ese JSON sobre `benchmark/linea_base.json`."]
    return "\n\n".join(p for p in partes if p) + "\n"


def _resumen(r: dict, base: dict | None) -> list[str]:
    ind = r["auditoria"]["indicadores"]
    ci = r["casos"]["indicadores"]
    resueltos = (f"{_de(ci['aciertos_finales'])}, referencias equivocadas aceptadas: "
                 f"{ci['errores_aceptados']['aciertos']}")
    nota, peores = comparable(r, base), empeoraron(r, base)
    if nota:
        frente_a_base = nota
    elif peores:
        frente_a_base = "**Empeoró:** " + "; ".join(peores)
    else:
        frente_a_base = f"Ningún indicador empeoró (línea base del {_fecha_legible(base['fecha'])})"
    return ["## Resumen", _tabla(["Indicador", "Resultado"], [
        ["DIPs auditados", f"{r['datos']['dips']} Others"],
        ["Coincide con el auditor (OK o discrepancia)", _de(ind["coincidencia"])],
        ["Discrepancias del auditor que el programa marca", _de(ind["discrepancias_detectadas"])],
        ["OK del auditor que el programa marca con posible discrepancia",
         _de(ind["falsas_discrepancias"])],
        ["Casos difíciles de asociar: bien resueltos", resueltos],
        ["Tiempo total", duracion(r["tiempos"]["total_s"])],
        ["Frente a la línea base", frente_a_base],
    ])]


def _tabla_indicadores(r: dict, base: dict | None, grupo: str) -> str:
    return _tabla(
        ["Indicador", "Actual", "Línea base", "Cambio"],
        [[d, _de(a), f"{p['pct']:.0f}%" if p else "-", _cambio(a, p, sube)]
         for g, clave, d, sube, a, p in _grupos(r, base) if g == grupo],
        {1, 2, 3})


def _seccion_auditor(r: dict, base: dict | None) -> list[str]:
    aud = r["auditoria"]
    columnas = list(next(iter(aud["matriz"].values())))
    partes = [
        "## 1. Resultado frente al auditor",
        _tabla_indicadores(r, base, "auditoria"),
        "**Matriz** (filas: auditor; columnas: programa)",
        _tabla(["Auditor \\ Programa"] + [c for c in columnas],
               [[h] + [fila[c] for c in columnas]
                for h, fila in aud["matriz"].items()], set(range(1, len(columnas) + 1))),
    ]
    if aud["por_tema"]:
        partes += ["**Discrepancias del auditor según el tema de su comentario**", _tabla(
            ["Tema", "Auditor", "El programa marca", "El programa tiene algún hallazgo"],
            [[tema, v["auditor"], v["programa_marca"], v["programa_algun_hallazgo"]]
             for tema, v in sorted(aud["por_tema"].items(), key=lambda x: -x[1]["auditor"])],
            {1, 2, 3})]
    if aud["hallazgos_en_ok_del_auditor"]:
        partes.append("Hallazgos del programa en DIPs que el auditor dio OK: " + ", ".join(
            f"`{k}` ({v})" for k, v in aud["hallazgos_en_ok_del_auditor"].items()) + ".")
    return partes


def _seccion_metodos(r: dict) -> list[str]:
    dips = r["auditoria"]["dips"]
    conteo = {k: sum(d["metodo"] == k for d in dips) for k in METODOS}
    partes = ["## 2. Cómo se asoció cada DIP a su referencia", _tabla(
        ["Método", "DIPs", "Qué pasa con el DIP"],
        [[METODOS[k][0], n, METODOS[k][1]] for k, n in conteo.items() if n], {1})]
    sin_reglas = [d for d in dips if d["metodo"] != "reglas"]
    if sin_reglas:
        partes += ["**DIPs que no asocian las reglas**", _tabla(
            ["Barcode", "Fault Name", "Intervalo", "Programa", "Auditor"],
            [[d["barcode"], d["fault_name"][:60], d["intervalo"],
              d["programa"], d["auditor"]]
             for d in sin_reglas])]
    return partes


def _seccion_casos(r: dict, base: dict | None) -> list[str]:
    detalle = r["casos"]["casos"]
    positivos = sum(d["grupo"] == "positivo" for d in detalle)
    partes = [
        "## 3. Casos difíciles de asociar",
        f"{len(detalle)} Fault Names con errores de escritura, abreviaturas, español o sinónimos: "
        f"{positivos} con referencia en la tabla y {len(detalle) - positivos} sin referencia. "
        f"Los que las reglas no asocian quedan {SIN_FUENTE}.",
        _tabla_indicadores(r, base, "casos"),
    ]
    aceptados = [d for d in detalle if d["error_aceptado"]]
    if aceptados:
        partes += ["**Referencias equivocadas aceptadas**", _tabla(
            ["Fault Name", "Intervalo", "Esperado", "Asociado"],
            [[d["fault_name"], d["intervalo"], d["esperado"], d["final"]] for d in aceptados])]
    return partes


def _seccion_tiempos(r: dict, base: dict | None) -> list[str]:
    t, n = r["tiempos"], r["datos"]
    b_t = (base if not comparable(r, base) else {}).get("tiempos", {})
    filas = [
        ["Preparación: lectura de referencias y catálogo", duracion(t["preparacion_s"]),
         duracion(b_t.get("preparacion_s"))],
        [f"Auditoría de {n['dips']} DIPs", duracion(t["auditoria_s"]),
         duracion(b_t.get("auditoria_s"))],
        [f"Casos ({n['casos']})", duracion(t["casos_s"]), duracion(b_t.get("casos_s"))],
        ["**Total**", f"**{duracion(t['total_s'])}**", duracion(b_t.get("total_s"))],
    ]
    e = r["equipo"]
    return ["## 4. Tiempos", _tabla(["Etapa", "Tiempo", "Línea base"], filas, {1, 2}),
            f"Equipo: {e['procesador']}, {e['hilos']} hilos, "
            f"{e['ram_gb'] or '?'} GB de RAM, {e['sistema']}."]


def _seccion_configuracion(r: dict, completo: bool) -> list[str]:
    c = r["configuracion"]
    tol = c["tolerancias"]

    def si_no(v: object) -> str:
        return "sí" if v else "no"
    filas = [
        ["Tolerancia en días", tol.get("dias"), "tolerancias.dias"],
        ["Días por mes", f"{tol.get('meses_min')}-{tol.get('meses_max')}",
         "tolerancias.meses_min, tolerancias.meses_max"],
        ["Catálogo Others (palabras clave)", f"{c['catalogo']['entradas']} entradas",
         c["catalogo"]["archivo"]],
        ["Tabla de referencias", f"{c['referencias']['filas']} filas",
         c["referencias"]["archivo"]],
    ]
    partes = [
        "## 5. Configuración usada",
        "Se cambia en `config/config.yaml`. Después de cambiarla, ejecute el benchmark y "
        "compare con la línea base.",
        _tabla(["Parámetro", "Valor", "Clave en config.yaml"], filas, {1}),
    ]
    if completo:
        partes += ["**Tipos de discrepancia y reglas** (`config/discrepancias.yaml`)", _tabla(
            ["Tipo", "Regla", "Activa", "Severidad"],
            [[tipo, f"`{codigo}`", si_no(t["activo"] and regla["activa"]), regla["severidad"]]
             for tipo, t in c["discrepancias"].items()
             for codigo, regla in t["reglas"].items()])]
    return partes


def _desacuerdos(dips: list[dict]) -> list[str]:
    partes = ["## 6. Desacuerdos con el auditor"]
    for acuerdo in ("Solo el programa marca", "Solo el auditor marca"):
        grupo = [d for d in dips if d["acuerdo"] == acuerdo]
        partes.append(f"### {acuerdo} ({len(grupo)})")
        for d in grupo:
            referencia = d["referencia"] or "sin referencia"
            lineas = [
                f"**{d['barcode']}**: {d['fault_name']}",
                f"- Intervalo: {d['intervalo'] or 'sin dato'}. Referencia: {referencia} "
                f"({METODOS[d['metodo']][0].lower()})",
                f"- Auditor: **{d['auditor']}**"
                + (f". {d['comentario_auditor']}" if d["comentario_auditor"] else ""),
                f"- Programa: **{d['programa']}**",
            ] + [f"  - {h}" for h in d["hallazgos"]]
            partes.append("\n".join(lineas))
    return partes
