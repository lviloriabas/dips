"""Benchmark del auditor de DIPs, en dos modos que se corren y se reportan por separado.

  sin_modelo: solo reglas, como `auditar` sin --llm. Tarda unos segundos.
  con_modelo: reglas + modelo local, como `auditar --llm`. Necesita Ollama.

Con los datos de la carpeta benchmark/, cada modo mide:
  1. Auditoría: audita los DIPs de dips_auditados.xlsx y compara el resultado con
     el veredicto del auditor.
  2. Casos: en casos_modelo_local.yaml (Fault Names que las reglas no resuelven,
     con la referencia correcta) mide cuántos quedan bien asociados.
  3. Tiempos de cada etapa y, con modelo, el costo de cada consulta (tokens, RAM).

El resultado se guarda en benchmark/resultados/<modo>/ (JSON para guardar y
comparar, Markdown para leer) y se compara con benchmark/linea_base_<modo>.json,
que es la copia de un resultado anterior del mismo modo. Los ajustes que se
evalúan están en config/config.yaml.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from . import __version__
from .asociacion import Asociacion, _equivalentes, asociar
from .auditor import RAIZ, Auditor
from .evaluacion import INDICADORES, Evaluacion, evaluar, indicadores
from .llm import ClienteOllama
from .referencias import normalizar_unidad

CARPETA = RAIZ / "benchmark"
DATOS = CARPETA / "dips_auditados.xlsx"
CASOS = CARPETA / "casos_modelo_local.yaml"
RESULTADOS = CARPETA / "resultados"  # una subcarpeta por modo
FORMATO = 2  # versión del formato del JSON de resultados

# Modos del benchmark: título y línea de comando que lo corre.
MODOS = {
    "sin_modelo": ("Sin modelo local (solo reglas)", "benchmark_sin_modelo.bat"),
    "con_modelo": ("Con modelo local (reglas + modelo)", "benchmark_con_modelo.bat"),
}

# Indicadores de los casos etiquetados: clave, descripción y si conviene que suba
# (True) o que baje (False). El último solo existe con modelo.
INDICADORES_CASOS = [
    ("aciertos_finales", "Casos bien resueltos", True),
    ("con_referencia", "Con referencia: asociados a la correcta", True),
    ("sin_referencia", "Sin referencia: no se asocian a ninguna", True),
    ("errores_aceptados", "Referencia equivocada aceptada (el error peligroso)", False),
    ("aciertos_modelo", "Respuesta del modelo correcta, antes de validar", True),
]
# Cómo se asoció cada DIP a su referencia: nombre, nombre corto y qué pasa con el DIP.
METODOS = {
    "reglas": ("Reglas", "reglas", "Se aplican todas las verificaciones con esa referencia."),
    "modelo_aceptada": ("Modelo local: sugerencia aceptada", "aceptada",
                        "Pasó la validación. Se verifica con esa referencia y queda en REVISAR."),
    "modelo_descartada": ("Modelo local: sugerencia descartada", "descartada",
                          "No pasó la validación. Queda en REVISAR sin referencia."),
    "modelo_ninguna": ("Modelo local: respondió NINGUNA", "NINGUNA",
                       "Queda en REVISAR sin referencia."),
    "sin_referencia": ("Sin referencia (sin modelo)", "-",
                       "Queda en REVISAR sin referencia: el auditor la busca."),
}
_ACUERDO = {"Ambos marcan": "Ambos marcan", "Ambos OK": "Ambos OK",
            "Solo humano": "Solo el auditor marca", "Solo IA": "Solo el programa marca"}
_CORTO = {"DISCREPANCIA CRÍTICA": "CRÍTICA", "DISCREPANCIA NO CRÍTICA": "NO CRÍTICA"}


# --------------------------------------------------------------------------
# Casos etiquetados del modelo local
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


def _evaluar_caso(caso: Caso, auditor: Auditor, cliente) -> dict:
    catalogo = auditor.catalogo
    inicio = time.perf_counter()
    a = asociar(caso.nombre, catalogo, cliente, caso.intervalo, caso.unidad, auditor.parametros)
    segundos = time.perf_counter() - inicio
    consultado = cliente is not None and a.metodo != "REGLAS"
    esperado = catalogo.por_id(caso.esperado)

    def correcto(id_: str | None) -> bool:
        # Elegir una entrada equivalente (mismas verificaciones) no es un error.
        entrada = catalogo.por_id(id_ or "")
        return id_ == caso.esperado or (entrada is not None and esperado is not None
                                        and _equivalentes([entrada, esperado]))

    final = a.entrada.id if a.entrada else "NINGUNA"
    respuesta = (a.propuesta or "NINGUNA") if consultado else "(reglas)"
    return {
        "grupo": caso.grupo, "fault_name": caso.nombre,
        "intervalo": f"{caso.intervalo:g} {caso.unidad}", "esperado": caso.esperado,
        "respuesta_modelo": respuesta, "final": final,
        "acierto_modelo": correcto(a.propuesta or "NINGUNA") if consultado else None,
        "acierto_final": correcto(final),
        "error_aceptado": a.entrada is not None and not correcto(final),
        "segundos": round(segundos, 2), "detalle": a.detalle,
    }


class CandidatoMasParecido:
    """Alternativa sin modelo: elige siempre el candidato más parecido al Fault Name.

    Pasa por la misma validación que el modelo. Solo se mide en el modo con modelo,
    como comparación; el programa no la usa.
    """

    def elegir_categoria(self, nombre, candidatos, intervalo=""):
        return (candidatos[0] if candidatos else None), ""


def _indicador(aciertos: int, total: int) -> dict:
    return {"aciertos": aciertos, "total": total,
            "pct": round(aciertos / total * 100, 1) if total else 0.0}


def _indicadores_casos(detalle: list[dict], con_modelo: bool) -> dict[str, dict]:
    pos = [d for d in detalle if d["grupo"] == "positivo"]
    neg = [d for d in detalle if d["grupo"] == "negativo"]
    salida = {
        "aciertos_finales": _indicador(sum(d["acierto_final"] for d in detalle), len(detalle)),
        "con_referencia": _indicador(sum(d["acierto_final"] for d in pos), len(pos)),
        "sin_referencia": _indicador(sum(d["acierto_final"] for d in neg), len(neg)),
        "errores_aceptados": _indicador(sum(d["error_aceptado"] for d in detalle), len(detalle)),
    }
    if con_modelo:
        consultados = [d for d in detalle if d["acierto_modelo"] is not None]
        salida["aciertos_modelo"] = _indicador(sum(d["acierto_modelo"] for d in consultados),
                                               len(consultados))
    return salida


# --------------------------------------------------------------------------
# Avance: tiempo transcurrido y estimación de lo que falta
# --------------------------------------------------------------------------

class Avance:
    """Tiempo transcurrido y estimación de lo que falta.

    Casi todo el tiempo se va en consultar al modelo local (decenas de segundos por
    consulta en CPU); las reglas tardan menos de un segundo en total. Por eso lo que
    falta se estima como consultas pendientes x segundos promedio por consulta.
    Antes de la primera consulta se usa el promedio de una corrida anterior.
    """

    def __init__(self, al_avanzar: Callable[[str], None] | None = None):
        self.inicio = time.perf_counter()
        self.etapa = "Preparando"
        self.consultando = ""        # Fault Name que se le está preguntando al modelo
        self.previstas = 0           # DIPs y casos que requieren el modelo
        self.hechas = 0
        self.segundos_modelo = 0.0   # suma del tiempo de las consultas hechas
        self.referencia: float | None = None  # segundos por consulta de una corrida anterior
        self.carga_pendiente = 0.0   # estimado de la carga del modelo, hasta que ocurre
        self.al_avanzar = al_avanzar  # recibe una línea de texto (consola sin animación)

    @property
    def transcurrido(self) -> float:
        return time.perf_counter() - self.inicio

    @property
    def por_consulta(self) -> float | None:
        return self.segundos_modelo / self.hechas if self.hechas else self.referencia

    @property
    def faltante(self) -> float | None:
        pendientes = max(self.previstas - self.hechas, 0)
        if not pendientes:
            return self.carga_pendiente
        if self.por_consulta is None:
            return None
        return pendientes * self.por_consulta + self.carga_pendiente

    @property
    def total(self) -> float | None:
        faltante = self.faltante
        return None if faltante is None else self.transcurrido + faltante

    def linea(self) -> str:
        return (f"[{self.hechas}/{self.previstas}] transcurrido {reloj(self.transcurrido)} · "
                f"falta {aprox(self.faltante)} · total estimado {aprox(self.total)}")

    def nueva_etapa(self, etapa: str) -> None:
        self.etapa = etapa
        self.consultando = ""
        if self.al_avanzar:
            self.al_avanzar(f"{etapa} · {self.linea()}")

    def hecha(self, segundos: float) -> None:
        """Terminó un DIP o caso que requería el modelo; `segundos` = tiempo de sus consultas."""
        self.hechas += 1
        self.segundos_modelo += segundos
        if self.al_avanzar:
            self.al_avanzar(f"  {self.linea()} · {self.consultando[:60]} ({segundos:.1f} s)")
        self.consultando = ""


class _Observado:
    """Envuelve el cliente del modelo para mostrar qué Fault Name se está consultando."""

    def __init__(self, cliente: ClienteOllama, avance: Avance):
        self._cliente = cliente
        self._avance = avance

    def elegir_categoria(self, nombre, candidatos, intervalo=""):
        self._avance.consultando = nombre
        return self._cliente.elegir_categoria(nombre, candidatos, intervalo)

    def __getattr__(self, nombre):
        return getattr(self._cliente, nombre)


@contextmanager
def sin_suspension():
    """Evita que Windows apague la pantalla o se suspenda mientras corre el benchmark.

    En suspensión el modelo se detiene o se vuelve muy lento: las consultas exceden el
    tiempo máximo y los tiempos medidos no sirven.
    """
    if sys.platform != "win32":
        yield
        return
    import ctypes
    continuo, sistema, pantalla = 0x80000000, 0x00000001, 0x00000002
    kernel32 = ctypes.windll.kernel32
    kernel32.SetThreadExecutionState(continuo | sistema | pantalla)
    try:
        yield
    finally:
        kernel32.SetThreadExecutionState(continuo)


def reloj(segundos: float | None) -> str:
    if segundos is None:
        return "calculando..."
    s = int(round(segundos))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def aprox(segundos: float | None) -> str:
    return reloj(segundos) if segundos is None else "~" + reloj(segundos)


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
# Plan y ejecución
# --------------------------------------------------------------------------

@dataclass
class Plan:
    config: dict
    auditor: Auditor
    reglas: Evaluacion           # auditoría solo con reglas (tarda menos de un segundo)
    casos: list[Caso]
    llm: ClienteOllama | None    # None = modo sin modelo
    dips_con_modelo: set[int]    # DIPs que las reglas no asocian: se consultan al modelo
    casos_con_modelo: set[int]
    anterior: dict | None        # último resultado con el mismo modelo (para estimar)

    @property
    def modo(self) -> str:
        return "con_modelo" if self.llm else "sin_modelo"

    @property
    def consultas_previstas(self) -> int:
        return len(self.dips_con_modelo) + len(self.casos_con_modelo) if self.llm else 0

    @property
    def estimado(self) -> float | None:
        """Duración estimada de todo el benchmark, según una corrida anterior."""
        if not self.llm:
            return 0.0
        if not self.anterior:
            return None
        return (self.consultas_previstas * self.anterior["costo_modelo"]["s_por_consulta"]
                + (self.anterior["tiempos"].get("carga_modelo_s") or 0))


def preparar(config: dict, llm: ClienteOllama | None = None) -> Plan:
    """Lee los datos, audita solo con reglas y cuenta cuántas consultas al modelo habrá.

    Sin `llm` el benchmark es el del modo sin modelo."""
    auditor = Auditor(config)
    reglas = evaluar(auditor, DATOS)
    casos = cargar_casos()
    dips_con_modelo = {i for i, a in enumerate(reglas.resultado.asociaciones)
                       if a is not None and a.metodo != "REGLAS"}
    casos_con_modelo = {i for i, c in enumerate(casos)
                        if asociar(c.nombre, auditor.catalogo, None, c.intervalo, c.unidad,
                                   auditor.parametros).metodo != "REGLAS"}
    return Plan(config, auditor, reglas, casos, llm, dips_con_modelo, casos_con_modelo,
                _anterior(llm.modelo) if llm else None)


def descripcion(plan: Plan) -> dict:
    """Qué se mide y con qué configuración (se conoce antes de empezar)."""
    config, catalogo = plan.config, plan.auditor.catalogo
    humanos = plan.reglas.comparacion["ESTADO HUMANO"].value_counts()
    return {
        "formato": FORMATO,
        "modo": plan.modo,
        "fecha": f"{datetime.now():%Y-%m-%d %H:%M}",
        "version_programa": __version__,
        "datos": {
            "archivo": _relativa(DATOS), "dips": len(plan.reglas.comparacion),
            "veredictos_auditor": {e: int(humanos.get(e, 0)) for e in
                                   ["OK", "DISCREPANCIA NO CRÍTICA", "DISCREPANCIA CRÍTICA"]},
            "archivo_casos": _relativa(CASOS), "casos": len(plan.casos),
            "dips_sin_referencia_por_reglas": len(plan.dips_con_modelo),
        },
        "modelo_local": plan.llm.modelo if plan.llm else None,
        "configuracion": {
            **({"llm": {k: v for k, v in config["llm"].items() if k != "url"}}
               if plan.llm else {}),
            "tolerancias": config.get("tolerancias", {}),
            "severidades": config.get("severidades", {}),
            "catalogo": {"archivo": _relativa(config["catalogo"]),
                         "entradas": len(catalogo.entradas)},
            "referencias": {"archivo": _relativa(config["referencias"]),
                            "filas": len(catalogo.referencias)},
        },
        "equipo": equipo(),
    }


def texto_plan(plan: Plan) -> str:
    """Cuántas consultas al modelo habrá y cuánto se estima que tarde todo."""
    if not plan.llm:
        return "**Plan:** solo reglas, sin consultas al modelo; tarda unos segundos."
    texto = (f"**Plan:** {plan.consultas_previstas} consultas al modelo "
             f"({len(plan.dips_con_modelo)} DIPs de la auditoría y "
             f"{len(plan.casos_con_modelo)} casos). ")
    if plan.anterior:
        return texto + (f"Tiempo estimado: {aprox(plan.estimado)}, con "
                        f"{plan.anterior['costo_modelo']['s_por_consulta']:.1f} s por consulta "
                        f"como en la corrida del {_fecha_legible(plan.anterior['fecha'])}.")
    return texto + "El tiempo total se estima después de la primera consulta."


def ejecutar(plan: Plan, avance: Avance) -> dict:
    """Corre las etapas del modo del plan y devuelve el resultado (se guarda como JSON)."""
    llm = plan.llm
    tiempos: dict[str, float | int | None] = {"preparacion_s": round(avance.transcurrido, 2)}
    avance.previstas = plan.consultas_previstas
    if plan.anterior:
        avance.referencia = plan.anterior["costo_modelo"]["s_por_consulta"]
        avance.carga_pendiente = plan.anterior["tiempos"].get("carga_modelo_s") or 0.0
    memoria = None
    if llm:
        avance.nueva_etapa("Cargando el modelo local en memoria")
        llm.descargar_de_memoria()  # para medir la carga desde cero
        tiempos["carga_modelo_s"] = round(llm.cargar(), 2)
        avance.carga_pendiente = 0.0
        memoria = llm.memoria()

    # Auditoría de los DIPs. Sin modelo, vale la que ya se hizo solo con reglas.
    n = len(plan.reglas.comparacion)
    ev = plan.reglas
    inicio = time.perf_counter()
    if llm:
        avance.nueva_etapa(f"Auditoría de {n} DIPs (reglas + modelo local)")
        vistas = [0]

        def progreso(i: int) -> None:
            if i in plan.dips_con_modelo:
                nuevas = llm.mediciones[vistas[0]:]
                vistas[0] = len(llm.mediciones)
                avance.hecha(sum(m.segundos for m in nuevas))

        plan.auditor.llm = _Observado(llm, avance)
        try:
            ev = evaluar(plan.auditor, DATOS, progreso=progreso)
        finally:
            plan.auditor.llm = None
        tiempos["auditoria_s"] = round(time.perf_counter() - inicio, 2)
    else:
        tiempos["auditoria_s"] = round(plan.reglas.metricas["segundos"], 2)
    tiempos["auditoria_consultas"] = llm.consultas if llm else 0

    # Casos etiquetados: Fault Names que las reglas no resuelven.
    inicio = time.perf_counter()
    if llm:
        avance.nueva_etapa(f"Modelo local: {len(plan.casos)} casos de asociación")
        antes = llm.consultas
        observado = _Observado(llm, avance)
        detalle = []
        for i, caso in enumerate(plan.casos):
            previas = llm.consultas
            detalle.append(_evaluar_caso(caso, plan.auditor, observado))
            if i in plan.casos_con_modelo:
                avance.hecha(sum(m.segundos for m in llm.mediciones[previas:]))
        tiempos["casos_consultas"] = llm.consultas - antes
        llm.descargar_de_memoria()
    else:
        detalle = [_evaluar_caso(c, plan.auditor, None) for c in plan.casos]
    tiempos["casos_s"] = round(time.perf_counter() - inicio, 2)
    casos = {"indicadores": _indicadores_casos(detalle, llm is not None)}
    if llm:
        # Qué pasaría con los mismos casos sin el modelo (se calcula al instante).
        casos["comparacion"] = {
            "solo_reglas": _indicadores_casos(
                [_evaluar_caso(c, plan.auditor, None) for c in plan.casos], False),
            "mas_parecido": _indicadores_casos(
                [_evaluar_caso(c, plan.auditor, CandidatoMasParecido()) for c in plan.casos],
                False),
        }
    casos["casos"] = detalle
    tiempos["total_s"] = round(avance.transcurrido, 2)

    auditoria = {"indicadores": indicadores(ev.metricas)}
    if llm:
        auditoria["indicadores_solo_reglas"] = indicadores(plan.reglas.metricas)
    return {
        **descripcion(plan),
        "auditoria": {
            **auditoria,
            "matriz": {h: {p: int(v) for p, v in fila.items()} for h, fila in ev.matriz.iterrows()},
            "por_tema": {t: {"auditor": a, "programa_marca": b, "programa_algun_hallazgo": c}
                         for t, (a, b, c) in ev.metricas["por_tema"].items()},
            "hallazgos_en_ok_del_auditor": ev.metricas["codigos_en_humano_ok"],
            "dips": _dips(ev, plan.reglas, llm is not None),
        },
        "casos": casos,
        "tiempos": tiempos,
        "costo_modelo": _costo(llm, memoria) if llm else None,
    }


def _relativa(ruta: Path) -> str:
    try:
        return Path(ruta).resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return str(ruta)


def _texto(valor: object) -> str:
    return "" if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor)


def _metodo(a: Asociacion | None, con_modelo: bool) -> str:
    if a is None or a.metodo == "REGLAS":
        return "reglas"
    if a.metodo == "IA":
        return "modelo_aceptada"
    if a.propuesta:
        return "modelo_descartada"
    return "modelo_ninguna" if con_modelo else "sin_referencia"


def _dips(ev: Evaluacion, reglas: Evaluacion, con_modelo: bool) -> list[dict]:
    solo_reglas = dict(zip(reglas.comparacion["Fault Barcode"], reglas.comparacion["ESTADO IA"]))
    salida = []
    for i, f in ev.comparacion.iterrows():
        a = ev.resultado.asociaciones[i]
        valor = f["DIP Interval"]
        salida.append({
            "barcode": f["Fault Barcode"], "fault_name": f["Fault Name"],
            "intervalo": f"{valor:g} {_texto(f['Interval Type'])}" if pd.notna(valor) else "",
            "auditor": f["ESTADO HUMANO"], "comentario_auditor": _texto(f["COMENTARIO HUMANO"]),
            "tema_auditor": f["TEMA HUMANO"],
            "programa": f["ESTADO IA"], "programa_solo_reglas": solo_reglas[f["Fault Barcode"]],
            "acuerdo": _ACUERDO[f["ACUERDO"]],
            "metodo": _metodo(a, con_modelo), "referencia": f["REFERENCIA ASOCIADA"],
            "propuesta_modelo": a.propuesta if a else None,
            "detalle_modelo": a.detalle if a and a.metodo != "REGLAS" else "",
            "hallazgos": [h for h in _texto(f["HALLAZGOS"]).splitlines() if h],
        })
    return salida


def _costo(llm: ClienteOllama, memoria: tuple[float, float] | None) -> dict:
    m = llm.mediciones
    segundos = sorted(x.segundos for x in m)
    entrada = sum(x.tokens_entrada for x in m)
    salida = sum(x.tokens_salida for x in m)
    s_entrada = sum(x.segundos_entrada for x in m)
    s_salida = sum(x.segundos_salida for x in m)
    return {
        "consultas": len(m),
        "s_por_consulta": round(statistics.mean(segundos), 2) if m else None,
        "s_p95": round(segundos[min(len(m) - 1, round(0.95 * (len(m) - 1)))], 2) if m else None,
        "s_max": round(segundos[-1], 2) if m else None,
        "tokens_entrada_por_consulta": round(entrada / len(m)) if m else None,
        "tokens_salida_por_consulta": round(salida / len(m)) if m else None,
        "tokens_por_s_entrada": round(entrada / s_entrada, 1) if s_entrada else None,
        "tokens_por_s_salida": round(salida / s_salida, 1) if s_salida else None,
        "pct_tiempo_en_prompt": (round(s_entrada / (s_entrada + s_salida) * 100)
                                 if s_entrada + s_salida else None),
        "memoria_gb": round(memoria[0], 2) if memoria else None,
        "memoria_gpu_gb": round(memoria[1], 2) if memoria else None,
    }


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


def linea_base(modo: str) -> Path:
    return CARPETA / f"linea_base_{modo}.json"


def cargar_linea_base(modo: str) -> dict | None:
    base = _leer(linea_base(modo))
    return base if base and base.get("modo") == modo else None


def _anterior(modelo: str) -> dict | None:
    """Último resultado medido con el mismo modelo (sirve para estimar el tiempo)."""
    carpeta = RESULTADOS / "con_modelo"
    candidatos = sorted(carpeta.glob("*.json"), reverse=True) if carpeta.exists() else []
    for ruta in candidatos + [linea_base("con_modelo")]:
        r = _leer(ruta)
        if (r and r.get("modo") == "con_modelo" and r["modelo_local"] == modelo
                and (r.get("costo_modelo") or {}).get("s_por_consulta")):
            return r
    return None


def guardar(resultado: dict, base: dict | None, carpeta: Path | None = None) -> tuple[Path, Path]:
    """Guarda el resultado en JSON (para guardar) y en Markdown (para leer), en la
    subcarpeta de su modo."""
    carpeta = (carpeta or RESULTADOS) / resultado["modo"]
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
    if base["modo"] != resultado["modo"]:
        return "La línea base es de otro modo."
    antes, ahora = base["datos"], resultado["datos"]
    if (antes["dips"], antes["casos"]) != (ahora["dips"], ahora["casos"]):
        return (f"La línea base se midió con otros datos ({antes['dips']} DIPs y "
                f"{antes['casos']} casos; ahora {ahora['dips']} y {ahora['casos']}).")
    return ""


def _nota_modelo(resultado: dict, base: dict | None) -> str:
    if base is None or comparable(resultado, base) or base["modelo_local"] == resultado[
            "modelo_local"]:
        return ""
    return f"La línea base usó el modelo {base['modelo_local']}."


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
        if clave in actuales:
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


def como_se_audita(r: dict, estimado: str = "") -> str:
    """Explicación del método. Se muestra antes de empezar y queda en el Markdown."""
    datos, c, modelo = r["datos"], r["configuracion"], r["modelo_local"]
    v = datos["veredictos_auditor"]
    sin_reglas = f"{datos['dips_sin_referencia_por_reglas']} de {datos['dips']}"
    if modelo:
        tercero = (
            f"3. **Modelo local (solo asocia).** `{modelo}` (Ollama, en este equipo). Se usa "
            f"solo con los DIPs que las reglas no asocian ({sin_reglas}): elige entre "
            f"{c['llm'].get('candidatos', 6)} referencias candidatas o responde NINGUNA. La "
            "sugerencia se descarta si no comparte una palabra distintiva con el Fault Name o si "
            "el intervalo no es compatible. Lo que sugiere queda en REVISAR: nunca decide OK ni "
            "discrepancia. Es lo que hace `auditar --llm`.")
        quinto = (
            f"5. **Casos.** {datos['casos']} Fault Names que las reglas no resuelven, con la "
            f"referencia correcta, en `{datos['archivo_casos']}`. Miden si el modelo acierta y "
            "cuánto tarda, frente a no usar el modelo.")
    else:
        tercero = (
            f"3. **Sin modelo local.** Los DIPs que las reglas no asocian ({sin_reglas}) quedan "
            "en REVISAR sin referencia, y el auditor la busca. Es lo que hace `auditar` sin "
            "`--llm`. No necesita Ollama.")
        quinto = (
            f"5. **Casos.** {datos['casos']} Fault Names que las reglas no resuelven, con la "
            f"referencia correcta, en `{datos['archivo_casos']}`. Sin modelo, los que no tienen "
            "referencia en la tabla quedan bien (sin referencia) y los que sí tienen quedan en "
            "REVISAR sin referencia. Sirven para comparar con el modo con modelo.")
    return "\n".join([
        f"1. **Datos.** {datos['dips']} DIPs Others ya auditados por personas (jul-ago 2026): "
        f"{v['OK']} OK, {v['DISCREPANCIA NO CRÍTICA']} con discrepancia no crítica y "
        f"{v['DISCREPANCIA CRÍTICA']} con discrepancia crítica, en `{datos['archivo']}` "
        "(copia anónima). Son los datos del Excel de entrada del día de la auditoría: en ICAM "
        "esos DIPs ya están corregidos, así que no se completan desde ICAM. Solo entran DIPs "
        "con intervalo y tipo de intervalo, y cada uno se audita con la fecha en que lo "
        "auditó la persona.",
        f"2. **Reglas (deciden el resultado).** Asocian cada DIP a una referencia de "
        f"`{c['referencias']['archivo']}` por palabras clave (`{c['catalogo']['archivo']}`) y "
        "verifican intervalo, tipo de intervalo, parent assy, due date, vencidos, duplicados, "
        "S/N y deferral reference.",
        tercero,
        "4. **Comparación.** El auditor da OK o discrepancia. El programa marca un DIP si lo "
        "deja con discrepancia o en REVISAR.",
        quinto,
    ] + ([f"\n{estimado}"] if estimado else []))


def titulo(r: dict) -> str:
    return f"Benchmark del auditor de DIPs: {MODOS[r['modo']][0].lower()}"


def a_markdown(r: dict, base: dict | None, nombre_json: str = "", completo: bool = True) -> str:
    """Reporte legible. `completo=False` es la versión de la consola: sin el método (ya se
    mostró antes de empezar), sin las severidades y sin el detalle por DIP."""
    modelo = r["modelo_local"]
    partes = [
        f"# {titulo(r)}" if completo else "# Resultado del benchmark",
        f"{_fecha_legible(r['fecha'])} · programa v{r['version_programa']} · "
        + (f"modelo local {modelo}" if modelo else "sin modelo local")
        + f" · duración {duracion(r['tiempos']['total_s'])}",
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
                   f"comparación, copie ese JSON sobre `benchmark/linea_base_{r['modo']}.json`."]
    return "\n\n".join(p for p in partes if p) + "\n"


def _resumen(r: dict, base: dict | None) -> list[str]:
    ind, costo = r["auditoria"]["indicadores"], r["costo_modelo"]
    ci = r["casos"]["indicadores"]
    resueltos = (f"{_de(ci['aciertos_finales'])}, referencias equivocadas aceptadas: "
                 f"{ci['errores_aceptados']['aciertos']}")
    total = duracion(r["tiempos"]["total_s"])
    if costo and costo["consultas"]:
        total += (f"; el modelo respondió {costo['consultas']} consultas de "
                  f"{costo['s_por_consulta']:.1f} s en promedio")
    nota, peores = comparable(r, base), empeoraron(r, base)
    if nota:
        frente_a_base = nota
    elif peores:
        frente_a_base = "**Empeoró:** " + "; ".join(peores)
    else:
        frente_a_base = f"Ningún indicador empeoró (línea base del {_fecha_legible(base['fecha'])})"
    frente_a_base += (" " + _nota_modelo(r, base)).rstrip()
    modo = MODOS[r["modo"]][0] + (f": `{r['modelo_local']}`" if r["modelo_local"] else "")
    return ["## Resumen", _tabla(["Indicador", "Resultado"], [
        ["Modo", modo],
        ["DIPs auditados", f"{r['datos']['dips']} Others"],
        ["Coincide con el auditor (OK o discrepancia)", _de(ind["coincidencia"])],
        ["Discrepancias del auditor que el programa marca", _de(ind["discrepancias_detectadas"])],
        ["OK del auditor que el programa marca con discrepancia",
         _de(ind["falsas_discrepancias"])],
        ["Casos que las reglas no resuelven: bien resueltos", resueltos],
        ["Tiempo total", total],
        ["Frente a la línea base", frente_a_base],
    ])]


def _tabla_indicadores(r: dict, base: dict | None, grupo: str,
                       extra: list[tuple[str, dict]] = ()) -> str:
    """Tabla de indicadores del grupo; `extra` agrega columnas (título, indicadores por clave)."""
    return _tabla(
        ["Indicador", "Actual"] + [t for t, _ in extra] + ["Línea base", "Cambio"],
        [[d, _de(a)] + [_de(v[clave]) if clave in v else "-" for _, v in extra]
         + [f"{p['pct']:.0f}%" if p else "-", _cambio(a, p, sube)]
         for g, clave, d, sube, a, p in _grupos(r, base) if g == grupo],
        set(range(1, 4 + len(extra))))


def _seccion_auditor(r: dict, base: dict | None) -> list[str]:
    aud = r["auditoria"]
    columnas = list(next(iter(aud["matriz"].values())))
    extra = ([("Solo reglas", aud["indicadores_solo_reglas"])]
             if "indicadores_solo_reglas" in aud else [])
    partes = [
        "## 1. Resultado frente al auditor",
        _tabla_indicadores(r, base, "auditoria", extra),
        "**Matriz** (filas: auditor; columnas: programa)",
        _tabla(["Auditor \\ Programa"] + [_CORTO.get(c, c) for c in columnas],
               [[_CORTO.get(h, h)] + [fila[c] for c in columnas]
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
    dips, con_modelo = r["auditoria"]["dips"], r["modelo_local"] is not None
    conteo = {k: sum(d["metodo"] == k for d in dips) for k in METODOS}
    partes = ["## 2. Cómo se asoció cada DIP a su referencia", _tabla(
        ["Método", "DIPs", "Qué pasa con el DIP"],
        [[METODOS[k][0], n, METODOS[k][2]] for k, n in conteo.items() if n], {1})]
    sin_reglas = [d for d in dips if d["metodo"] != "reglas"]
    if not sin_reglas:
        return partes

    def fila(d: dict) -> list:
        modelo = METODOS[d["metodo"]][1] + (f" ({d['propuesta_modelo']})"
                                            if d["propuesta_modelo"] else "")
        return ([d["barcode"], d["fault_name"][:60], d["intervalo"]]
                + ([modelo] if con_modelo else [])
                + [_CORTO.get(d["programa"], d["programa"]),
                   _CORTO.get(d["auditor"], d["auditor"])])
    partes += [
        "**DIPs que no asocian las reglas**" + (" (consultados al modelo)" if con_modelo else ""),
        _tabla(["Barcode", "Fault Name", "Intervalo"] + (["Modelo"] if con_modelo else [])
               + ["Programa", "Auditor"], [fila(d) for d in sin_reglas]),
    ]
    if con_modelo:
        cambiaron = sum(d["programa"] != d["programa_solo_reglas"] for d in sin_reglas)
        partes.append(f"El modelo cambió el estado de {cambiaron} de estos DIPs frente a la "
                      "auditoría solo con reglas.")
    return partes


def _seccion_casos(r: dict, base: dict | None) -> list[str]:
    casos = r["casos"]
    detalle = casos["casos"]
    positivos = sum(d["grupo"] == "positivo" for d in detalle)
    partes = [
        "## 3. Casos que las reglas no resuelven",
        f"{len(detalle)} Fault Names con errores de escritura, abreviaturas, español o sinónimos: "
        f"{positivos} con referencia en la tabla y {len(detalle) - positivos} sin referencia.",
    ]
    if not r["modelo_local"]:
        asociados = casos["indicadores"]["con_referencia"]["aciertos"]
        return partes + [
            _tabla_indicadores(r, base, "casos"),
            f"Sin modelo, las reglas resuelven {asociados} de los {positivos} casos con referencia "
            "(errores de escritura y siglas); el resto queda en REVISAR sin referencia y el auditor "
            "la busca. Los que no tienen referencia quedan bien."]
    comparacion = casos["comparacion"]
    partes += [
        "*Actual* es el modelo después de la validación. *Solo reglas* es lo que pasa con los "
        "mismos casos sin modelo (modo sin modelo). *Más parecido* elige siempre la referencia "
        "más parecida al Fault Name y pasa por la misma validación que el modelo; el programa "
        "no la usa.",
        _tabla_indicadores(r, base, "casos", [("Solo reglas", comparacion["solo_reglas"]),
                                              ("Más parecido", comparacion.get("mas_parecido",
                                                                               {}))]),
    ]
    errores = [d for d in detalle if not d["acierto_final"]]
    if errores:
        partes += ["**Casos con error**", _tabla(
            ["Fault Name", "Intervalo", "Esperado", "Modelo", "Final"],
            [[d["fault_name"], d["intervalo"], d["esperado"], d["respuesta_modelo"],
              d["final"] + (" (ACEPTADA)" if d["error_aceptado"] else "")] for d in errores])]
    return partes


def _seccion_tiempos(r: dict, base: dict | None) -> list[str]:
    t, costo, n = r["tiempos"], r["costo_modelo"], r["datos"]
    usar_base = base if not comparable(r, base) else {}
    b_t = usar_base.get("tiempos", {})
    b_c = usar_base.get("costo_modelo") or {}
    con_modelo = r["modelo_local"] is not None
    filas = [["Preparación: lectura de datos y referencias, auditoría solo con reglas",
              duracion(t["preparacion_s"]), "-", duracion(b_t.get("preparacion_s"))]]
    if con_modelo:
        filas += [
            ["Carga del modelo en memoria", duracion(t.get("carga_modelo_s")), "-",
             duracion(b_t.get("carga_modelo_s"))],
            [f"Auditoría de {n['dips']} DIPs", duracion(t["auditoria_s"]),
             t["auditoria_consultas"], duracion(b_t.get("auditoria_s"))]]
    filas += [
        [f"Casos ({n['casos']})", duracion(t.get("casos_s")), t.get("casos_consultas", 0),
         duracion(b_t.get("casos_s"))],
        ["**Total**", f"**{duracion(t['total_s'])}**",
         t["auditoria_consultas"] + t.get("casos_consultas", 0), duracion(b_t.get("total_s"))],
    ]
    partes = ["## 4. Tiempos y costo computacional",
              _tabla(["Etapa", "Tiempo", "Consultas al modelo", "Línea base"], filas, {1, 2, 3})]
    if not con_modelo:
        partes.append("Sin modelo no hay consultas ni memoria adicional: todo lo hacen las "
                      "reglas en Python.")
    if costo and costo["consultas"]:
        def fila(nombre: str, clave: str, formato: str = "{:.1f}", sufijo: str = "") -> list:
            def f(v):
                return "-" if v is None else formato.format(v) + sufijo
            return [nombre, f(costo.get(clave)), f(b_c.get(clave))]
        en_gpu = (costo.get("memoria_gpu_gb") or 0) > 0.1
        partes += [
            _tabla(["Consultas al modelo", "Actual", "Línea base"], [
                fila("Segundos por consulta (promedio)", "s_por_consulta"),
                fila("Segundos por consulta (p95)", "s_p95"),
                fila("Tokens de entrada por consulta (prompt)", "tokens_entrada_por_consulta",
                     "{:.0f}"),
                fila("Velocidad al procesar el prompt", "tokens_por_s_entrada",
                     sufijo=" tokens/s"),
                fila("Tokens de salida por consulta (respuesta)", "tokens_salida_por_consulta",
                     "{:.0f}"),
                fila("Velocidad al generar la respuesta", "tokens_por_s_salida",
                     sufijo=" tokens/s"),
                fila("Tiempo procesando el prompt", "pct_tiempo_en_prompt", "{:.0f}", "%"),
                fila("Memoria del modelo", "memoria_gb", "{:.1f}", " GB"),
            ], {1, 2}),
            f"El modelo corrió en {'GPU' if en_gpu else 'CPU'}. En CPU, el tiempo depende sobre "
            "todo del largo del prompt (candidatos) y de la respuesta (justificación)."]
    e = r["equipo"]
    partes.append(f"Equipo: {e['procesador']}, {e['hilos']} hilos, "
                  f"{e['ram_gb'] or '?'} GB de RAM, {e['sistema']}.")
    return partes


def _seccion_configuracion(r: dict, completo: bool) -> list[str]:
    c = r["configuracion"]
    tol = c["tolerancias"]

    def si_no(v: object) -> str:
        return "sí" if v else "no"
    filas = []
    if "llm" in c:
        llm = c["llm"]
        filas += [
            ["Modelo local", llm.get("modelo"), "llm.modelo"],
            ["Referencias candidatas por consulta", llm.get("candidatos", 6), "llm.candidatos"],
            ["Pedir justificación al modelo", si_no(llm.get("justificacion", True)),
             "llm.justificacion"],
            ["Modo thinking", si_no(llm.get("pensar")), "llm.pensar"],
            ["Temperatura", llm.get("temperatura", 0), "llm.temperatura"],
            ["Contexto / máximo de la respuesta (tokens)",
             f"{llm.get('contexto_tokens', 2048)} / {llm.get('max_tokens_respuesta', 300)}",
             "llm.contexto_tokens, llm.max_tokens_respuesta"],
            ["Solo CPU", si_no(llm.get("solo_cpu")), "llm.solo_cpu"],
            ["Fracción mínima del TA para aceptar una sugerencia",
             llm.get("fraccion_minima_ta", 0.2), "llm.fraccion_minima_ta"],
        ]
    filas += [
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
    if "llm" in c:
        partes.append("Las instrucciones que recibe el modelo están en `dips_audit/llm.py` "
                      "(`_SISTEMA`).")
    if completo:
        partes += ["**Severidad de cada hallazgo** (`severidades`)", _tabla(
            ["Hallazgo", "Severidad"], [[f"`{k}`", v] for k, v in c["severidades"].items()])]
    return partes


def _desacuerdos(dips: list[dict]) -> list[str]:
    partes = ["## 6. Desacuerdos con el auditor"]
    for acuerdo in ("Solo el programa marca", "Solo el auditor marca"):
        grupo = [d for d in dips if d["acuerdo"] == acuerdo]
        partes.append(f"### {acuerdo} ({len(grupo)})")
        for d in grupo:
            referencia = d["referencia"] or "sin referencia"
            lineas = [
                f"**{d['barcode']}** · {d['fault_name']}",
                f"- Intervalo: {d['intervalo'] or 'sin dato'} · Referencia: {referencia} "
                f"({METODOS[d['metodo']][0].lower()})",
                f"- Auditor: **{d['auditor']}**"
                + (f". {d['comentario_auditor']}" if d["comentario_auditor"] else ""),
                f"- Programa: **{d['programa']}**",
            ] + [f"  - {h}" for h in d["hallazgos"]]
            partes.append("\n".join(lineas))
    return partes
