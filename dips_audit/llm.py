"""Cliente mínimo para un modelo local servido por Ollama.

El modelo solo elige una categoría de una lista cerrada (o NINGUNA). La respuesta
se fuerza con un esquema JSON; nunca decide el veredicto. Los parámetros se
ajustan en config/config.yaml (sección llm).
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .referencias import EntradaCatalogo

# Instrucciones del modelo. Si se cambian, mida el efecto con el benchmark.
_SISTEMA = (
    "Eres un asistente de auditoría de mantenimiento aeronáutico (Boeing 737). "
    "Recibes el Fault Name de un DIP (deferred item) y una lista cerrada de categorías. "
    "Indica a cuál categoría corresponde el DIP. Usa el intervalo del DIP como evidencia: "
    "normalmente coincide con el TA de la categoría correcta. Si ninguna corresponde "
    "claramente, responde NINGUNA. No inventes categorías ni supongas información que no "
    "esté en el texto."
)
_SISTEMA_JUSTIFICACION = " La justificación debe tener como máximo 25 palabras."
# Tiempo que Ollama mantiene el modelo en memoria después de la última consulta.
_MANTENER_CARGADO = "15m"


class ErrorLLM(Exception):
    pass


@dataclass
class Medicion:
    """Costo de una consulta al modelo, según Ollama."""
    segundos: float           # tiempo total de la consulta (reloj)
    tokens_entrada: int       # tokens del prompt
    tokens_salida: int        # tokens de la respuesta
    segundos_entrada: float   # procesando el prompt
    segundos_salida: float    # generando la respuesta


class ClienteOllama:
    def __init__(self, url: str, modelo: str, timeout: int = 300, pensar: bool = False,
                 solo_cpu: bool = False, justificacion: bool = True, temperatura: float = 0,
                 contexto_tokens: int = 2048, max_tokens_respuesta: int = 300):
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.timeout = timeout
        self.pensar = pensar  # modo "thinking": más lento, a veces más preciso
        self.solo_cpu = solo_cpu  # ignora la GPU aunque exista (equipos del departamento)
        self.justificacion = justificacion
        self.temperatura = temperatura
        self.contexto_tokens = contexto_tokens
        self.max_tokens_respuesta = max_tokens_respuesta
        self._cache: dict[tuple[str, tuple[str, ...]], tuple[str | None, str]] = {}
        self.mediciones: list[Medicion] = []

    @classmethod
    def desde_config(cls, c: dict, modelo: str | None = None) -> ClienteOllama:
        return cls(c["url"], modelo or c["modelo"], c.get("timeout_segundos", 300),
                   pensar=c.get("pensar", False), solo_cpu=c.get("solo_cpu", False),
                   justificacion=c.get("justificacion", True),
                   temperatura=c.get("temperatura", 0),
                   contexto_tokens=c.get("contexto_tokens", 2048),
                   max_tokens_respuesta=c.get("max_tokens_respuesta", 300))

    @property
    def consultas(self) -> int:
        return len(self.mediciones)

    def _opciones(self) -> dict:
        return {"temperature": self.temperatura,
                "num_ctx": max(self.contexto_tokens, 4096) if self.pensar else self.contexto_tokens,
                "num_predict": 2048 if self.pensar else self.max_tokens_respuesta,
                **({"num_gpu": 0} if self.solo_cpu else {})}

    def _post(self, ruta: str, cuerpo: dict) -> dict:
        req = urllib.request.Request(
            self.url + ruta, data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Modelos sin modo "thinking" rechazan el parámetro: se reintenta sin él.
            if e.code == 400 and "think" in cuerpo:
                cuerpo = {k: v for k, v in cuerpo.items() if k != "think"}
                return self._post(ruta, cuerpo)
            raise

    def memoria(self) -> tuple[float, float] | None:
        """(GB totales, GB en GPU) que ocupa el modelo cargado, según Ollama."""
        try:
            with urllib.request.urlopen(self.url + "/api/ps", timeout=5) as resp:
                for m in json.loads(resp.read())["models"]:
                    if m["name"] == self.modelo or m["model"] == self.modelo:
                        return m["size"] / 1024 ** 3, m.get("size_vram", 0) / 1024 ** 3
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            pass
        return None

    def cargar(self) -> float:
        """Carga el modelo en memoria sin consultarlo. Devuelve los segundos que tardó."""
        inicio = time.perf_counter()
        try:
            self._post("/api/generate", {"model": self.modelo, "keep_alive": _MANTENER_CARGADO,
                                         "options": self._opciones()})
        except (urllib.error.URLError, OSError) as e:
            raise ErrorLLM(f"No se pudo cargar el modelo: {e}") from e
        return time.perf_counter() - inicio

    def descargar_de_memoria(self) -> None:
        try:
            self._post("/api/generate", {"model": self.modelo, "keep_alive": 0})
        except (urllib.error.URLError, OSError):
            pass

    def verificar(self) -> None:
        """Lanza ErrorLLM si Ollama no está corriendo o el modelo no está descargado."""
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=5) as resp:
                modelos = [m["name"] for m in json.loads(resp.read())["models"]]
        except (urllib.error.URLError, OSError) as e:
            raise ErrorLLM(f"No se pudo conectar con Ollama en {self.url} ({e}). "
                           "¿Está abierto Ollama?") from e
        if self.modelo not in modelos and f"{self.modelo}:latest" not in modelos:
            raise ErrorLLM(f"El modelo '{self.modelo}' no está descargado. "
                           f"Ejecute: ollama pull {self.modelo}")

    def elegir_categoria(self, fault_name: str, candidatos: list[EntradaCatalogo],
                         intervalo: str = "") -> tuple[EntradaCatalogo | None, str]:
        if not candidatos:
            return None, "Sin candidatos."
        clave = (fault_name.strip().upper() + "|" + intervalo, tuple(c.id for c in candidatos))
        if clave in self._cache:
            id_, justificacion = self._cache[clave]
        else:
            id_, justificacion = self._consultar(fault_name, candidatos, intervalo)
            self._cache[clave] = (id_, justificacion)
        elegido = next((c for c in candidatos if c.id == id_), None)
        return elegido, justificacion

    def _consultar(self, fault_name: str, candidatos: list[EntradaCatalogo], intervalo: str
                   ) -> tuple[str | None, str]:
        # Líneas cortas: en CPU el costo principal es procesar el prompt.
        lista = "\n".join(
            f"- {c.id}: {c.nombre} | referencia: "
            f"{'; '.join(r.descripcion for r in c.referencias)[:90]} | TA: "
            f"{'; '.join(dict.fromkeys(r.ta for r in c.referencias))[:60]}"
            for c in candidatos)
        usuario = (f"Fault Name: {fault_name}\n"
                   + (f"Intervalo del DIP: {intervalo}\n" if intervalo else "")
                   + f"\nCategorías posibles:\n{lista}\n- NINGUNA")
        propiedades = {"categoria": {"type": "string",
                                     "enum": [c.id for c in candidatos] + ["NINGUNA"]}}
        if self.justificacion:
            propiedades["justificacion"] = {"type": "string", "maxLength": 200}
        esquema = {"type": "object", "properties": propiedades, "required": list(propiedades)}
        sistema = _SISTEMA + (_SISTEMA_JUSTIFICACION if self.justificacion else "")
        cuerpo = {
            "model": self.modelo,
            "messages": [{"role": "system", "content": sistema},
                         {"role": "user", "content": usuario}],
            "format": esquema,
            "stream": False,
            "think": self.pensar,
            "keep_alive": _MANTENER_CARGADO,
            "options": self._opciones(),
        }
        # Un segundo intento si la consulta falla (p. ej. excede el tiempo porque el
        # equipo se suspendió). Solo se mide el intento que responde.
        for intento in range(2):
            inicio = time.perf_counter()
            try:
                respuesta = self._post("/api/chat", cuerpo)
                break
            except (urllib.error.URLError, OSError) as e:
                if intento:
                    raise ErrorLLM(f"Error consultando el modelo (dos intentos): {e}") from e
        self.mediciones.append(Medicion(
            segundos=time.perf_counter() - inicio,
            tokens_entrada=respuesta.get("prompt_eval_count", 0),
            tokens_salida=respuesta.get("eval_count", 0),
            segundos_entrada=respuesta.get("prompt_eval_duration", 0) / 1e9,
            segundos_salida=respuesta.get("eval_duration", 0) / 1e9))
        contenido = respuesta.get("message", {}).get("content", "")
        try:
            datos = json.loads(contenido)
            categoria = str(datos["categoria"])
            justificacion = str(datos.get("justificacion", ""))[:300]
        except (KeyError, ValueError, TypeError):
            # JSON cortado por el límite de tokens: se rescata solo la categoría,
            # que el esquema obliga a generar primero.
            m = re.search(r'"categoria"\s*:\s*"([A-Z0-9_]+)"', contenido)
            if not m:
                return None, "Respuesta del modelo no válida."
            categoria, justificacion = m.group(1), "(justificación incompleta)"
        if categoria not in {c.id for c in candidatos}:
            return None, justificacion or "El modelo respondió NINGUNA."
        return categoria, justificacion
