"""Cliente mínimo para un modelo local servido por Ollama.

El modelo solo elige una categoría de una lista cerrada (o NINGUNA). La respuesta
se fuerza con un esquema JSON y temperatura 0; nunca decide el veredicto.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from .referencias import EntradaCatalogo

_SISTEMA = (
    "Eres un asistente de auditoría de mantenimiento aeronáutico (Boeing 737). "
    "Recibes el Fault Name de un DIP (deferred item) y una lista cerrada de categorías. "
    "Indica a cuál categoría corresponde el DIP. Usa el intervalo del DIP como evidencia: "
    "normalmente coincide con el TA de la categoría correcta. Si ninguna corresponde "
    "claramente, responde NINGUNA. No inventes categorías ni supongas información que no "
    "esté en el texto. La justificación debe tener como máximo 25 palabras."
)


class ErrorLLM(Exception):
    pass


class ClienteOllama:
    def __init__(self, url: str, modelo: str, timeout: int = 120, pensar: bool = False,
                 solo_cpu: bool = False):
        self.url = url.rstrip("/")
        self.modelo = modelo
        self.timeout = timeout
        self.pensar = pensar  # modo "thinking": más lento, a veces más preciso
        self.solo_cpu = solo_cpu  # ignora la GPU aunque exista (equipos del departamento)
        self._cache: dict[tuple[str, tuple[str, ...]], tuple[str | None, str]] = {}
        self.consultas = 0

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

    def memoria_gb(self) -> float | None:
        """RAM que ocupa el modelo cargado (según Ollama)."""
        try:
            with urllib.request.urlopen(self.url + "/api/ps", timeout=5) as resp:
                for m in json.loads(resp.read())["models"]:
                    if m["name"] == self.modelo or m["model"] == self.modelo:
                        return m["size"] / 1024 ** 3
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            pass
        return None

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
        esquema = {
            "type": "object",
            "properties": {
                "categoria": {"type": "string", "enum": [c.id for c in candidatos] + ["NINGUNA"]},
                "justificacion": {"type": "string", "maxLength": 200},
            },
            "required": ["categoria", "justificacion"],
        }
        try:
            respuesta = self._post("/api/chat", {
                "model": self.modelo,
                "messages": [{"role": "system", "content": _SISTEMA},
                             {"role": "user", "content": usuario}],
                "format": esquema,
                "stream": False,
                "think": self.pensar,
                "keep_alive": "15m",
                "options": {"temperature": 0, "num_ctx": 4096 if self.pensar else 2048,
                            "num_predict": 2048 if self.pensar else 300,
                            **({"num_gpu": 0} if self.solo_cpu else {})},
            })
        except (urllib.error.URLError, OSError) as e:
            raise ErrorLLM(f"Error consultando el modelo: {e}") from e
        self.consultas += 1
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
