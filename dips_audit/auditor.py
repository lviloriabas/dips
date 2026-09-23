"""Orquesta la auditoría: carga, asociación, reglas, duplicados y resultado."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from .asociacion import Asociacion, asociar, similares_en_tabla
from .cargador import Lote, cargar_export
from .llm import ClienteOllama
from .referencias import Catalogo, EntradaCatalogo, cargar_catalogo, cargar_referencias
from .reglas import (Contexto, Hallazgo, auditar_dip, buscar_duplicados, buscar_sn_repetidos,
                     estado_final)

RAIZ = Path(__file__).resolve().parent.parent
FUERA_DE_ALCANCE = "FUERA DE ALCANCE"


def cargar_configuracion(ruta: Path | None = None) -> dict:
    ruta = Path(ruta) if ruta else RAIZ / "config" / "config.yaml"
    config = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    for clave in ("referencias", "catalogo", "carpeta_salida"):
        p = Path(config[clave])
        config[clave] = p if p.is_absolute() else RAIZ / p
    return config


@dataclass
class ResultadoAuditoria:
    lote: Lote
    filas: pd.DataFrame        # una fila por DIP (resultado + datos clave)
    hallazgos: pd.DataFrame    # una fila por hallazgo
    advertencias: list[str] = field(default_factory=list)
    segundos: float = 0.0
    consultas_llm: int = 0

    def conteo_estados(self) -> dict[str, int]:
        return self.filas["ESTADO IA"].value_counts().to_dict()


class Auditor:
    def __init__(self, config: dict, llm: ClienteOllama | None = None,
                 fecha_auditoria: date | None = None):
        self.config = config
        self.llm = llm
        self.fecha_auditoria = fecha_auditoria or date.today()
        referencias = cargar_referencias(config["referencias"], config.get("hoja_referencias",
                                                                             "References"))
        self.catalogo: Catalogo = cargar_catalogo(config["catalogo"], referencias)
        self.tipos = {t.upper() for t in config.get("tipos_auditados", ["Others"])}
        tol = config.get("tolerancias", {})
        self._ctx_base = dict(
            severidades=config.get("severidades", {}),
            tol_dias=tol.get("dias", 1), meses_min=tol.get("meses_min", 30),
            meses_max=tol.get("meses_max", 31))

    def contexto(self, fecha: date | None = None) -> Contexto:
        return Contexto(fecha_referencia=fecha or self.fecha_auditoria, **self._ctx_base)

    def auditar_archivo(self, ruta: Path, hoja: str | None = None) -> ResultadoAuditoria:
        return self.auditar_lote(cargar_export(ruta, hoja))

    def auditar_lote(self, lote: Lote, fechas_referencia: list[date] | None = None
                     ) -> ResultadoAuditoria:
        inicio = time.perf_counter()
        consultas_previas = self.llm.consultas if self.llm else 0
        dips = lote.datos.to_dict("records")
        en_alcance = [not d["tipo"] or d["tipo"].upper() in self.tipos for d in dips]

        asociaciones: list[Asociacion | None] = []
        for dip, alcance in zip(dips, en_alcance):
            asociaciones.append(
                asociar(dip["nombre"], self.catalogo, self.llm, dip["intervalo"], dip["unidad"])
                if alcance else None)
        entradas = [a.entrada if a else None for a in asociaciones]
        # Duplicados y S/N repetidos se buscan sobre el subconjunto en alcance;
        # luego se remapean los índices al lote completo.
        indices_alcance = [i for i, a in enumerate(en_alcance) if a]
        dips_alcance = [dips[i] for i in indices_alcance]
        duplicados = buscar_duplicados(dips_alcance, [entradas[i] for i in indices_alcance],
                                       self._ctx_base["tol_dias"])
        duplicados = {indices_alcance[k]: v for k, v in duplicados.items()}
        sn_repetidos = {indices_alcance[k]: v
                        for k, v in buscar_sn_repetidos(dips_alcance).items()}

        filas, hallazgos = [], []
        for i, (dip, alcance, asoc) in enumerate(zip(dips, en_alcance, asociaciones)):
            if not alcance:
                filas.append(self._fila(dip, None, None, [], [], FUERA_DE_ALCANCE, ""))
                continue
            fecha = fechas_referencia[i] if fechas_referencia else None
            ctx = self.contexto(fecha)
            r = auditar_dip(dip, asoc.entrada, ctx)
            if asoc.metodo == "IA":
                r.hallazgos.append(Hallazgo(
                    "asociacion_ia", "Reference Match", "REVISAR",
                    f"Referencia sugerida por el modelo local: {asoc.entrada.nombre}. "
                    f"Confirmar. ({asoc.detalle})"))
            elif asoc.entrada is None:
                if asoc.metodo == "AMBIGUA":
                    motivo = f"coincide con varias referencias ({', '.join(asoc.candidatos[:3])})"
                else:
                    motivo = "no se encontró en el catálogo de referencias Others"
                similares = similares_en_tabla(dip["nombre"], self.catalogo)
                pista = "; ".join(f"'{f.descripcion}' ({f.tipo}, fila {f.fila})"
                                  for f, _ in similares)
                r.hallazgos.append(Hallazgo(
                    "sin_referencia", "Missing Reference in Table", "REVISAR",
                    f"El DIP {motivo}. Revisar manualmente."
                    + (f" Parecido en la tabla: {pista}." if pista else "")
                    + (f" IA: {asoc.detalle}" if asoc.detalle else "")))
                otros_tipos = {f.tipo for f, p in similares if p >= 90} - self.tipos
                if otros_tipos and dip["tipo"]:
                    r.hallazgos.append(Hallazgo(
                        "tipo_dip_distinto_a_referencia", "Incorrect DIP Type", "OBSERVACION",
                        f"Abierto como {dip['tipo']}, pero se parece a una referencia "
                        f"{'/'.join(sorted(otros_tipos))}."))
            severidades = self._ctx_base["severidades"]
            if i in duplicados:
                otro_barcode, otro_nombre = duplicados[i]
                r.hallazgos.append(Hallazgo(
                    "duplicado", "Duplicated DIP", severidades.get("duplicado", "NO CRITICA"),
                    f"Posible DIP duplicado de {otro_barcode} ('{otro_nombre}'): mismo avión, "
                    f"mismo componente y abiertos al mismo tiempo."))
            elif i in sn_repetidos:
                r.hallazgos.append(Hallazgo(
                    "sn_repetido", "Incorrect S/N", severidades.get("sn_repetido", "NO CRITICA"),
                    f"El mismo S/N aparece en otro DIP activo del avión: "
                    f"{', '.join(sn_repetidos[i])}."))
            estado = estado_final(r.hallazgos)
            comentario = self._comentario(r)
            filas.append(self._fila(dip, asoc, r, r.hallazgos, r.manuales, estado, comentario))
            for h in r.hallazgos:
                hallazgos.append({
                    "Fila Excel": dip["fila"], "Fault Barcode": dip["barcode"],
                    "Aircraft": dip["avion"], "Fault Name": dip["nombre"],
                    "Severidad": h.severidad, "Tipo de discrepancia": h.categoria,
                    "Código": h.codigo, "Detalle": h.mensaje,
                })

        resultado = ResultadoAuditoria(
            lote=lote, filas=pd.DataFrame(filas),
            hallazgos=pd.DataFrame(hallazgos, columns=[
                "Fila Excel", "Fault Barcode", "Aircraft", "Fault Name", "Severidad",
                "Tipo de discrepancia", "Código", "Detalle"]),
            advertencias=list(lote.notas),
            segundos=time.perf_counter() - inicio,
            consultas_llm=(self.llm.consultas - consultas_previas) if self.llm else 0,
        )
        return resultado

    @staticmethod
    def _comentario(r) -> str:
        partes = []
        if r.intervalo_ok:
            partes.append("T/A aperturado correctamente")
        for h in r.hallazgos:
            if h.severidad in ("CRITICA", "NO CRITICA"):
                partes.append(h.mensaje)
        return " // ".join(partes)

    @staticmethod
    def _fila(dip: dict, asoc: Asociacion | None, r, hallazgos: list[Hallazgo],
              manuales: list[str], estado: str, comentario: str) -> dict:
        entrada: EntradaCatalogo | None = asoc.entrada if asoc else None
        orden = {"CRITICA": 0, "NO CRITICA": 1, "REVISAR": 2, "OBSERVACION": 3}
        hallazgos = sorted(hallazgos, key=lambda h: orden[h.severidad])
        return {
            "Fila Excel": dip["fila"],
            "Fault Barcode": dip["barcode"],
            "Aircraft": dip["avion"],
            "Flota": dip.get("flota") or "",
            "Fault Name": dip["nombre"],
            "DIP Interval": dip["intervalo"],
            "Interval Type": dip["tipo_intervalo_original"],
            "Fault Status": dip["estado"],
            "ESTADO IA": estado,
            "HALLAZGOS": "\n".join(f"[{h.severidad}] {h.mensaje}" for h in hallazgos),
            "TIPO DE DISCREPANCIA": ", ".join(dict.fromkeys(
                h.categoria for h in hallazgos if h.severidad in ("CRITICA", "NO CRITICA"))),
            "COMENTARIO SUGERIDO": comentario,
            "VERIFICACIÓN MANUAL": "\n".join(f"- {m}" for m in manuales),
            "REFERENCIA ASOCIADA": entrada.nombre if entrada else "",
            "ASOCIACIÓN": (f"{asoc.metodo} ({asoc.confianza})" if asoc else ""),
            "TA SEGÚN REFERENCIA": "\n".join(
                f"{x.descripcion}: {x.ta}" + (f" / RIR {x.rir}" if x.rir else "")
                for x in entrada.referencias) if entrada else "",
            "REFERENCIA TÉCNICA ESPERADA": entrada.referencias_tecnicas if entrada else "",
        }
