"""Compara modelos locales en la tarea real: asociar DIPs que las reglas no resuelven.

Para cada modelo mide:
  - aciertos del modelo "crudo" (su respuesta tal cual),
  - aciertos finales (después de las validaciones deterministas),
  - asociaciones erróneas aceptadas (lo peligroso: una referencia equivocada),
  - latencia por consulta, tiempo de carga y RAM ocupada.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .asociacion import _equivalentes, asociar
from .llm import ClienteOllama, ErrorLLM
from .referencias import Catalogo, normalizar_unidad

CASOS = Path(__file__).resolve().parent.parent / "tests" / "datos" / "benchmark_llm.yaml"


@dataclass
class Caso:
    nombre: str
    intervalo: float | None
    unidad: str | None
    esperado: str  # ID del catálogo o NINGUNA


@dataclass
class ResultadoModelo:
    modelo: str
    pensar: bool
    solo_cpu: bool = False
    carga_s: float = 0.0
    ram_gb: float | None = None
    latencias: list[float] = field(default_factory=list)
    detalle: list[dict] = field(default_factory=list)
    error: str = ""

    def _cuenta(self, clave: str, grupo: str | None = None) -> int:
        return sum(1 for d in self.detalle if d[clave] and (grupo is None or d["grupo"] == grupo))

    @property
    def total(self) -> int:
        return len(self.detalle)

    @property
    def aciertos_crudos(self) -> int:
        return self._cuenta("acierto_crudo")

    @property
    def aciertos_finales(self) -> int:
        return self._cuenta("acierto_final")

    @property
    def errores_aceptados(self) -> int:
        return self._cuenta("error_aceptado")

    @property
    def positivos_ok(self) -> int:
        return self._cuenta("acierto_final", "positivo")

    @property
    def negativos_ok(self) -> int:
        return self._cuenta("acierto_final", "negativo")

    @property
    def latencia_media(self) -> float:
        return statistics.mean(self.latencias) if self.latencias else 0.0

    @property
    def latencia_p95(self) -> float:
        if not self.latencias:
            return 0.0
        orden = sorted(self.latencias)
        return orden[min(len(orden) - 1, int(round(0.95 * (len(orden) - 1))))]


def cargar_casos(ruta: Path = CASOS) -> list[tuple[str, Caso]]:
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    casos = []
    for grupo, clave in (("positivo", "positivos"), ("negativo", "negativos")):
        for c in datos[clave]:
            valor, _, unidad = c["intervalo"].partition(" ")
            casos.append((grupo, Caso(c["nombre"], float(valor), normalizar_unidad(unidad),
                                      c.get("esperado", "NINGUNA"))))
    return casos


class _Registro:
    """Envuelve el cliente para guardar la respuesta cruda del modelo."""

    def __init__(self, cliente: ClienteOllama):
        self.cliente = cliente
        self.crudo: str | None = None
        self.justificacion = ""

    def elegir_categoria(self, nombre, candidatos, intervalo=""):
        elegido, justificacion = self.cliente.elegir_categoria(nombre, candidatos, intervalo)
        self.crudo = elegido.id if elegido else "NINGUNA"
        self.justificacion = justificacion
        return elegido, justificacion


def seleccionar(casos: list[tuple[str, Caso]], n: int | None) -> list[tuple[str, Caso]]:
    """Subconjunto balanceado (mitad con referencia, mitad sin) para medir velocidad."""
    if not n or n >= len(casos):
        return casos
    pos = [c for c in casos if c[0] == "positivo"]
    neg = [c for c in casos if c[0] == "negativo"]
    return pos[: n - n // 2] + neg[: n // 2]


def evaluar_modelo(modelo: str, catalogo: Catalogo, casos: list[tuple[str, Caso]], url: str,
                   pensar: bool = False, timeout: int = 600, progreso=None,
                   solo_cpu: bool = False) -> ResultadoModelo:
    res = ResultadoModelo(modelo=modelo, pensar=pensar, solo_cpu=solo_cpu)
    cliente = ClienteOllama(url, modelo, timeout=timeout, pensar=pensar, solo_cpu=solo_cpu)
    try:
        cliente.verificar()
        # Carga del modelo en memoria (primera consulta, no se cuenta en latencia).
        inicio = time.perf_counter()
        cliente.elegir_categoria("CARGA", catalogo.entradas[:2])
        res.carga_s = time.perf_counter() - inicio
        res.ram_gb = cliente.memoria_gb()

        registro = _Registro(cliente)
        for grupo, caso in casos:
            registro.crudo, registro.justificacion = None, ""
            inicio = time.perf_counter()
            a = asociar(caso.nombre, catalogo, registro, caso.intervalo, caso.unidad)
            res.latencias.append(time.perf_counter() - inicio)
            final = a.entrada.id if a.entrada else "NINGUNA"
            # Elegir una entrada equivalente (mismas verificaciones) no es un error.
            esperado = catalogo.por_id(caso.esperado)
            correcto = final == caso.esperado or (
                a.entrada is not None and esperado is not None
                and _equivalentes([a.entrada, esperado]))
            crudo = catalogo.por_id(registro.crudo or "")
            crudo_ok = registro.crudo == caso.esperado or (
                crudo is not None and esperado is not None and _equivalentes([crudo, esperado]))
            res.detalle.append({
                "modelo": modelo + (" (thinking)" if pensar else ""),
                "grupo": grupo, "nombre": caso.nombre,
                "intervalo": f"{caso.intervalo:g} {caso.unidad}", "esperado": caso.esperado,
                "respuesta_modelo": registro.crudo or "(reglas)", "final": final,
                "acierto_crudo": crudo_ok,
                "acierto_final": correcto,
                "error_aceptado": a.entrada is not None and not correcto,
                "segundos": round(res.latencias[-1], 2),
                "justificacion": registro.justificacion,
            })
            if progreso:
                progreso()
    except ErrorLLM as e:
        res.error = str(e)
    finally:
        cliente.descargar_de_memoria()
    return res
